"""Video playback with a decoding thread and a wall-clock presentation clock.

The decoder keeps a few frames ahead of the clock; the output loop asks for the
frame that should be on screen *now*. This makes seeking, speed changes and
looping responsive without blocking the UI.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from ..imaging import FRAME_SIZE, fit_contain
from .base import BaseSource, display_name

log = logging.getLogger(__name__)

QUEUE_FRAMES = 6
SEEK_PREROLL = 0.10
# Video is presented slightly behind the clock so it lines up with the audio
# buffered in the virtual cable (see VIDEO_LOOKAHEAD in audio.py).
AV_PRESENT_DELAY = 0.10


@dataclass(frozen=True)
class PlaybackState:
    position: float
    playing: bool
    speed: float
    generation: int
    duration: float


class VideoSource(BaseSource):
    kind = "video"

    def __init__(self, path: str | Path, audio_engine=None) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._running = True

        self._container = av.open(self.path)
        if not self._container.streams.video:
            raise ValueError("This file has no video track")
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        self._time_base = float(self._stream.time_base)

        self._duration = self._read_duration()
        self._fps = self._read_fps()
        self._playing = False
        self._position = 0.0
        self._anchor_pos = 0.0
        self._anchor_wall = 0.0
        self._speed = 1.0
        self._loop = False
        self._generation = 0
        self._seek_target = 0.0
        self._eof = False

        self._queue: deque[tuple[float, np.ndarray]] = deque()
        self._last_frame: np.ndarray | None = None
        self._last_pts = -1.0
        self._frames_iter = None

        self._thread = threading.Thread(target=self._decode_loop, name="websim-video", daemon=True)
        self._thread.start()

        self._audio = None
        if audio_engine is not None:
            from ..audio import VideoAudioTrack

            self._audio = VideoAudioTrack(self, audio_engine)

    # ------------------------------------------------------------------ setup
    def _read_duration(self) -> float:
        try:
            if self._stream.duration is not None:
                return max(0.0, float(self._stream.duration * self._stream.time_base))
            if self._container.duration is not None:
                return max(0.0, float(self._container.duration / av.time_base))
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def _read_fps(self) -> float:
        try:
            rate = self._stream.average_rate or self._stream.guessed_rate
            if rate:
                return float(rate)
        except Exception:  # noqa: BLE001
            pass
        return 30.0

    # --------------------------------------------------------------- metadata
    @property
    def title(self) -> str:
        return display_name(self.path)

    @property
    def has_transport(self) -> bool:
        return True

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    @property
    def speed(self) -> float:
        with self._lock:
            return self._speed

    @property
    def loop(self) -> bool:
        with self._lock:
            return self._loop

    @property
    def position(self) -> float:
        return self._current_time()

    def _current_time(self) -> float:
        with self._lock:
            if not self._playing:
                return self._position
            return self._anchor_pos + max(0.0, _now() - self._anchor_wall) * self._speed

    def snapshot(self) -> PlaybackState:
        with self._lock:
            return PlaybackState(
                position=self._current_time(),
                playing=self._playing,
                speed=self._speed,
                generation=self._generation,
                duration=self._duration,
            )

    # ---------------------------------------------------------------- controls
    def play(self) -> None:
        with self._lock:
            at_end = bool(self._duration and self._position >= self._duration - 0.02)
            if at_end:
                self._position = 0.0
            self._anchor_pos = self._position
            self._anchor_wall = time.monotonic()
            self._playing = True
            if at_end:
                self._bump_locked(0.0)

    def pause(self) -> None:
        with self._cv:
            self._position = self._clamp(self._current_time())
            self._playing = False
            self._cv.notify_all()

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, position: float) -> None:
        with self._lock:
            target = self._clamp(position)
            self._position = target
            self._anchor_pos = target
            self._anchor_wall = time.monotonic()
            self._bump_locked(target)

    def seek_by(self, delta: float) -> None:
        self.seek(self._current_time() + delta)

    def stop(self) -> None:
        with self._lock:
            self._playing = False
            self._position = 0.0
            self._anchor_pos = 0.0
            self._bump_locked(0.0)

    def set_speed(self, speed: float) -> None:
        speed = max(0.25, min(3.0, float(speed)))
        with self._lock:
            now_pos = self._current_time()
            self._position = now_pos
            self._anchor_pos = now_pos
            self._anchor_wall = time.monotonic()
            self._speed = speed
            self._bump_locked(now_pos)

    def set_loop(self, loop: bool) -> None:
        with self._lock:
            self._loop = bool(loop)

    def _bump_locked(self, seek_to: float | None = None) -> None:
        self._generation += 1
        if seek_to is not None:
            self._seek_target = seek_to
        self._queue.clear()
        self._eof = False
        self._cv.notify_all()

    def _clamp(self, position: float) -> float:
        if self._duration > 0:
            return max(0.0, min(self._duration - 0.001, position))
        return max(0.0, position)

    # ------------------------------------------------------------------ frames
    def frame(self) -> np.ndarray | None:
        self._advance()
        with self._cv:
            pos = self._current_time()
            if self._playing:
                pos = max(0.0, pos - AV_PRESENT_DELAY)
            chosen: tuple[float, np.ndarray] | None = None
            while self._queue and self._queue[0][0] <= pos + 0.004:
                chosen = self._queue.popleft()
            if chosen is not None:
                self._last_pts, raw = chosen
                self._last_frame = fit_contain(raw, FRAME_SIZE)
                self._cv.notify_all()
            return self._last_frame

    def _advance(self) -> None:
        if not self._playing:
            return
        pos = self._anchor_pos + max(0.0, _now() - self._anchor_wall) * self._speed
        if self._duration > 0 and pos >= self._duration:
            if self._loop:
                self.seek(0.0)
                self.play()
            else:
                with self._lock:
                    self._position = self._duration
                    self._playing = False
                    self._anchor_pos = self._position
                    self._bump_locked(self._position)
        elif self._duration <= 0:
            with self._lock:
                eof = self._eof
            if eof and not self._queue and pos > self._last_pts + 0.25:
                if self._loop:
                    self.seek(0.0)
                    self.play()
                else:
                    with self._lock:
                        self._position = self._last_pts
                        self._playing = False
                        self._bump_locked(self._last_pts)

    # ----------------------------------------------------------------- decoder
    def _decode_loop(self) -> None:
        generation = -1
        pts_step = 1.0 / max(1.0, self._fps)
        while self._running:
            with self._cv:
                if self._generation != generation:
                    generation = self._generation
                    target = self._seek_target
                    try:
                        offset = int(max(0.0, target - SEEK_PREROLL) / self._time_base)
                        self._container.seek(offset, stream=self._stream, backward=True)
                    except Exception as exc:  # noqa: BLE001
                        log.debug("seek failed: %s", exc)
                    self._frames_iter = None
                    self._eof = False
                    self._cv.notify_all()
                if len(self._queue) >= QUEUE_FRAMES:
                    self._cv.wait(0.05)
                    continue
                running = self._running
                eof = self._eof
            if not running:
                break
            if eof:
                with self._cv:
                    self._cv.wait(0.05)
                continue
            if self._frames_iter is None:
                self._frames_iter = self._container.decode(self._stream)
            try:
                frame = next(self._frames_iter, None)
            except (av.error.EOFError, StopIteration):
                frame = None
            except Exception as exc:  # noqa: BLE001
                log.warning("Video decode error: %s", exc)
                with self._cv:
                    self._eof = True
                    self._cv.wait(0.1)
                continue
            if frame is None:
                with self._cv:
                    self._frames_iter = None
                    self._eof = True
                    self._cv.notify_all()
                    self._cv.wait(0.05)
                continue
            try:
                pts = float(frame.pts * self._time_base) if frame.pts is not None else self._last_pts + pts_step
            except Exception:  # noqa: BLE001
                pts = self._last_pts + pts_step
            raw = frame.to_ndarray(format="bgr24")
            with self._cv:
                if len(self._queue) < QUEUE_FRAMES:
                    self._queue.append((pts, raw))
                self._cv.notify_all()

    # ------------------------------------------------------------------ audio
    @property
    def audio(self):
        return self._audio

    # ------------------------------------------------------------------ close
    def close(self) -> None:
        if self._audio is not None:
            self._audio.close()
            self._audio = None
        with self._cv:
            self._running = False
            self._cv.notify_all()
        self._thread.join(timeout=2.0)
        try:
            self._container.close()
        except Exception:  # noqa: BLE001
            pass


def _now() -> float:
    return time.monotonic()
