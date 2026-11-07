"""The studio: owns every input, the effects and the 30 fps output loop."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from .audio import AudioEngine, list_audio_devices
from .blur import apply_blur
from .compose import background_blur, overlay_person
from .config import OVERLAY_STYLES, Settings, SettingsStore
from .imaging import FRAME_H, FRAME_W, placeholder, to_rgb
from .output import VirtualCameraSink
from .segmenter import BackgroundSegmenter
from .sources import open_source
from .sources.base import BaseSource
from .sources.testpattern import TestPatternSource
from .sources.webcam import CameraDevice, WebcamSource, list_cameras

log = logging.getLogger(__name__)

MODES = ("webcam", "media")


class OutputLoop(QThread):
    """Runs the mixer at fps and pushes frames to the virtual camera."""

    def __init__(self, studio: "Studio") -> None:
        super().__init__()
        self.studio = studio
        self._running = True
        self.frames = 0
        self.fps = 0.0

    def stop(self) -> None:
        self._running = False
        self.requestInterruption()
        if self.isRunning():
            self.wait(2500)

    def run(self) -> None:  # noqa: D401
        interval = 1.0 / self.studio.fps
        last_preview = 0.0
        last_stats = 0.0
        frames_since = 0
        while self._running and not self.isInterruptionRequested():
            started = time.monotonic()
            frame = self.studio.compose()
            emitted = False
            attempted = False
            if frame is not None:
                if self.studio.sink.active:
                    attempted = True
                    emitted = self.studio.sink.send(frame)
                now = time.monotonic()
                if now - last_preview >= 1 / 24:
                    self.studio.publish_preview(frame)
                    last_preview = now
                if attempted and not emitted:
                    self.studio.notice.emit(self.studio.sink.error or "Virtual camera disconnected")
                    self.studio.changed.emit()
                if not emitted:
                    self._pace(started, interval)
            else:
                self._pace(started, interval)
            self.frames += 1
            frames_since += 1
            now = time.monotonic()
            if now - last_stats >= 1.0:
                self.fps = frames_since / max(0.001, now - last_stats)
                frames_since = 0
                last_stats = now
                self.studio.publish_stats(self.fps)

    @staticmethod
    def _pace(started: float, interval: float) -> None:
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


class Studio(QObject):
    preview = Signal(QImage)
    changed = Signal()
    position = Signal(float, float)
    status = Signal(str)
    stats = Signal(float)
    mediaChanged = Signal()
    notice = Signal(str)

    fps = 30

    def __init__(
        self,
        store: SettingsStore,
        *,
        preview_only: bool = False,
        enable_audio: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.settings: Settings = store.settings
        self.preview_only = bool(preview_only)
        self.enable_audio = enable_audio
        self.engine = AudioEngine()
        self.sink = VirtualCameraSink(FRAME_W, FRAME_H, self.fps)
        self.segmenter = BackgroundSegmenter()

        self._lock = __import__("threading").RLock()
        self._mode = ""
        self._media: BaseSource | None = None
        self._webcam: WebcamSource | None = None
        self._overlay_style = self.settings.overlay_style
        self._webcam_bg_blur = self.settings.webcam_bg_blur
        self._blur_enabled = self.settings.blur_enabled
        self._blur_type = self.settings.blur_type
        self._blur_strength = self.settings.blur_strength
        self._blur_area = self.settings.blur_area
        self._blur_box = self.settings.blur_box
        self._frozen = False
        self._freeze_style = "cutout"
        self._freeze_was_playing = False
        self._freeze_prev_style = "off"
        self._last_error = ""
        self._last_error_at = 0.0
        self._notice = ""
        self.loop: OutputLoop | None = None
        self._started = False
        self._tone = False
        self._webcam_failed_at = 0.0

    # ------------------------------------------------------------------ startup
    def start(self, *, test_pattern: bool = False) -> None:
        self._started = True
        if not self.preview_only:
            self.sink.open()
        if self.enable_audio:
            self.engine.start(
                mic_name=self.settings.mic_name,
                output_name=self.settings.output_name,
                monitor_name=self.settings.monitor_name,
                monitor=self.settings.monitor_enabled,
            )
            self.engine.set_levels(
                source_volume=self.settings.source_volume / 100,
                mic_volume=self.settings.mic_volume / 100,
                source_muted=self.settings.source_muted,
                mic_muted=self.settings.mic_muted,
            )
        else:
            self.engine.status = "Audio disabled"
        if test_pattern:
            self.open_test_pattern(tone=True)
        else:
            self.set_mode("webcam")
        self.loop = OutputLoop(self)
        self.loop.start()
        self._emit_status()
        self.changed.emit()

    def shutdown(self) -> None:
        self._started = False
        if self.loop is not None:
            self.loop.stop()
            self.loop = None
        self.segmenter.close()
        self._close_media()
        self._close_webcam()
        self.engine.shutdown()
        self.sink.close()
        self.save()

    def save(self) -> None:
        s = self.settings
        s.overlay_style = self._overlay_style
        s.webcam_bg_blur = self._webcam_bg_blur
        s.blur_enabled = self._blur_enabled
        s.blur_type = self._blur_type
        s.blur_strength = self._blur_strength
        s.blur_area = self._blur_area
        s.blur_box = self._blur_box
        self.store.save()

    # -------------------------------------------------------------------- state
    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def media(self) -> BaseSource | None:
        with self._lock:
            return self._media

    @property
    def webcam(self) -> WebcamSource | None:
        with self._lock:
            return self._webcam

    @property
    def overlay_style(self) -> str:
        return self._overlay_style

    @property
    def webcam_bg_blur(self) -> bool:
        return self._webcam_bg_blur

    @property
    def blur_enabled(self) -> bool:
        return self._blur_enabled

    @property
    def blur_type(self) -> str:
        return self._blur_type

    @property
    def blur_strength(self) -> int:
        return self._blur_strength

    @property
    def blur_area(self) -> str:
        return self._blur_area

    @property
    def blur_box(self) -> list[float] | None:
        return self._blur_box

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def tone(self) -> bool:
        return self._tone

    def media_title(self) -> str:
        with self._lock:
            return self._media.title if self._media is not None else ""

    def media_position(self) -> tuple[float, float]:
        with self._lock:
            media = self._media
        if media is None or not media.has_transport:
            return 0.0, 0.0
        return float(media.position), float(media.duration)

    def playing(self) -> bool:
        with self._lock:
            return bool(self._media and self._media.playing)

    def source_kind(self) -> str:
        with self._lock:
            return self._media.kind if self._media is not None else ""

    def page_info(self) -> tuple[int, int]:
        with self._lock:
            media = self._media
        if media is not None and media.kind == "pdf":
            return int(getattr(media, "page_index", 0)), int(getattr(media, "page_count", 0))
        return 0, 0

    def status_text(self) -> str:
        if self.sink.active:
            head = "Virtual camera live"
        elif self.preview_only:
            head = "Preview only"
        else:
            head = "Preview only — virtual camera unavailable"
        bits = [head]
        if self.engine.status:
            bits.append(self.engine.status)
        if self.tone:
            bits.append("test tone on")
        return " • ".join(bits)

    # ------------------------------------------------------------------ sources
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        if mode == self._mode:
            return
        if self._media is not None and self._media.playing:
            self._media.pause()
        if mode == "webcam" and self._tone:
            self._tone = False
            self.engine.set_levels(tone=False)
        if mode == "webcam":
            self._frozen = False
        with self._lock:
            self._mode = mode
        if mode == "webcam":
            self._ensure_webcam()
        self._sync_webcam_lifecycle()
        self._emit_status()
        self.changed.emit()

    def open_file(self, path: str) -> None:
        try:
            source = open_source(path, audio_engine=self.engine)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open %s: %s", path, exc)
            self._emit_notice(f"Could not open this file: {exc}")
            return
        self._close_media()
        with self._lock:
            self._media = source
            self._mode = "media"
            self._frozen = False
            self._freeze_was_playing = False
        self._tone = False
        self.engine.set_levels(tone=False)
        if source.has_transport:
            if source.audio is not None and not source.audio.available:
                self._emit_notice("This video has no audio track")
            source.set_loop(self.settings.loop)
            source.set_speed(self.settings.speed)
            source.play()
        self.store.remember_file(str(Path(path)))
        self.store.save()
        self._sync_webcam_lifecycle()
        self.mediaChanged.emit()
        self.changed.emit()
        self._emit_status()

    def open_test_pattern(self, tone: bool = True) -> None:
        self._close_media()
        with self._lock:
            self._media = TestPatternSource()
            self._mode = "media"
            self._frozen = False
            self._freeze_was_playing = False
        self._tone = tone
        self.engine.set_levels(tone=tone)
        self._sync_webcam_lifecycle()
        self.mediaChanged.emit()
        self.changed.emit()
        self._emit_status()

    def _close_media(self) -> None:
        with self._lock:
            media = self._media
            self._media = None
        if media is not None:
            try:
                media.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.engine.flush_video()
        except Exception:  # noqa: BLE001
            pass

    def close_media(self) -> None:
        self._close_media()
        self._tone = False
        self.engine.set_levels(tone=False)
        with self._lock:
            self._mode = "webcam"
            self._frozen = False
        self._ensure_webcam()
        self.mediaChanged.emit()
        self.changed.emit()

    # ------------------------------------------------------------------- webcam
    def cameras(self) -> list[CameraDevice]:
        return list_cameras()

    def camera_name(self) -> str:
        webcam = self.webcam
        return webcam.device_name if webcam is not None else ""

    def set_camera(self, device: CameraDevice) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.playing:
            media.pause()
        self._close_webcam()
        self.settings.camera_index = device.index
        self.settings.camera_name = device.name
        self._open_webcam(device)
        with self._lock:
            self._mode = "webcam"
        self.store.save()
        self._sync_webcam_lifecycle()
        self.changed.emit()
        self._emit_status()

    def _ensure_webcam(self, force: bool = False) -> None:
        webcam = self.webcam
        if webcam is not None and webcam.error == "":
            return
        if not force and time.monotonic() - self._webcam_failed_at < 8.0:
            return
        devices = self.cameras()
        chosen = None
        for device in devices:
            if device.name == self.settings.camera_name:
                chosen = device
                break
        if chosen is None and devices:
            chosen = devices[0]
        if chosen is None:
            self._emit_notice("No camera found")
            self._webcam_failed_at = time.monotonic()
            return
        self._open_webcam(chosen)

    def _open_webcam(self, device: CameraDevice) -> None:
        self._close_webcam()
        try:
            webcam = WebcamSource(device.index, device.name, device.backend)
        except Exception as exc:  # noqa: BLE001
            log.warning("Camera failed: %s", exc)
            self._emit_notice(f"Camera failed: {exc}")
            self._webcam_failed_at = time.monotonic()
            return
        with self._lock:
            self._webcam = webcam
        if not webcam.available:
            self._webcam_failed_at = time.monotonic()
            self._emit_notice(webcam.error or "Camera unavailable")
        else:
            self._webcam_failed_at = 0.0
        self.segmenter.reset()

    def _close_webcam(self) -> None:
        with self._lock:
            webcam = self._webcam
            self._webcam = None
        if webcam is not None:
            webcam.close()
        self.segmenter.set_active(False)
        self.segmenter.reset()

    def _needs_webcam(self) -> bool:
        with self._lock:
            if self._mode == "webcam":
                return True
            return self._overlay_style in ("cutout", "ghost", "corner")

    def _sync_webcam_lifecycle(self) -> None:
        need_mask = False
        with self._lock:
            if self._mode == "media":
                need_mask = self._overlay_style in ("cutout", "ghost")
            elif self._mode == "webcam":
                need_mask = self._webcam_bg_blur
        if self._needs_webcam():
            self._ensure_webcam()
        webcam = self.webcam
        have_camera = webcam is not None and webcam.error == ""
        self.segmenter.set_active(need_mask and have_camera)
        if not self._needs_webcam() and not need_mask:
            self._close_webcam()

    # ---------------------------------------------------------------- transport
    def play_pause(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.toggle()
            self.changed.emit()

    def play(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.play()
            self.changed.emit()

    def pause(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.pause()
            self.changed.emit()

    def stop(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.stop()
            self.changed.emit()

    def seek(self, position: float) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.seek(position)
            self.changed.emit()

    def nudge(self, seconds: float) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.seek_by(seconds)
            self.changed.emit()

    def set_speed(self, speed: float) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.set_speed(speed)
        self.settings.speed = speed
        self.store.save()
        self.changed.emit()

    def set_loop(self, loop: bool) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.has_transport:
            media.set_loop(loop)
        self.settings.loop = loop
        self.store.save()
        self.changed.emit()

    def next_page(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.kind == "pdf":
            media.next_page()
            self.changed.emit()

    def previous_page(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and media.kind == "pdf":
            media.previous_page()
            self.changed.emit()

    def toggle_freeze(self) -> None:
        """Freeze + me on top on one key; press again to carry on."""
        with self._lock:
            media = self._media
            if media is None or not media.has_transport:
                self._emit_notice("Freeze works on videos — open a video first")
                return
            if not self._frozen:
                self._freeze_was_playing = media.playing
                self._freeze_prev_style = self._overlay_style
                self._frozen = True
                media.pause()
                self._overlay_style = self._freeze_style
            else:
                self._frozen = False
                self._overlay_style = self._freeze_prev_style
                if self._freeze_was_playing:
                    media.play()
        self._sync_webcam_lifecycle()
        self.save()
        self.changed.emit()

    # ------------------------------------------------------------------ effects
    def set_overlay(self, style: str) -> None:
        if style not in OVERLAY_STYLES:
            return
        notice = False
        with self._lock:
            self._overlay_style = style
            if style != "off" and self._mode == "webcam":
                if self._media is not None:
                    self._mode = "media"
                else:
                    notice = True
        if notice:
            self._emit_notice("Open a lesson file to use Me on top")
        if style in ("cutout", "ghost", "corner"):
            self._ensure_webcam()
        self.save()
        self._sync_webcam_lifecycle()
        self.changed.emit()

    def set_webcam_bg_blur(self, enabled: bool) -> None:
        with self._lock:
            media = self._media
            self._webcam_bg_blur = bool(enabled)
            if enabled and self._mode == "media":
                self._mode = "webcam"
        if media is not None and media.playing:
            media.pause()
        if enabled:
            self._ensure_webcam()
        self.save()
        self._sync_webcam_lifecycle()
        self.changed.emit()

    def set_blur_enabled(self, enabled: bool) -> None:
        self._blur_enabled = bool(enabled)
        self.save()
        self.changed.emit()

    def set_blur_type(self, kind: str) -> None:
        self._blur_type = kind
        self._blur_enabled = True
        self.save()
        self.changed.emit()

    def set_blur_strength(self, strength: int) -> None:
        self._blur_strength = max(0, min(100, int(strength)))
        self.save()
        self.changed.emit()

    def set_blur_area(self, area: str) -> None:
        if area not in ("whole", "box"):
            return
        self._blur_area = area
        self.save()
        self.changed.emit()

    def set_blur_box(self, box: list[float] | None) -> None:
        if box is not None and len(box) == 4:
            x, y, w, h = (max(0.0, min(1.0, float(v))) for v in box)
            if w < 0.02 or h < 0.02:
                box = None
            else:
                box = [x, y, min(w, 1.0 - x), min(h, 1.0 - y)]
        self._blur_box = box
        self._blur_area = "box" if box is not None else "whole"
        self.settings.blur_box = box
        self.save()
        self.changed.emit()

    def clear_blur_box(self) -> None:
        self.set_blur_box(None)

    def cycle_overlay(self) -> None:
        order = ["off", "cutout", "ghost", "corner"]
        try:
            current = order.index(self._overlay_style)
        except ValueError:
            current = 0
        self.set_overlay(order[(current + 1) % len(order)])

    def cycle_blur_type(self) -> None:
        from .blur import BLUR_KINDS

        try:
            current = BLUR_KINDS.index(self._blur_type)
        except ValueError:
            current = -1
        self.set_blur_type(BLUR_KINDS[(current + 1) % len(BLUR_KINDS)])
        self._blur_enabled = True
        self.save()
        self.changed.emit()

    def change_speed(self, delta: float) -> None:
        self.set_speed(max(0.25, min(3.0, round((self.settings.speed + delta) * 100) / 100)))

    # ------------------------------------------------------------------- audio
    def set_source_volume(self, volume: int) -> None:
        self.settings.source_volume = max(0, min(100, int(volume)))
        self.engine.set_levels(source_volume=self.settings.source_volume / 100)
        self.store.save()

    def set_mic_volume(self, volume: int) -> None:
        self.settings.mic_volume = max(0, min(100, int(volume)))
        self.engine.set_levels(mic_volume=self.settings.mic_volume / 100)
        self.store.save()

    def toggle_source_mute(self) -> None:
        self.settings.source_muted = not self.settings.source_muted
        self.engine.set_levels(source_muted=self.settings.source_muted)
        self.store.save()
        self.changed.emit()

    def toggle_mic_mute(self) -> None:
        self.settings.mic_muted = not self.settings.mic_muted
        self.engine.set_levels(mic_muted=self.settings.mic_muted)
        self.store.save()
        self.changed.emit()

    def set_monitor(self, enabled: bool) -> None:
        self.settings.monitor_enabled = bool(enabled)
        self.engine.set_monitor(enabled)
        self._resync_audio()
        self.store.save()
        self.changed.emit()

    def set_mic_device(self, name: str) -> None:
        self.settings.mic_name = name
        self.engine.reconfigure(mic_name=name)
        self._resync_audio()
        self.store.save()
        self.changed.emit()

    def set_output_device(self, name: str) -> None:
        self.settings.output_name = name
        self.engine.reconfigure(output_name=name, monitor=self.settings.monitor_enabled)
        self._resync_audio()
        self.store.save()
        self.changed.emit()

    def set_monitor_device(self, name: str) -> None:
        self.settings.monitor_name = name
        self.engine.reconfigure(monitor_name=name, monitor=self.settings.monitor_enabled)
        self._resync_audio()
        self.store.save()
        self.changed.emit()

    @staticmethod
    def audio_devices():
        return list_audio_devices()

    def _resync_audio(self) -> None:
        with self._lock:
            media = self._media
        if media is not None and getattr(media, "audio", None) is not None:
            try:
                media.audio.resync()
            except AttributeError:
                pass
        self._emit_status()

    # ------------------------------------------------------------------ output
    def retry_output(self) -> None:
        self.sink.close()
        if not self.preview_only:
            self.sink.open()
        self._emit_status()
        self.changed.emit()

    def _emit_status(self) -> None:
        self.status.emit(self.status_text())

    def _emit_notice(self, message: str) -> None:
        self._notice = message
        log.info("Notice: %s", message)
        self.notice.emit(message)

    def publish_preview(self, frame: np.ndarray) -> None:
        try:
            rgb = to_rgb(frame)
            image = QImage(rgb.data, FRAME_W, FRAME_H, 3 * FRAME_W, QImage.Format_RGB888).copy()
            self.preview.emit(image)
        except Exception as exc:  # noqa: BLE001
            log.debug("Preview failed: %s", exc)

    def publish_stats(self, fps: float) -> None:
        self.stats.emit(fps)
        self.position.emit(*self.media_position())

    # ------------------------------------------------------------------- frames
    def compose(self) -> np.ndarray:
        with self._lock:
            mode = self._mode
            media = self._media
            webcam = self._webcam
            overlay_style = self._overlay_style
            bg_blur = self._webcam_bg_blur
            blur_enabled = self._blur_enabled
            blur_type = self._blur_type
            blur_strength = self._blur_strength
            blur_area = self._blur_area
            blur_box = self._blur_box
        try:
            if mode == "webcam":
                if webcam is None:
                    return placeholder("Camera off", "Pick a camera in the panel, or open a lesson file")
                frame, raw = webcam.frame_pair()
                if frame is None:
                    if webcam.error:
                        return placeholder("Camera unavailable", "Allow Camera access in System Settings, then Refresh")
                    return placeholder("Waiting for the camera...", webcam.device_name)
                if bg_blur:
                    if raw is not None:
                        self.segmenter.submit(raw)
                    mask = self.segmenter.latest()
                    if mask is not None:
                        frame = background_blur(frame, mask, strength=blur_strength if blur_enabled else 60)
                    else:
                        self._note_error("Background removal is starting — keeping the background for now")
                elif blur_enabled:
                    frame = apply_blur(frame, blur_type, blur_strength, blur_box if blur_area == "box" else None)
                return frame

            if media is None:
                return placeholder("Open a lesson file", "Videos, PDFs and images - drag one onto this window")
            base = media.frame()
            if base is None:
                return placeholder("Loading...", media.title)
            if blur_enabled:
                base = apply_blur(base, blur_type, blur_strength, blur_box if blur_area == "box" else None)
            if overlay_style != "off" and webcam is not None:
                person, raw = webcam.frame_pair()
                if person is not None:
                    if raw is not None and overlay_style in ("cutout", "ghost"):
                        self.segmenter.submit(raw)
                    mask = self.segmenter.latest() if overlay_style in ("cutout", "ghost") else None
                    if overlay_style in ("cutout", "ghost") and mask is None:
                        self._note_error("Background removal is starting — using corner view for now")
                    base = overlay_person(base, person, mask, overlay_style)
            return base
        except Exception as exc:  # noqa: BLE001
            self._note_error(f"Frame error: {exc}")
            return placeholder("Something went wrong", str(exc)[:120])

    def _note_error(self, message: str) -> None:
        now = time.monotonic()
        if message != self._last_error or now - self._last_error_at > 5.0:
            self._last_error = message
            self._last_error_at = now
            log.warning(message)
            self.notice.emit(message)
