from __future__ import annotations

import time

import numpy as np

from websim.sources import open_source
from websim.sources.image import ImageSource
from websim.sources.pdf import PdfSource
from websim.sources.video import VideoSource


def test_video_source_play_pause_seek(sample_video):
    source = VideoSource(sample_video)
    try:
        assert source.title == sample_video.name
        assert 2.5 < source.duration < 3.5
        first = None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and first is None:
            first = source.frame()
            if first is None:
                time.sleep(0.02)
        assert first is not None
        assert first.shape == (720, 1280, 3)
        source.play()
        time.sleep(0.4)
        assert source.position > 0.2
        assert source.playing
        source.pause()
        paused = source.position
        time.sleep(0.15)
        assert abs(source.position - paused) < 0.05
        source.seek(2.0)
        assert abs(source.position - 2.0) < 0.05
        time.sleep(0.2)
        assert source.frame() is not None
    finally:
        source.close()


def test_pdf_pages(sample_pdf):
    pdf = PdfSource(sample_pdf)
    try:
        assert pdf.page_count == 2
        assert pdf.kind == "pdf"
        assert pdf.frame().shape == (720, 1280, 3)
        assert pdf.page_index == 0
        pdf.next_page()
        assert pdf.page_index == 1
        pdf.next_page()
        assert pdf.page_index == 1  # clamped
        pdf.previous_page()
        assert pdf.page_index == 0
        pdf.previous_page()
        assert pdf.page_index == 0
        assert pdf.frame() is not None
    finally:
        pdf.close()


def test_image_source(sample_image):
    image = ImageSource(sample_image)
    try:
        frame = image.frame()
        assert frame.shape == (720, 1280, 3)
        assert frame.dtype == np.uint8
    finally:
        image.close()


def test_open_source_dispatch(sample_video, sample_pdf, sample_image):
    for path, kind in ((sample_video, "video"), (sample_pdf, "pdf"), (sample_image, "image")):
        source = open_source(path)
        try:
            assert source.kind == kind
            frame = source.frame()
            if frame is None and kind == "video":
                deadline = time.monotonic() + 3
                while frame is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                    frame = source.frame()
            assert frame is not None
        finally:
            source.close()
