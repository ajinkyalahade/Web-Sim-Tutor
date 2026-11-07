"""PDF slides: render a page and show it like a still frame."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..imaging import FRAME_H, FRAME_W, blank
from .base import BaseSource, display_name

log = logging.getLogger(__name__)


class PdfSource(BaseSource):
    kind = "pdf"

    def __init__(self, path: str | Path) -> None:
        import pypdfium2 as pdfium

        self.path = str(path)
        self._pdfium = pdfium
        # Pass a Python file object: pdfium's own file opening cannot handle
        # non-ASCII paths on Windows. autoclose closes it with the document.
        handle = open(self.path, "rb")
        try:
            self._doc = pdfium.PdfDocument(handle, autoclose=True)
        except Exception:
            handle.close()
            raise
        self.page_count = len(self._doc)
        if self.page_count <= 0:
            raise ValueError("This PDF has no pages")
        self._page_index = 0
        self._frame: np.ndarray | None = None
        self._render()

    # ------------------------------------------------------------------ pages
    @property
    def page_index(self) -> int:
        return self._page_index

    def goto(self, index: int) -> None:
        index = max(0, min(self.page_count - 1, int(index)))
        if index != self._page_index:
            self._page_index = index
            self._render()

    def next_page(self) -> None:
        self.goto(self._page_index + 1)

    def previous_page(self) -> None:
        self.goto(self._page_index - 1)

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        page = self._doc[self._page_index]
        try:
            width, height = page.get_size()
            if width <= 0 or height <= 0:
                raise ValueError("Invalid PDF page size")
            # supersample for crisp text, then shrink to the output frame
            scale = min((FRAME_W * 0.94) / width, (FRAME_H * 0.92) / height) * 2.0
            bitmap = page.render(scale=scale)
            try:
                arr = bitmap.to_numpy()
                if arr.ndim == 2:
                    arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                elif arr.shape[2] == 4:
                    arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
                arr = np.ascontiguousarray(arr)
            finally:
                bitmap.close()
        finally:
            page.close()

        # fit the rendered page into a white paper card on a dark desk
        paper = min((FRAME_W * 0.94) / arr.shape[1], (FRAME_H * 0.92) / arr.shape[0])
        new_w = max(1, int(round(arr.shape[1] * paper)))
        new_h = max(1, int(round(arr.shape[0] * paper)))
        resized = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)

        frame = blank((FRAME_W, FRAME_H), (26, 25, 33))
        x0 = (FRAME_W - new_w) // 2
        y0 = (FRAME_H - new_h) // 2
        # soft drop shadow
        shadow = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        cv2.rectangle(shadow, (x0 + 10, y0 + 12), (x0 + new_w + 10, y0 + new_h + 12), (12, 12, 16), -1)
        shadow = cv2.GaussianBlur(shadow, (0, 0), 18)
        frame = cv2.addWeighted(frame, 1.0, shadow, 0.65, 0)
        frame[y0 : y0 + new_h, x0 : x0 + new_w] = resized
        cv2.rectangle(frame, (x0 - 1, y0 - 1), (x0 + new_w, y0 + new_h), (200, 200, 210), 1)
        self._frame = frame

    def frame(self) -> np.ndarray | None:
        return self._frame

    @property
    def title(self) -> str:
        return display_name(self.path)

    def close(self) -> None:
        try:
            self._doc.close()
        except Exception:  # noqa: BLE001
            pass
        self._frame = None
