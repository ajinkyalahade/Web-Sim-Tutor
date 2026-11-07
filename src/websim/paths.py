"""Filesystem locations used by WebSim.

Everything the app writes lives in ``<project>/.websim`` so the folder stays
self-contained (no system-wide config, no stray files in $HOME).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def home() -> Path:
    """Runtime folder, overridable for tests via WEBSIM_HOME."""
    override = os.environ.get("WEBSIM_HOME")
    path = Path(override) if override else PROJECT_ROOT / ".websim"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return home() / "settings.json"


def log_file() -> Path:
    logs = home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "websim.log"
