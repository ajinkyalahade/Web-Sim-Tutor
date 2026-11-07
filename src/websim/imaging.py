"""Frame helpers: resizing, letterboxing and colour conversion."""

from __future__ import annotations

import cv2
import numpy as np

FRAME_W = 1280
FRAME_H = 720
FRAME_SIZE = (FRAME_W, FRAME_H)
FPS = 30


def ensure_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame


def fit_contain(frame: np.ndarray, size: tuple[int, int] = FRAME_SIZE, bg: tuple[int, int, int] = (13, 12, 18)) -> np.ndarray:
    """Scale to fit inside the frame, padding with ``bg`` (no cropping)."""
    w, h = size
    src_h, src_w = frame.shape[:2]
    if src_w <= 0 or src_h <= 0:
        return blank(size, bg)
    scale = min(w / src_w, h / src_h)
    new_w, new_h = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (new_w, new_h), interpolation=interp)
    out = blank(size, bg)
    x0 = (w - new_w) // 2
    y0 = (h - new_h) // 2
    out[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return out


def fit_cover(frame: np.ndarray, size: tuple[int, int] = FRAME_SIZE) -> np.ndarray:
    """Scale and centre-crop so the frame is completely filled."""
    w, h = size
    src_h, src_w = frame.shape[:2]
    if src_w <= 0 or src_h <= 0:
        return blank(size)
    scale = max(w / src_w, h / src_h)
    new_w, new_h = max(w, int(round(src_w * scale))), max(h, int(round(src_h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (new_w, new_h), interpolation=interp)
    x0 = (new_w - w) // 2
    y0 = (new_h - h) // 2
    return resized[y0 : y0 + h, x0 : x0 + w].copy()


def blank(size: tuple[int, int] = FRAME_SIZE, colour: tuple[int, int, int] = (13, 12, 18)) -> np.ndarray:
    frame = np.empty((size[1], size[0], 3), dtype=np.uint8)
    frame[:] = colour
    return frame


def placeholder(message: str, sub: str = "", size: tuple[int, int] = FRAME_SIZE) -> np.ndarray:
    """A calm holding frame shown before any camera/media exists."""
    frame = blank(size, (22, 20, 30))
    h, w = frame.shape[:2]
    # subtle vignette so it does not look like a bug
    yy, xx = np.mgrid[0:h, 0:w]
    glow = np.exp(-(((xx - w / 2) / (w * 0.45)) ** 2 + ((yy - h / 2) / (h * 0.5)) ** 2) * 2.2)
    frame = np.clip(frame.astype(np.float32) + glow[..., None] * 18, 0, 255).astype(np.uint8)
    draw_centred(frame, message, 0.0, 1.15, (238, 236, 246), bold=True)
    if sub:
        draw_centred(frame, sub, 70.0, 0.62, (150, 146, 170))
    cv2.rectangle(frame, (0, h - 3), (w, h), (124, 92, 246), -1)
    return frame


def draw_centred(
    frame: np.ndarray,
    text: str,
    dy: float = 0.0,
    scale: float = 1.0,
    colour: tuple[int, int, int] = (255, 255, 255),
    bold: bool = False,
) -> None:
    h, w = frame.shape[:2]
    thickness = 2 if bold else 1
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    cv2.putText(
        frame,
        text,
        (int((w - tw) / 2), int(h / 2 + th / 2 + dy)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        colour,
        thickness,
        cv2.LINE_AA,
    )


def to_rgb(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def feather_mask(mask: np.ndarray, size: tuple[int, int] = FRAME_SIZE, sigma: float = 7.0) -> np.ndarray:
    """Resize a 0..1 mask to the frame and soften its edge."""
    w, h = size
    if mask.dtype != np.float32:
        mask = mask.astype(np.float32)
    if mask.max() > 1.0:
        mask = mask / 255.0
    if mask.shape[1] != w or mask.shape[0] != h:
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
    if sigma > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    return np.clip(mask, 0.0, 1.0)
