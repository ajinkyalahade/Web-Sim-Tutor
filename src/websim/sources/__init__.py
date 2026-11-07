"""Open any supported lesson file as a source."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import BaseSource
from .image import ImageSource
from .pdf import PdfSource
from .video import VideoSource

log = logging.getLogger(__name__)

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".ogv",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
PDF_EXTS = {".pdf"}

FILTER = (
    "Lessons (*.mp4 *.m4v *.mov *.mkv *.avi *.webm *.wmv *.flv *.mpg *.mpeg *.ts *.3gp *.ogv "
    "*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;Video (*.mp4 *.mov *.mkv *.avi *.webm *.wmv *.flv);;"
    "PDF (*.pdf);;Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"
)


def open_source(path: str | Path, audio_engine=None) -> BaseSource:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    ext = p.suffix.lower()
    if ext in PDF_EXTS:
        return PdfSource(p)
    if ext in IMAGE_EXTS:
        return ImageSource(p)
    if ext in VIDEO_EXTS:
        return VideoSource(p, audio_engine=audio_engine)
    # last resort: let ffmpeg decide (it knows more containers than we list)
    return VideoSource(p, audio_engine=audio_engine)
