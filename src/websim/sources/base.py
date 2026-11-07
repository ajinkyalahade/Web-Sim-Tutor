"""Media source interfaces shared by video, PDF and image inputs."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..imaging import FRAME_SIZE


class BaseSource:
    """A thing that can produce a 1280x720 BGR frame on demand."""

    kind = "media"

    def frame(self) -> np.ndarray | None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    @property
    def title(self) -> str:  # pragma: no cover - interface
        return ""

    @property
    def has_transport(self) -> bool:
        """True when play/pause/seek controls make sense."""
        return False

    @property
    def duration(self) -> float:
        return 0.0

    @property
    def position(self) -> float:
        return 0.0

    @property
    def playing(self) -> bool:
        return False

    @property
    def size(self) -> tuple[int, int]:
        return FRAME_SIZE


def display_name(path: str | Path) -> str:
    return Path(path).name
