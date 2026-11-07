"""The system-wide virtual camera (OBS virtual camera via pyvirtualcam)."""

from __future__ import annotations

import logging
import platform

import numpy as np

log = logging.getLogger(__name__)


class VirtualCameraSink:
    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self._camera = None
        self.active = False
        self.status = "Not started"
        self.error = ""
        self._frame_count = 0

    def open(self) -> bool:
        if self.active:
            return True
        try:
            import pyvirtualcam

            fmt = pyvirtualcam.PixelFormat.RGB
            # Ask for OBS explicitly. Otherwise, on Windows, pyvirtualcam also tries
            # Unity Capture and appends its "not found" error, which hides the
            # real OBS error.
            self._camera = pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                fmt=fmt,
                backend="obs",
                print_fps=False,
            )
            self.active = True
            self.status = f"Live — {self._camera.device}"
            self.error = ""
            self._frame_count = 0
            log.info("Virtual camera opened: %s", self._camera.device)
            return True
        except Exception as exc:  # noqa: BLE001
            self._camera = None
            self.active = False
            self.status = "Virtual camera not available"
            self.error = _friendly_error(exc)
            log.warning("Virtual camera unavailable: %s", exc)
            return False

    def send(self, frame: np.ndarray) -> bool:
        if not self.active or self._camera is None:
            return False
        try:
            # pyvirtualcam wants RGB, packed and contiguous
            rgb = frame[:, :, ::-1] if frame.flags["C_CONTIGUOUS"] else frame[:, :, ::-1].copy()
            self._camera.send(np.ascontiguousarray(rgb))
            self._camera.sleep_until_next_frame()
            self._frame_count += 1
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Virtual camera write failed: %s", exc)
            self.close()
            self.error = f"Virtual camera stopped: {exc}"
            self.status = "Disconnected"
            return False

    def close(self) -> None:
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:  # noqa: BLE001
                pass
        self._camera = None
        self.active = False
        if self.status.startswith("Live"):
            self.status = "Stopped"


def _friendly_error(exc: Exception, system: str | None = None) -> str:
    text = str(exc)
    system = system or platform.system()
    lowered = text.lower()
    if system == "Windows":
        # pyvirtualcam (native_windows_obs/virtual_output.h) raises exactly two errors:
        if "could not be started" in lowered:
            # The shared frame queue already exists: someone else is feeding the camera.
            return (
                "The OBS Virtual Camera is already in use. Close OBS (or click 'Stop Virtual Camera' "
                "in OBS), close any other WebSim window, check Task Manager for a leftover "
                "python.exe / websim.exe, then click Retry virtual camera."
            )
        if "device not found" in lowered or "did you install obs" in lowered:
            # The DirectShow filter is not registered in HKEY_CLASSES_ROOT.
            return (
                "OBS is installed but its virtual camera driver is not registered. Open OBS, click "
                "'Start Virtual Camera' (approve the admin prompt), then 'Stop Virtual Camera', quit "
                "OBS and click Retry virtual camera. A portable/zip copy of OBS cannot register it: "
                "use the normal OBS installer."
            )
    if "obs" in lowered or "virtual camera" in lowered or "not found" in lowered:
        if system == "Darwin":
            return (
                "OBS Virtual Camera not found. Install OBS Studio 30+, open it once, click "
                "'Start Virtual Camera' then 'Stop', and quit OBS. WebSim will then appear as "
                "'OBS Virtual Camera'."
            )
        return f"OBS Virtual Camera not available: {text}"
    if "permission" in lowered and system == "Darwin":
        return "macOS blocked camera access. Allow it in System Settings → Privacy & Security → Camera."
    return f"Virtual camera error: {text}"


def probe_virtual_camera() -> tuple[bool, str]:
    """Open and close a camera quickly, for the diagnostics command."""
    sink = VirtualCameraSink()
    ok = sink.open()
    message = sink.status if ok else (sink.error or sink.status)
    sink.close()
    return ok, message
