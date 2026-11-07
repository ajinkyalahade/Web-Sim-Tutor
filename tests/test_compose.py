from __future__ import annotations

import cv2
import numpy as np

from websim.compose import background_blur, corner, cutout, ghost, overlay_person, rounded_mask


def _scene(size=(720, 1280)):
    h, w = size
    base = np.zeros((h, w, 3), dtype=np.uint8)
    base[:] = (200, 80, 40)  # blue-ish base (BGR)
    person = np.zeros((h, w, 3), dtype=np.uint8)
    person[:] = (30, 40, 230)  # red-ish person
    mask = np.zeros((256, 256), dtype=np.float32)
    cv2.circle(mask, (128, 128), 90, 1.0, -1)
    return base, person, mask


def test_cutout_puts_person_on_top():
    base, person, mask = _scene()
    out = cutout(base, person, mask)
    assert out.shape == base.shape
    # centre is the person
    assert int(out[360, 640, 2]) > 150
    # corner is the base
    assert np.array_equal(out[10, 10], base[10, 10])


def test_ghost_is_translucent():
    base, person, mask = _scene()
    out = ghost(base, person, mask, opacity=0.5)
    centre = out[360, 640]
    assert not np.array_equal(centre, person[360, 640])
    assert not np.array_equal(centre, base[360, 640])
    assert centre[2] > base[360, 640][2]


def test_corner_overlay_sits_bottom_right():
    base, person, mask = _scene()
    out = corner(base, person)
    assert out.shape == base.shape
    assert np.array_equal(out[10, 10], base[10, 10])
    # bottom-right area contains the person
    assert out[650, 1100][2] > 120


def test_overlay_falls_back_to_corner_without_mask():
    base, person, _ = _scene()
    out = overlay_person(base, person, None, "cutout")
    assert out.shape == base.shape
    assert np.array_equal(out[10, 10], base[10, 10])
    assert out[650, 1100][2] > 120


def test_background_blur_keeps_person_sharp():
    base, person, mask = _scene()
    person = person.copy()
    person[300:420, 560:720] = (255, 255, 255)
    out = background_blur(person, mask, strength=80)
    # centre of mask is untouched
    assert np.array_equal(out[360, 640], person[360, 640])
    # outside the mask it is averaged/blurred
    assert out.shape == person.shape


def test_rounded_mask_edges():
    mask = rounded_mask(100, 80, 12)
    assert mask.shape == (80, 100)
    assert mask[40, 50] == 255
    assert mask[0, 0] == 0
