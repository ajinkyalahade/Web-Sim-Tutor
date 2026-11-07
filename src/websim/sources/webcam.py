"""Webcam capture and device enumeration."""

from __future__ import annotations

import logging
import os
import platform
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

# Windows Media Foundation can take 10+ s to open a webcam with hardware
# transforms on; this is OpenCV's documented switch. Read lazily by OpenCV.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import cv2  # noqa: E402
import numpy as np

from ..imaging import FRAME_SIZE, fit_cover  # noqa: E402

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    backend: int = 0


def _is_virtual(name: str) -> bool:
    return "obs virtual camera" in name.lower()


def _enumerate(system: str) -> list[CameraDevice]:
    from cv2_enumerate_cameras import enumerate_cameras

    if system == "Windows":
        # enumerate_cameras() with no backend lists every camera twice (MSMF as
        # 1400+n, DirectShow as 700+n). Use one backend, with plain indices and
        # an explicit backend, so the list has no duplicates and the index
        # always means the same device. DirectShow opens fast and supports MJPG;
        # Media Foundation is only a fallback.
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            try:
                found = list(enumerate_cameras(backend))
            except Exception as exc:  # noqa: BLE001
                log.debug("Camera enumeration (backend %s) failed: %s", backend, exc)
                continue
            if found:
                return [
                    CameraDevice(int(info.index), str(info.name or f"Camera {info.index}"), int(backend))
                    for info in found
                ]
        return []
    return [
        CameraDevice(
            int(getattr(info, "index", 0)),
            str(getattr(info, "name", "") or f"Camera {getattr(info, 'index', 0)}"),
            int(getattr(info, "backend", 0) or 0),
        )
        for info in enumerate_cameras()
    ]


def list_cameras(include_virtual: bool = False, system: str | None = None) -> list[CameraDevice]:
    system = system or platform.system()
    try:
        devices = _enumerate(system)
    except Exception as exc:  # noqa: BLE001
        log.debug("Camera enumeration failed: %s", exc)
        devices = []
    if not include_virtual:
        devices = [d for d in devices if not _is_virtual(d.name)]
    if not devices:
        backend = int(cv2.CAP_DSHOW) if system == "Windows" else 0
        for index in range(3):
            devices.append(CameraDevice(index, f"Camera {index}", backend))
    return devices


