"""Animated test card: proves the virtual camera path end to end."""

from __future__ import annotations

import math
import time
from datetime import datetime

import cv2
import numpy as np

from ..imaging import FRAME_H, FRAME_W
from .base import BaseSource

BARS = [
    (235, 235, 235),
    (60, 220, 235),
    (60, 235, 120),
    (235, 120, 60),
    (235, 60, 200),
    (60, 60, 235),
]


class TestPatternSource(BaseSource):
    kind = "test"

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._last = 0.0
        self._frame: np.ndarray | None = None

    def frame(self) -> np.ndarray:
        now = time.monotonic()
        if self._frame is not None and now - self._last < 1 / 30:
            return self._frame
        self._last = now
        elapsed = now - self._started
        frame = np.full((FRAME_H, FRAME_W, 3), 18, dtype=np.uint8)

        # colour bars
        bar_w = FRAME_W // len(BARS)
        for i, colour in enumerate(BARS):
            x0 = i * bar_w
            cv2.rectangle(frame, (x0, 60), (x0 + bar_w - 1, 330), colour, -1)

        # moving sweep, so a frozen feed is obvious
        x = int((elapsed * 160) % (FRAME_W + 200)) - 100
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, 60), (x + 70, 330), (255, 255, 255), -1)
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

        # header
        cv2.rectangle(frame, (0, 0), (FRAME_W, 60), (10, 10, 14), -1)
        cv2.putText(frame, "WEBSIM  -  CAMERA TEST", (28, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 250), 2, cv2.LINE_AA)
        cv2.circle(frame, (FRAME_W - 40, 30), 10, (80, 220, 120), -1)

        # clock face with a rotating hand
        centre = (260, 520)
        cv2.circle(frame, centre, 96, (28, 26, 38), -1)
        cv2.circle(frame, centre, 96, (225, 225, 240), 2)
        for tick in range(12):
            angle = tick / 12 * 2 * math.pi
            cv2.circle(frame, (int(centre[0] + 84 * math.cos(angle)), int(centre[1] + 84 * math.sin(angle))), 3, (220, 220, 235), -1)
        angle = elapsed * 1.2
        cv2.line(
            frame,
            centre,
            (int(centre[0] + 74 * math.cos(angle)), int(centre[1] + 74 * math.sin(angle))),
            (90, 225, 135),
            5,
            cv2.LINE_AA,
        )

        # elapsed + wall clock
        cv2.putText(frame, f"{elapsed:7.1f}s", (480, 520), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (240, 240, 250), 3, cv2.LINE_AA)
        cv2.putText(
            frame,
            datetime.now().strftime("%H:%M:%S"),
            (484, 580),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (185, 185, 210),
            2,
            cv2.LINE_AA,
        )

        # footer
        cv2.rectangle(frame, (0, FRAME_H - 40), (FRAME_W, FRAME_H), (10, 10, 14), -1)
        note = "If you can read this in Zoom or a browser camera test, the virtual camera works."
        cv2.putText(frame, note, (24, FRAME_H - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 200), 1, cv2.LINE_AA)
        self._frame = frame
        return frame

    @property
    def title(self) -> str:
        return "Test pattern"

    @property
    def has_transport(self) -> bool:
        return False
