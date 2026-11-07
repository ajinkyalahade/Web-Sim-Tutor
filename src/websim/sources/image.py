"""Still images (PNG, JPEG, WebP, BMP, TIFF...)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..imaging import FRAME_SIZE, fit_contain
from .base import BaseSource, display_name


class ImageSource(BaseSource):
    kind = "image"

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        data = np.fromfile(self.path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Could not read image: {self.path}")
        if image.ndim == 2:
            image = np.stack([image] * 3, axis=-1)
        if image.shape[2] == 4:
            # composite on white so transparent PNG slides look like slides
            alpha = image[:, :, 3:4].astype(np.float32) / 255.0
            rgb = image[:, :, :3].astype(np.float32)
            white = np.full_like(rgb, 255.0)
            image = np.clip(rgb * alpha + white * (1 - alpha), 0, 255).astype(np.uint8)
        self._frame = fit_contain(image, FRAME_SIZE, (26, 25, 33))

    def frame(self) -> np.ndarray | None:
        return self._frame

    @property
    def title(self) -> str:
        return display_name(self.path)

    def close(self) -> None:
        self._frame = None
