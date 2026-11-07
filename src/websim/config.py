"""Persisted user settings (JSON in the project's runtime folder)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .paths import settings_file

log = logging.getLogger(__name__)

OVERLAY_STYLES = ("off", "cutout", "ghost", "corner")
BLUR_TYPES = ("gaussian", "pixelate", "box", "motion", "frosted", "blackout")


@dataclass
class Settings:
    # devices
    camera_index: int | None = None
    camera_name: str = ""
    mic_name: str = ""
    output_name: str = ""  # virtual cable / BlackHole
    monitor_name: str = ""  # headphones
    monitor_enabled: bool = False

    # audio levels (0-100)
    source_volume: int = 80
    mic_volume: int = 100
    source_muted: bool = False
    mic_muted: bool = False

    # pointing / effects
    overlay_style: str = "off"
    webcam_bg_blur: bool = False
    blur_enabled: bool = False
    blur_type: str = "gaussian"
    blur_strength: int = 45
    blur_area: str = "whole"  # "whole" | "box"
    blur_box: list[float] | None = None  # normalized x, y, w, h

    # playback
    speed: float = 1.0
    loop: bool = False

    # window / files
    window_width: int = 1280
    window_height: int = 780
    always_on_top: bool = False
    global_shortcuts: bool = True
    last_media_dir: str = ""
    recent_files: list[str] = field(default_factory=list)


def _load_raw(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read settings (%s); using defaults", exc)
        return {}
    return data if isinstance(data, dict) else {}


class SettingsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else settings_file()
        self.settings = Settings()
        self.load()

    def load(self) -> Settings:
        raw = _load_raw(self.path)
        defaults = Settings()
        cleaned: dict[str, Any] = {}
        for f in fields(Settings):
            if f.name not in raw:
                continue
            value = raw[f.name]
            default = getattr(defaults, f.name)
            if f.name in ("blur_box", "recent_files"):
                if isinstance(value, list):
                    cleaned[f.name] = value
                continue
            if isinstance(default, bool):
                if isinstance(value, bool):
                    cleaned[f.name] = value
            elif isinstance(default, int):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    cleaned[f.name] = int(value)
            elif isinstance(default, float):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    cleaned[f.name] = float(value)
            elif isinstance(default, str):
                if isinstance(value, str):
                    cleaned[f.name] = value
            elif default is None:
                if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                    cleaned[f.name] = value
            elif isinstance(default, list):
                if isinstance(value, list):
                    cleaned[f.name] = value
        self.settings = Settings(**cleaned)
        self._sanitise()
        return self.settings

    def _sanitise(self) -> None:
        s = self.settings
        if s.overlay_style not in OVERLAY_STYLES:
            s.overlay_style = "off"
        if s.blur_type not in BLUR_TYPES:
            s.blur_type = "gaussian"
        if s.blur_area not in ("whole", "box"):
            s.blur_area = "whole"
        s.blur_strength = max(0, min(100, s.blur_strength))
        s.source_volume = max(0, min(100, s.source_volume))
        s.mic_volume = max(0, min(100, s.mic_volume))
        s.speed = max(0.25, min(3.0, s.speed))
        s.window_width = max(900, s.window_width)
        s.window_height = max(600, s.window_height)
        if s.blur_box is not None:
            try:
                x, y, w, h = (float(v) for v in s.blur_box)
            except (TypeError, ValueError):
                s.blur_box = None
            else:
                if not (0 <= x < 1 and 0 <= y < 1 and w > 0.01 and h > 0.01):
                    s.blur_box = None
                else:
                    s.blur_box = [x, y, w, h]
        s.recent_files = [p for p in s.recent_files if isinstance(p, str)][:10]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self.settings), indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Could not save settings: %s", exc)

    def remember_file(self, path: str) -> None:
        recent = [p for p in self.settings.recent_files if p != path]
        recent.insert(0, path)
        self.settings.recent_files = recent[:10]
        self.settings.last_media_dir = str(Path(path).resolve().parent)
