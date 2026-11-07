"""Person segmentation (MediaPipe) in a background thread.

The output loop always reads the newest mask and never waits for it: a slow
machine simply gets a slightly older silhouette, which is invisible on video.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

log = logging.getLogger(__name__)

_SEG_W, _SEG_H = 640, 360


class BackgroundSegmenter(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="websim-segmenter", daemon=True)
        self._cv = threading.Condition()
        self._running = True
        self._active = False
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._mask: np.ndarray | None = None
        self._mask_seq = -1
        self.available = True
        self.error = ""
        self.latency_ms = 0.0
        self._segmenter = None
        self._thread_started = False

    # ------------------------------------------------------------------ public
    def set_active(self, active: bool) -> None:
        with self._cv:
            self._active = bool(active)
            if active:
                self._ensure_started_locked()
            self._cv.notify_all()

    def _ensure_started_locked(self) -> None:
        if not self._thread_started:
            self._thread_started = True
            try:
                self.start()
            except RuntimeError:
                pass

    def submit(self, frame_bgr: np.ndarray) -> None:
        with self._cv:
            if not self._active:
                return
            self._frame = frame_bgr
            self._seq += 1
            self._cv.notify_all()

    def latest(self) -> np.ndarray | None:
        with self._cv:
            return self._mask

    def reset(self) -> None:
        with self._cv:
            self._mask = None
            self._frame = None

    # -------------------------------------------------------------------- loop
    def run(self) -> None:
        try:
            import mediapipe as mp

            if not hasattr(mp, "solutions"):
                raise RuntimeError("installed mediapipe has no solutions API")
            self._segmenter = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
        except Exception as exc:  # noqa: BLE001
            self.available = False
            self.error = f"Background removal unavailable: {exc}"
            log.warning(self.error)
            return

        while self._running:
            with self._cv:
                while self._running and (not self._active or self._frame is None or self._seq == self._mask_seq):
                    self._cv.wait(0.2)
                if not self._running:
                    break
                frame = self._frame
                seq = self._seq
            if frame is None:
                continue
            started = time.monotonic()
            try:
                small = cv2.resize(frame, (_SEG_W, _SEG_H), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                result = self._segmenter.process(rgb)
                mask = result.segmentation_mask
                if mask is not None:
                    mask = np.asarray(mask, dtype=np.float32)
            except Exception as exc:  # noqa: BLE001
                log.debug("Segmentation error: %s", exc)
                time.sleep(0.1)
                continue
            with self._cv:
                if self._active:
                    self._mask = mask
                    self._mask_seq = seq
                self.latency_ms = (time.monotonic() - started) * 1000

        try:
            if self._segmenter is not None:
                self._segmenter.close()
        except Exception:  # noqa: BLE001
            pass
        self._segmenter = None

    def close(self) -> None:
        with self._cv:
            self._running = False
            self._cv.notify_all()
        if self._thread_started and self.is_alive():
            self.join(timeout=2.0)
