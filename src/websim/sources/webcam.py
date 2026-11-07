"""Webcam capture and device enumeration."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ..imaging import FRAME_SIZE, fit_cover

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    backend: int = 0


def list_cameras(include_virtual: bool = False) -> list[CameraDevice]:
    devices: list[CameraDevice] = []
    try:
        from cv2_enumerate_cameras import enumerate_cameras

        for info in enumerate_cameras():
            name = str(getattr(info, "name", "") or f"Camera {getattr(info, 'index', 0)}")
            if not include_virtual and "obs virtual camera" in name.lower():
                continue
            devices.append(CameraDevice(int(getattr(info, "index", 0)), name, int(getattr(info, "backend", 0) or 0)))
    except Exception as exc:  # noqa: BLE001
        log.debug("Camera enumeration failed: %s", exc)
        devices = []
    if not devices:
        for index in range(3):
            devices.append(CameraDevice(index, f"Camera {index}"))
    return devices


class WebcamSource:
    """Latest-frame webcam capture in a background thread."""

    kind = "webcam"

    def __init__(self, index: int, name: str = "", backend: int = 0) -> None:
        self.index = index
        self.device_name = name or f"Camera {index}"
        self.backend = backend
        self._capture: Any = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._fitted: np.ndarray | None = None
        self._frame_id = 0
        self._fitted_id = -1
        self._running = False
        self._thread: threading.Thread | None = None
        self.error = ""
        self._open()

    def _open(self) -> None:
        attempts: list[tuple[int, int | None]] = []
        if self.backend:
            attempts.append((self.index, self.backend))
        attempts.append((self.index, None))
        # cv2-enumerate-cameras uses backend-offset device numbers; some OpenCV
        # builds also accept the plain zero-based index.
        if self.index >= 1000:
            import platform

            if platform.system() == "Darwin":
                attempts.append((self.index - 1200, cv2.CAP_AVFOUNDATION))
            elif platform.system() == "Windows":
                attempts.append((self.index % 1000, cv2.CAP_DSHOW))
        seen: set[tuple[int, int | None]] = set()
        capture = None
        for index, backend in attempts:
            if (index, backend) in seen or index < 0:
                continue
            seen.add((index, backend))
            try:
                candidate = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            except Exception:  # noqa: BLE001
                continue
            if candidate is None:
                continue
            if candidate.isOpened():
                capture = candidate
                break
            try:
                candidate.release()
            except Exception:  # noqa: BLE001
                pass
        self._capture = capture
        if capture is None:
            self.error = f"Could not open {self.device_name}"
            log.warning("Could not open webcam %s", self.device_name)
            return
        for prop, value in (
            (cv2.CAP_PROP_FRAME_WIDTH, 1280),
            (cv2.CAP_PROP_FRAME_HEIGHT, 720),
            (cv2.CAP_PROP_FPS, 30),
            (cv2.CAP_PROP_BUFFERSIZE, 1),
        ):
            try:
                capture.set(prop, value)
            except Exception:  # noqa: BLE001
                pass
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="websim-webcam", daemon=True)
        self._thread.start()

    @property
    def cap(self):
        return self._capture

    @property
    def available(self) -> bool:
        return self._capture is not None and self.error == ""

    def _loop(self) -> None:
        failures = 0
        while self._running:
            try:
                ok, frame = self._capture.read()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                log.debug("Webcam read failed: %s", exc)
                ok, frame = False, None
            if not ok or frame is None:
                failures += 1
                if failures % 60 == 1:
                    log.debug("Webcam frame missing (%s)", self.device_name)
                time.sleep(0.02)
                continue
            failures = 0
            with self._lock:
                self._frame = frame
                self._frame_id += 1

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
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:  # noqa: BLE001
                pass
            self._capture = None

    @property
    def title(self) -> str:
        return self.device_name

    @property
    def has_transport(self) -> bool:
        return False
