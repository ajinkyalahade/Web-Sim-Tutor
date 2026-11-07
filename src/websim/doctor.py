"""`websim --doctor`: a plain-language readiness check."""

from __future__ import annotations

import platform
import sys

from . import __version__
from .config import SettingsStore


def _line(label: str, value: str) -> str:
    return f"{label:<26} {value}"


def report() -> str:
    lines: list[str] = []
    lines.append("WebSim diagnostics")
    lines.append("=" * 68)
    lines.append(_line("WebSim", __version__))
    lines.append(_line("OS", f"{platform.system()} {platform.release()} ({platform.machine()})"))
    lines.append(_line("Python", sys.version.split()[0]))
    try:
        from PySide6 import __version__ as pyside_version

        lines.append(_line("PySide6", pyside_version))
    except Exception as exc:  # noqa: BLE001
        lines.append(_line("PySide6", f"MISSING ({exc})"))

    try:
        import av

        lines.append(_line("PyAV / FFmpeg", av.__version__))
    except Exception as exc:  # noqa: BLE001
        lines.append(_line("PyAV / FFmpeg", f"MISSING ({exc})"))

    # ---------------------------------------------------------------- camera
    lines.append("")
    lines.append("Cameras")
    try:
        from .sources.webcam import list_cameras

        cameras = list_cameras(include_virtual=True)
        if not cameras:
            lines.append("  none found (macOS may need Camera permission for Terminal)")
        for camera in cameras:
            note = "  [virtual — hidden by WebSim]" if "obs virtual" in camera.name.lower() else ""
            lines.append(f"  {camera.index:>6}  {camera.name}{note}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  could not enumerate: {exc}")

    # ---------------------------------------------------------------- camera out
    lines.append("")
    lines.append("Virtual camera")
    try:
        from .output import probe_virtual_camera

        ok, message = probe_virtual_camera()
        lines.append(f"  {'OK' if ok else 'FAIL'}  {message}")
        if not ok:
            lines.append("  Fix: install OBS Studio 30+, open it, Start Virtual Camera, Stop, quit OBS.")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  FAIL  {exc}")

    # ----------------------------------------------------------------- audio
    lines.append("")
    lines.append("Audio devices")
    try:
        from .audio import guess_virtual_output, list_audio_devices

        devices = list_audio_devices()
        if not devices:
            lines.append("  no audio devices found (sounddevice/PortAudio missing?)")
        for device in devices:
            direction = []
            if device.inputs:
                direction.append(f"in {device.inputs}")
            if device.outputs:
                direction.append(f"out {device.outputs}")
            tag = "  [virtual cable]" if device.is_virtual_output else ""
            lines.append(f"  {device.index:>3}  {device.name:<40} {', '.join(direction)}{tag}")
        virtual = guess_virtual_output(devices)
        lines.append("")
        if virtual:
            lines.append(f"  Virtual output detected: {virtual}")
        else:
            lines.append("  No virtual cable found. Install BlackHole 2ch (Mac) or VB-Audio Virtual Cable (Windows).")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  could not enumerate: {exc}")

    # ---------------------------------------------------------- background removal
    lines.append("")
    lines.append("Background removal")
    try:
        import mediapipe as mp

        if hasattr(mp, "solutions"):
            segmenter = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
            segmenter.close()
            lines.append(f"  OK  mediapipe {mp.__version__} (bundled selfie model)")
        else:
            lines.append(f"  FAIL  mediapipe {mp.__version__} has no solutions API — use 0.10.x")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  FAIL  {exc}")

    # ---------------------------------------------------------------- settings
    lines.append("")
    try:
        store = SettingsStore()
        from .audio import NO_OUTPUT

        output = store.settings.output_name
        if output == NO_OUTPUT:
            output = "(none)"
        lines.append(f"Settings file: {store.path}")
        lines.append(f"Virtual output setting: {output or '(auto-detect)'}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Settings error: {exc}")

    lines.append("")
    lines.append("Checklist: OBS installed once, virtual audio installed, Camera + Mic")
    lines.append("permissions granted, then File → Camera test pattern in WebSim.")
    return "\n".join(lines)