def open_attempts(index: int, backend: int, system: str | None = None) -> list[tuple[int, int | None]]:
    """(index, backend) pairs to try for a device, most specific first."""
    system = system or platform.system()
    if backend:
        # The index belongs to this backend. Falling back to another backend
        # with the same number could open a different camera (even the OBS
        # Virtual Camera, which would feed WebSim its own output).
        return [(index, backend)]
    attempts: list[tuple[int, int | None]] = [(index, None)]
    # cv2-enumerate-cameras' CAP_ANY indices are "backend offset + n".
    if index >= 100:
        offset = (index // 100) * 100
        attempts.append((index - offset, offset))
    if system == "Darwin" and index >= 1200:
        attempts.append((index - 1200, int(cv2.CAP_AVFOUNDATION)))
    return attempts


NO_FRAME_TIMEOUT = 6.0  # seconds an opened camera may stay black before we give up


def camera_help() -> str:
    if platform.system() == "Windows":
        return (
            "Close other apps using the camera (Zoom, Teams, browser tabs) and check Settings → "
            "Privacy & security → Camera → 'Let desktop apps access your camera', then Refresh cameras."
        )
    return "Allow Camera access in System Settings → Privacy & Security → Camera, then Refresh cameras."


class WebcamSource:
    """Latest-frame webcam capture in a background thread.

    Opening happens on that thread too: Windows drivers can take seconds to
    open a camera, and doing it on the UI thread freezes the window.
    """

    kind = "webcam"

    def __init__(
        self,
        index: int,
        name: str = "",
        backend: int = 0,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.index = index
        self.device_name = name or f"Camera {index}"
        self.backend = backend
        self._on_error = on_error
        self._capture: Any = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._fitted: np.ndarray | None = None
        self._frame_id = 0
        self._fitted_id = -1
        self._running = True
        self._opening = True
        self.error = ""
        self._thread: threading.Thread | None = threading.Thread(target=self._run, name="websim-webcam", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ open
    def _open_capture(self, use_mjpg: bool) -> Any:
        seen: set[tuple[int, int | None]] = set()
        for index, backend in open_attempts(self.index, self.backend):
            if (index, backend) in seen or index < 0:
                continue
            seen.add((index, backend))
            if not self._running:
                return None
            try:
                candidate = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            except Exception:  # noqa: BLE001
                continue
            if candidate is None:
                continue
            if candidate.isOpened():
                self.backend = backend or 0
                self._configure(candidate, use_mjpg)
                return candidate
            try:
                candidate.release()
            except Exception:  # noqa: BLE001
                pass
        return None

    def _configure(self, capture: Any, use_mjpg: bool) -> None:
        props: list[tuple[int, float]] = []
        if use_mjpg and self.backend == cv2.CAP_DSHOW:
            # DirectShow defaults to uncompressed YUY2, which most USB webcams
            # deliver at only 5-10 fps at 720p. MJPG gives a full 30 fps. It
            # must be set before the frame size.
            props.append((cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")))
        for prop, value in (
            *props,
            (cv2.CAP_PROP_FRAME_WIDTH, 1280),
            (cv2.CAP_PROP_FRAME_HEIGHT, 720),
            (cv2.CAP_PROP_FPS, 30),
            (cv2.CAP_PROP_BUFFERSIZE, 1),
        ):
            try:
                capture.set(prop, value)
            except Exception:  # noqa: BLE001
                pass

    def _set_capture(self, capture: Any) -> bool:
        """Install a capture unless close() already ran; False means it was released."""
        with self._lock:
            if self._running:
                self._capture = capture
                return True
        _release(capture)
        return False

    def _fail(self, message: str) -> None:
        self.error = message
        self._opening = False
        log.warning("%s", message)
        if self._on_error is not None and self._running:
            try:
                self._on_error(message)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        use_mjpg = True
        capture = self._open_capture(use_mjpg)
        if capture is None:
            if self._running:
                self._fail(f"Could not open {self.device_name}. {camera_help()}")
            return
        if not self._set_capture(capture):
            return
        self._opening = False
        self._loop(use_mjpg)
        with self._lock:
            capture, self._capture = self._capture, None
        _release(capture)

    def _loop(self, use_mjpg: bool) -> None:
        failures = 0
        started = time.monotonic()
        got_frame = False
        while self._running:
            capture = self._capture
            try:
                ok, frame = capture.read()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                log.debug("Webcam read failed: %s", exc)
                ok, frame = False, None
            if not ok or frame is None:
                failures += 1
                if failures % 60 == 1:
                    log.debug("Webcam frame missing (%s)", self.device_name)
                if not got_frame and time.monotonic() - started > NO_FRAME_TIMEOUT:
                    if use_mjpg and self.backend == cv2.CAP_DSHOW:
                        # Some cameras open with MJPG requested but never deliver.
                        log.info("No frames from %s with MJPG; reopening without it", self.device_name)
                        use_mjpg = False
                        with self._lock:
                            old, self._capture = self._capture, None
                        _release(old)
                        fresh = self._open_capture(use_mjpg)
                        if fresh is None or not self._set_capture(fresh):
                            if self._running:
                                self._fail(f"Could not reopen {self.device_name}. {camera_help()}")
                            return
                        started = time.monotonic()
                        continue
                    self._fail(f"No picture from {self.device_name}. {camera_help()}")
                    return
                time.sleep(0.02)
                continue
            failures = 0
            got_frame = True
            with self._lock:
                self._frame = frame
                self._frame_id += 1

    @property
    def cap(self):
        return self._capture

    @property
    def opening(self) -> bool:
        return self._opening and self.error == ""

    @property
    def available(self) -> bool:
        """True while opening or capturing; False once the camera has failed."""
        return self._running and self.error == ""

    def raw(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    def frame(self) -> np.ndarray | None:
        with self._lock:
            if self._frame is None:
                return None
            if self._fitted_id == self._frame_id and self._fitted is not None:
                return self._fitted
            self._fitted = fit_cover(self._frame, FRAME_SIZE)
            self._fitted_id = self._frame_id
            return self._fitted

    def frame_pair(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Fitted frame and the raw frame it came from, atomically."""
        with self._lock:
            if self._frame is None:
                return None, None
            raw = self._frame
            if self._fitted_id == self._frame_id and self._fitted is not None:
                return self._fitted, raw
            self._fitted = fit_cover(raw, FRAME_SIZE)
            self._fitted_id = self._frame_id
            return self._fitted, raw

    def close(self) -> None:
        with self._lock:
            self._running = False
        # The capture thread owns the capture and releases it on the way out;
        # releasing it here while it is inside read() can crash OpenCV.
        alive = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            alive = self._thread.is_alive()
            self._thread = None
        if not alive:
            with self._lock:
                capture, self._capture = self._capture, None
            _release(capture)

    @property
    def title(self) -> str:
        return self.device_name

    @property
    def has_transport(self) -> bool:
        return False


def _release(capture: Any) -> None:
    if capture is None:
        return
    try:
        capture.release()
    except Exception:  # noqa: BLE001
        pass
