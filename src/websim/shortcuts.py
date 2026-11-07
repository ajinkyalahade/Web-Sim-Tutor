"""Global shortcuts that work while Zoom or a browser has focus (pynput)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

GLOBAL_BINDINGS: dict[str, str] = {
    "play_pause": "<ctrl>+<alt>+<space>",
    "stop": "<ctrl>+<alt>+s",
    "back": "<ctrl>+<alt>+<left>",
    "forward": "<ctrl>+<alt>+<right>",
    "slower": "<ctrl>+<alt>+<down>",
    "faster": "<ctrl>+<alt>+<up>",
    "freeze": "<ctrl>+<alt>+f",
    "webcam": "<ctrl>+<alt>+c",
    "media": "<ctrl>+<alt>+v",
    "blur": "<ctrl>+<alt>+b",
    "mute_video": "<ctrl>+<alt>+m",
    "mute_mic": "<ctrl>+<alt>+n",
    "page_prev": "<ctrl>+<alt>+<page_up>",
    "page_next": "<ctrl>+<alt>+<page_down>",
}


class GlobalShortcuts(QObject):
    triggered = Signal(str)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._listener = None
        self.available = False
        self.error = ""

    def start(self) -> bool:
        if self._listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as exc:  # noqa: BLE001
            self.error = f"Global shortcuts unavailable: {exc}"
            log.warning(self.error)
            self.failed.emit(self.error)
            return False
        if not _has_accessibility_permission():
            self.error = (
                "Global shortcuts need Accessibility permission: System Settings → Privacy & Security → "
                "Accessibility → enable your terminal app, then restart WebSim."
            )
            log.info(self.error)
            self.failed.emit(self.error)
            return False
        try:
            mapping = {}
            for action, combo in GLOBAL_BINDINGS.items():
                mapping[combo] = self._make_callback(action)
            listener = keyboard.GlobalHotKeys(mapping)
            listener.daemon = True
            listener.start()
            self._listener = listener
            self.available = True
            self.error = ""
            log.info("Global shortcuts started")
            return True
        except Exception as exc:  # noqa: BLE001
            self._listener = None
            self.available = False
            self.error = f"Global shortcuts could not start: {exc}"
            log.warning(self.error)
            self.failed.emit(self.error)
            return False

    def _make_callback(self, action: str):
        def callback() -> None:
            try:
                self.triggered.emit(action)
            except Exception:  # noqa: BLE001
                pass

        return callback

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None
        self.available = False

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.start()
        else:
            self.stop()


def _has_accessibility_permission() -> bool:
    """On macOS, global key taps require Accessibility access."""
    try:
        import platform

        if platform.system() != "Darwin":
            return True
        import ctypes

        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        fn = lib.AXIsProcessTrusted
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:  # noqa: BLE001
        # If the check itself fails, let pynput try; it fails safely.
        return True
