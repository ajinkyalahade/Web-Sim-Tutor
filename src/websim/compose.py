"""Compositing the presenter over the shared screen."""

from __future__ import annotations

import cv2
import numpy as np

from .imaging import FRAME_H, FRAME_W, feather_mask


def _blend(base: np.ndarray, layer: np.ndarray, mask: np.ndarray) -> np.ndarray:
    alpha = mask[..., None]
    out = layer.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


def cutout(
    base: np.ndarray,
    person: np.ndarray,
    mask: np.ndarray,
    *,
    feather: float = 7.0,
    shadow: float = 0.38,
) -> np.ndarray:
    """The weather-presenter look: background removed, you stand on the frame."""
    if base.shape[:2] != person.shape[:2]:
        person = cv2.resize(person, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
    alpha = feather_mask(mask, (base.shape[1], base.shape[0]), feather)
    shaded = base
    if shadow > 0:
        halo = cv2.GaussianBlur(alpha, (0, 0), 22)
        shaded = np.clip(
            base.astype(np.float32) * (1.0 - halo[..., None] * shadow), 0, 255
        ).astype(np.uint8)
    return _blend(shaded, person, alpha)


def ghost(
    base: np.ndarray,
    person: np.ndarray,
    mask: np.ndarray,
    *,
    opacity: float = 0.72,
    feather: float = 5.0,
) -> np.ndarray:
    """See-through webcam fallback for slower machines (no hard cut-out)."""
    if base.shape[:2] != person.shape[:2]:
        person = cv2.resize(person, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
    alpha = feather_mask(mask, (base.shape[1], base.shape[0]), feather) * max(0.0, min(1.0, opacity))
    return _blend(base, person, alpha)


def rounded_mask(width: int, height: int, radius: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    radius = max(0, min(radius, min(width, height) // 2))
    cv2.rectangle(mask, (radius, 0), (width - radius - 1, height - 1), 255, -1)
    cv2.rectangle(mask, (0, radius), (width - 1, height - radius - 1), 255, -1)
    for cx, cy in (
        (radius, radius),
        (width - radius - 1, radius),
        (radius, height - radius - 1),
        (width - radius - 1, height - radius - 1),
    ):
        cv2.circle(mask, (cx, cy), radius, 255, -1)
    return mask


def corner(
    base: np.ndarray,
    person: np.ndarray,
    *,
    width_fraction: float = 0.32,
    margin: int = 26,
    radius: int = 18,
    shadow: float = 0.5,
) -> np.ndarray:
    """Picture-in-picture presenter in the bottom-right, for slow machines."""
    bh, bw = base.shape[:2]
    ph, pw = person.shape[:2]
    target_w = max(80, int(bw * width_fraction))
    target_h = max(60, int(round(target_w * ph / pw)))
    max_h = int(bh * 0.55)
    if target_h > max_h:
        target_h = max_h
        target_w = max(80, int(round(target_h * pw / ph)))
    p = cv2.resize(person, (target_w, target_h), interpolation=cv2.INTER_AREA)

    x0 = bw - target_w - margin
    y0 = bh - target_h - margin
    alpha = rounded_mask(target_w, target_h, radius).astype(np.float32) / 255.0

    # drop shadow
    pad = 18
    shadow_layer = np.zeros((bh, bw), dtype=np.float32)
    shadow_layer[y0 : y0 + target_h, x0 : x0 + target_w] = alpha
    shadow_layer = cv2.GaussianBlur(shadow_layer, (0, 0), pad)
    out = np.clip(base.astype(np.float32) * (1.0 - shadow_layer[..., None] * shadow), 0, 255).astype(np.uint8)

    roi = out[y0 : y0 + target_h, x0 : x0 + target_w].astype(np.float32)
    roi = p.astype(np.float32) * alpha[..., None] + roi * (1.0 - alpha[..., None])
    out[y0 : y0 + target_h, x0 : x0 + target_w] = np.clip(roi, 0, 255).astype(np.uint8)

    # a thin light rim keeps it readable over light slides
    cv2.rectangle(out, (x0 - 1, y0 - 1), (x0 + target_w, y0 + target_h), (235, 232, 248), 1, cv2.LINE_AA)
    return out


def background_blur(
    person: np.ndarray,
    mask: np.ndarray,
    *,
    feather: float = 9.0,
    strength: int = 60,
) -> np.ndarray:
    """Webcam mode: keep the tutor sharp, soften everything behind them."""
    h, w = person.shape[:2]
    k = 1 + 2 * int(round(4 + strength / 100 * 26))
    blurred = cv2.GaussianBlur(person, (k, k), 0)
    alpha = feather_mask(mask, (w, h), feather)
    return _blend(blurred, person, alpha)


def overlay_person(
    base: np.ndarray,
    person: np.ndarray,
    mask: np.ndarray | None,
    style: str,
) -> np.ndarray:
    """Dispatch used by the output loop; falls back to corner without a mask."""
    if person is None or style == "off":
        return base
    h, w = base.shape[:2]
    if style == "corner" or mask is None:
        return corner(base, person)
    if style == "ghost":
        return ghost(base, person, mask)
    return cutout(base, person, mask)


def frame_size_ok(base: np.ndarray) -> bool:
    return base.shape[0] == FRAME_H and base.shape[1] == FRAME_W
