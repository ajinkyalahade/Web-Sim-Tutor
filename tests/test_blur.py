from __future__ import annotations

import numpy as np

from websim.blur import BLUR_KINDS, apply_blur, blur_frame
from websim.imaging import feather_mask, fit_contain, fit_cover, placeholder


def test_fit_contain_and_cover_shapes():
    frame = np.zeros((100, 400, 3), dtype=np.uint8)
    contain = fit_contain(frame)
    cover = fit_cover(frame)
    assert contain.shape == (720, 1280, 3)
    assert cover.shape == (720, 1280, 3)


def test_feather_mask_resizes_and_softens():
    mask = np.ones((256, 256), dtype=np.float32)
    out = feather_mask(mask)
    assert out.shape == (720, 1280)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_all_blur_types_preserve_shape():
    frame = placeholder("test")
    for kind in BLUR_KINDS:
        out = blur_frame(frame, kind, 55)
        assert out.shape == frame.shape
        assert out.dtype == np.uint8


def test_box_blur_only_changes_the_box():
    rng = np.random.default_rng(3)
    frame = (rng.random((300, 400, 3)) * 255).astype(np.uint8)
    box = [0.25, 0.25, 0.5, 0.5]
    out = apply_blur(frame, "gaussian", 60, box)
    assert out.shape == frame.shape
    # far outside the box the pixels are untouched
    assert np.array_equal(out[5:40, 5:40], frame[5:40, 5:40])
    # inside the box they are not
    assert not np.array_equal(out[150:220, 200:300], frame[150:220, 200:300])


def test_blackout_box_is_black_inside():
    frame = np.full((300, 400, 3), 180, dtype=np.uint8)
    out = apply_blur(frame, "blackout", 100, [0.2, 0.2, 0.3, 0.3])
    assert out[80:120, 120:170].max() == 0
    assert out[5:20, 5:20].min() == 180


def test_pixelate_makes_blocks():
    rng = np.random.default_rng(9)
    frame = (rng.random((240, 320, 3)) * 255).astype(np.uint8)
    before = len(np.unique(frame.reshape(-1, 3), axis=0))
    out = blur_frame(frame, "pixelate", 80)
    assert out.shape == frame.shape
    after = len(np.unique(out.reshape(-1, 3), axis=0))
    assert after < before
    # pixels inside one mosaic block are identical
    assert np.array_equal(out[100, 100], out[100, 104])
