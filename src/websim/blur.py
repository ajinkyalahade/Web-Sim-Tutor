"""Blur filters for hiding answers or softening the background."""

from __future__ import annotations

import cv2
import numpy as np

BLUR_LABELS: list[tuple[str, str]] = [
    ("gaussian", "Gaussian (soft)"),
    ("pixelate", "Pixelate (mosaic)"),
    ("box", "Box (fast)"),
    ("motion", "Motion (streaky)"),
    ("frosted", "Frosted glass"),
    ("blackout", "Blackout"),
]

BLUR_KINDS = tuple(k for k, _ in BLUR_LABELS)


def label_for(kind: str) -> str:
    for key, label in BLUR_LABELS:
        if key == kind:
            return label
    return kind.title()


def _normalised_rect(box: list[float] | tuple[float, ...] | None, w: int, h: int) -> tuple[int, int, int, int] | None:
    if not box or len(box) != 4:
        return None
    x, y, bw, bh = (float(v) for v in box)
    x0 = max(0, min(w - 2, int(round(x * w))))
    y0 = max(0, min(h - 2, int(round(y * h))))
    x1 = max(x0 + 2, min(w, int(round((x + bw) * w))))
    y1 = max(y0 + 2, min(h, int(round((y + bh) * h))))
    return x0, y0, x1, y1


def blur_frame(frame: np.ndarray, kind: str, strength: int) -> np.ndarray:
    """Apply one blur type to a whole frame."""
    strength = max(0, min(100, int(strength)))
    if kind == "blackout":
        return np.zeros_like(frame)
    if kind == "pixelate":
        block = 3 + int(round(strength / 100 * 45))  # 3..48 px
        h, w = frame.shape[:2]
        small_w, small_h = max(1, w // block), max(1, h // block)
        small = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    if kind == "box":
        k = 1 + 2 * int(round(1 + strength / 100 * 22))
        return cv2.blur(frame, (k, k))
    if kind == "motion":
        length = 3 + int(round(strength / 100 * 55))  # 3..58 px streak
        kernel = np.zeros((1, length), dtype=np.float32)
        kernel[0, :] = 1.0 / length
        return cv2.filter2D(frame, -1, kernel, borderType=cv2.BORDER_REFLECT)
    if kind == "frosted":
        sigma = 2.0 + strength / 100 * 16.0
        out = cv2.GaussianBlur(frame, (0, 0), sigma)
        noise = np.random.default_rng(7).normal(0, 7 + strength / 10, out.shape[:2])[..., None]
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        haze = np.full_like(out, 255, dtype=np.uint8)
        return cv2.addWeighted(out, 0.92, haze, 0.08, 0)
    # gaussian (default)
    k = 1 + 2 * int(round(2 + strength / 100 * 30))
    return cv2.GaussianBlur(frame, (k, k), 0)


def apply_blur(
    frame: np.ndarray,
    kind: str,
    strength: int,
    box: list[float] | tuple[float, ...] | None = None,
) -> np.ndarray:
    """Blur the whole frame, or only a normalised rectangle when ``box`` is given."""
    h, w = frame.shape[:2]
    rect = _normalised_rect(box, w, h)
    if rect is None:
        return blur_frame(frame, kind, strength)

    x0, y0, x1, y1 = rect
    roi = frame[y0:y1, x0:x1]
    blurred = blur_frame(roi, kind, strength)
    layer = frame.copy()
    layer[y0:y1, x0:x1] = blurred

    # feathered mask so the box does not look like a hard sticker
    mask = np.zeros((h, w), dtype=np.float32)
    mask[y0:y1, x0:x1] = 1.0
    sigma = max(2.0, min(14.0, min(x1 - x0, y1 - y0) * 0.05))
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)[..., None]
    out = frame.astype(np.float32) * (1 - mask) + layer.astype(np.float32) * mask
    return np.clip(out, 0, 255).astype(np.uint8)
