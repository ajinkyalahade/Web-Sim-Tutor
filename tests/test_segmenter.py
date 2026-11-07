from __future__ import annotations

import time

import numpy as np
import pytest

from websim.segmenter import BackgroundSegmenter


def test_segmenter_returns_a_person_mask():
    segmenter = BackgroundSegmenter()
    segmenter.set_active(True)
    frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
    frame[200:600, 400:900] = (30, 40, 200)
    segmenter.submit(frame)
    deadline = time.monotonic() + 20
    mask = None
    try:
        while time.monotonic() < deadline:
            mask = segmenter.latest()
            if mask is not None:
                break
            time.sleep(0.05)
        if not segmenter.available:
            pytest.skip(segmenter.error or "mediapipe unavailable")
        assert mask is not None, "no mask produced"
        assert mask.shape[:2] == (360, 640)
        assert 0.0 <= float(mask.min()) and float(mask.max()) <= 1.0
    finally:
        segmenter.close()
