"""Audio: virtual microphone mixing, video sound, mic passthrough, monitor.

The virtual cable gets a mix of the video's sound and the real microphone; the
optional monitor output is video sound only (so headphones never feed back).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

try:  # PortAudio may be missing on a bare machine
    import sounddevice as sd
except Exception:  # noqa: BLE001
    sd = None  # type: ignore[assignment]

RATE = 48000
CHANNELS = 2
BLOCK = 1024
VIDEO_LOOKAHEAD = 0.12  # seconds of video sound kept decoded ahead of the video clock
TONE_HZ = 440.0
NO_OUTPUT = "__none__"


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    inputs: int
    outputs: int
    hostapi: str = ""
    default_rate: float = RATE

    @property
    def is_virtual_output(self) -> bool:
        n = self.name.lower()
        return any(k in n for k in ("blackhole", "cable output", "cable input", "vb-audio", "virtual cable"))


def list_audio_devices() -> list[AudioDevice]:
    if sd is None:
        return []
    try:
        hostapis = sd.query_hostapis()
        out: list[AudioDevice] = []
        for index, dev in enumerate(sd.query_devices()):
            host = ""
            try:
                host = str(hostapis[dev["hostapi"]]["name"])
            except Exception:  # noqa: BLE001
                pass
            out.append(
                AudioDevice(
                    index=index,
                    name=str(dev["name"]),
                    inputs=int(dev["max_input_channels"]),
                    outputs=int(dev["max_output_channels"]),
                    hostapi=host,
                    default_rate=float(dev.get("default_samplerate") or RATE),
                )
            )
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not enumerate audio devices: %s", exc)
        return []


def _default_name(kind: str) -> str:
    if sd is None:
        return ""
    try:
        index = sd.default.device[0 if kind == "input" else 1]
        if index is None or int(index) < 0:
            return ""
        return str(sd.query_devices(int(index))["name"])
    except Exception:  # noqa: BLE001
        return ""


def default_input_name() -> str:
    return _default_name("input")


def default_output_name() -> str:
    return _default_name("output")


def find_device(name: str, *, want_input: bool = False, want_output: bool = False) -> int | None:
    if not name or sd is None:
        return None
    for dev in list_audio_devices():
        if dev.name != name:
            continue
        if want_input and dev.inputs <= 0:
            continue
        if want_output and dev.outputs <= 0:
            continue
        return dev.index
    return None


def guess_virtual_output(devices: list[AudioDevice] | None = None) -> str:
    devices = devices if devices is not None else list_audio_devices()
    for dev in devices:
        if dev.outputs > 0 and dev.is_virtual_output:
            return dev.name
    return ""


def guess_virtual_input(devices: list[AudioDevice] | None = None) -> str:
    devices = devices if devices is not None else list_audio_devices()
    for dev in devices:
        if dev.inputs > 0 and dev.is_virtual_output:
            return dev.name
    return ""


class PcmReader:
    """One independent cursor into an :class:`PcmTimeline`."""

    def __init__(self, start: int = 0) -> None:
        self.pos = max(0, int(start))

    def snap(self, position: int) -> None:
        self.pos = max(0, int(position))


class PcmTimeline:
    """Append-only float32 stereo PCM with multiple readers and trimming."""

    def __init__(self, rate: int = RATE, channels: int = CHANNELS, max_seconds: float = 3.0) -> None:
        self.rate = rate
        self.channels = channels
        self._lock = threading.RLock()
        self._chunks: deque[tuple[int, np.ndarray]] = deque()
        self._segments: deque[tuple[int, float, float]] = deque()  # start frame, media pts, speed
        self._readers: list[PcmReader] = []
        self.write_index = 0
        self.max_frames = int(max_seconds * rate)

    # ------------------------------------------------------------------ write
    def new_reader(self, prefill: int = 0) -> PcmReader:
        with self._lock:
            reader = PcmReader()
            reader.snap(max(0, self.write_index - prefill))
            self._readers.append(reader)
            return reader

    def write(self, samples: np.ndarray, media_pts: float | None = None, speed: float = 1.0) -> None:
        if samples is None or samples.size == 0:
            return
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim == 1:
            samples = np.column_stack([samples, samples])
        if samples.shape[1] != self.channels:
            if samples.shape[1] == 1:
                samples = np.repeat(samples, self.channels, axis=1)
            else:
                samples = samples[:, : self.channels]
        with self._lock:
            start = self.write_index
            if media_pts is not None:
                if self._segments:
                    seg_start, seg_pts, seg_speed = self._segments[-1]
                    expected = seg_pts + (start - seg_start) / self.rate * seg_speed
                    if abs(media_pts - expected) > 0.03:
                        self._segments.append((start, float(media_pts), float(speed)))
                else:
                    self._segments.append((start, float(media_pts), float(speed)))
            self._chunks.append((start, samples))
            self.write_index += len(samples)
            self._trim_locked()

    def _trim_locked(self) -> None:
        keep_from = self.write_index - self.max_frames
        while self._chunks and self._chunks[0][0] + len(self._chunks[0][1]) <= keep_from:
            self._chunks.popleft()
        while len(self._segments) > 40:
            self._segments.popleft()

    # ------------------------------------------------------------------- read
    def read(self, reader: PcmReader, frames: int) -> np.ndarray:
        out = np.zeros((frames, self.channels), dtype=np.float32)
        with self._lock:
            oldest = self._chunks[0][0] if self._chunks else self.write_index
            if reader.pos < oldest:
                reader.pos = oldest
            start = reader.pos
            # Never run ahead of the writer: on underrun the reader waits for new
            # audio instead of skipping it (keeps the video sync intact).
            available = max(0, min(frames, self.write_index - start))
            if available <= 0:
                return out
            remaining = available
            for chunk_start, chunk in self._chunks:
                chunk_end = chunk_start + len(chunk)
                if chunk_end <= start:
                    continue
                if chunk_start >= start + remaining:
                    break
                src_off = max(0, start - chunk_start)
                dst_off = max(0, chunk_start - start)
                n = min(chunk_end - chunk_start - src_off, remaining - dst_off)
                if n > 0:
                    out[dst_off : dst_off + n] = chunk[src_off : src_off + n]
                if dst_off + n >= remaining:
                    break
            reader.pos = start + available
        return out

    def buffered(self, reader: PcmReader) -> int:
        with self._lock:
            return max(0, self.write_index - reader.pos)

    def flush(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._segments.clear()
            self.write_index = 0
            for reader in self._readers:
                reader.snap(0)

    def live_position(self, prefill: int = 0) -> int:
        with self._lock:
            return max(0, self.write_index - prefill)

    def media_at(self, frame_index: int) -> float | None:
        with self._lock:
            if not self._segments:
                return None
            best = self._segments[0]
            for seg in self._segments:
                if seg[0] <= frame_index:
                    best = seg
                else:
                    break
            start, pts, speed = best
            return max(0.0, pts + (frame_index - start) / self.rate * speed)


class StreamResampler:
    """Small continuous linear resampler for mic input rates != engine rate."""

    def __init__(self, source_rate: float, target_rate: float = RATE) -> None:
        self.ratio = float(target_rate) / float(source_rate) if source_rate else 1.0
        self._phase = 0.0
        self._last = 0.0

    def process(self, mono: np.ndarray) -> np.ndarray:
        if abs(self.ratio - 1.0) < 1e-6 or len(mono) == 0:
            return mono
        x = np.concatenate((np.array([self._last], dtype=np.float32), mono.astype(np.float32)))
        positions = self._phase + np.arange(0, len(x) - 1, 1.0 / self.ratio)
        out = np.interp(positions, np.arange(len(x)), x).astype(np.float32)
        consumed = float(positions[-1]) if len(positions) else 0.0
        self._phase = max(0.0, consumed - (len(x) - 1))
        self._last = float(mono[-1])
        return out


class AudioEngine:
    """Owns the mic input and every output stream; mixes video sound + mic."""

    def __init__(self) -> None:
        self.rate = RATE
        self.video = PcmTimeline(self.rate)
        self.mic = PcmTimeline(self.rate, max_seconds=1.0)
        self._lock = threading.RLock()
        self._mic_stream = None
        self._outputs: dict[str, tuple[object, PcmReader, PcmReader]] = {}
        self._threads: list[threading.Thread] = []
        self._mic_resampler: StreamResampler | None = None
        self.source_volume = 0.8
        self.mic_volume = 1.0
        self.source_muted = False
        self.mic_muted = False
        self.tone = False
        self.status = "Audio off"
        self._tone_phase = 0.0
        self.devices = {"output": "", "monitor": "", "mic": ""}
        self.choices = {"output": "", "monitor": "", "mic": ""}
        self._stop = threading.Event()

    # -------------------------------------------------------------- lifecycle
    def start(self, *, mic_name: str = "", output_name: str = "", monitor_name: str = "", monitor: bool = False) -> None:
        if sd is None:
            self.status = "Audio unavailable (sounddevice/PortAudio missing)"
            return
        self.stop()
        self._stop.clear()
        requested = output_name
        if requested == NO_OUTPUT:
            resolved_output = ""
        else:
            resolved_output = requested or guess_virtual_output()
        self.devices = {
            "mic": mic_name or default_input_name(),
            "output": resolved_output,
            "monitor": monitor_name or default_output_name(),
        }
        self.choices = {"mic": mic_name, "output": output_name, "monitor": monitor_name}
        self.video.flush()
        self.mic.flush()
        self._start_mic(self.devices["mic"])
        if self.devices["output"]:
            self._start_output("virtual", self.devices["output"], monitor=False)
        if monitor and self.devices["monitor"]:
            self._start_output("monitor", self.devices["monitor"], monitor=True)
        if self._outputs:
            status = "Audio live → " + ", ".join(self._outputs.keys())
            if self._mic_stream is None:
                status += " (no microphone)"
            self.status = status
        elif self._mic_stream is not None:
            self.status = "Microphone on, no virtual audio output selected"
        else:
            self.status = "No audio devices"

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            streams = [entry[0] for entry in self._outputs.values()]
            self._outputs.clear()
            mic = self._mic_stream
            self._mic_stream = None
        for stream in streams:
            try:
                stream.stop()  # type: ignore[attr-defined]
                stream.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        if mic is not None:
            try:
                mic.stop()  # type: ignore[attr-defined]
                mic.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()

    def reconfigure(self, *, mic_name: str | None = None, output_name: str | None = None,
                    monitor_name: str | None = None, monitor: bool | None = None) -> None:
        self.start(
            mic_name=self.choices["mic"] if mic_name is None else mic_name,
            output_name=self.choices["output"] if output_name is None else output_name,
            monitor_name=self.choices["monitor"] if monitor_name is None else monitor_name,
            monitor=self.monitor_enabled if monitor is None else monitor,
        )

    @property
    def monitor_enabled(self) -> bool:
        return "monitor" in self._outputs

    @property
    def output_active(self) -> bool:
        return "virtual" in self._outputs

    # ------------------------------------------------------------------- mic
    def _start_mic(self, name: str) -> None:
        if sd is None:
            return
        try:
            default_in = int(sd.default.device[0]) if sd.default.device[0] is not None else -1
        except Exception:  # noqa: BLE001
            default_in = -1
        index = find_device(name, want_input=True) if name else default_in
        if index is None and name:
            log.warning("Microphone %s not found; using system default", name)
            index = default_in
        if index is None or index < 0:
            log.warning("Microphone not found: %s", name or "system default")
            return
        try:
            info = sd.query_devices(index)
            max_in = int(info["max_input_channels"])
            channels = 1 if max_in >= 1 else 2
            rate = int(info.get("default_samplerate") or self.rate)
            selected = False
            for candidate in ([1, 2] if max_in >= 2 else [1]):
                try:
                    sd.check_input_settings(device=index, channels=candidate, samplerate=self.rate, dtype="float32")
                    channels, rate, selected = candidate, self.rate, True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not selected:
                rate = int(info["default_samplerate"] or self.rate)
            self._mic_resampler = StreamResampler(rate, self.rate)

            def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
                if status:
                    log.debug("Mic status: %s", status)
                data = np.asarray(indata, dtype=np.float32)
                mono = data.mean(axis=1) if data.ndim > 1 and data.shape[1] > 1 else data.reshape(-1)
                if self._mic_resampler is not None:
                    mono = self._mic_resampler.process(mono)
                self.mic.write(np.column_stack([mono, mono]))

            stream = sd.InputStream(
                device=index,
                channels=channels,
                samplerate=rate,
                dtype="float32",
                blocksize=0,
                callback=callback,
            )
            stream.start()
            with self._lock:
                self._mic_stream = stream
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open microphone %s: %s", name or index, exc)
            self._mic_stream = None

    # ---------------------------------------------------------------- outputs
    def _start_output(self, key: str, name: str, *, monitor: bool) -> None:
        if sd is None:
            return
        index = find_device(name, want_output=True)
        if index is None:
            log.warning("Output device not found: %s", name)
            return
        try:
            sd.check_output_settings(device=index, channels=CHANNELS, samplerate=self.rate, dtype="float32")
            stream = sd.OutputStream(
                device=index,
                channels=CHANNELS,
                samplerate=self.rate,
                dtype="float32",
                blocksize=BLOCK,
                latency="low",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open output %s: %s", name, exc)
            return
        video_reader = self.video.new_reader()
        mic_reader = self.mic.new_reader()
        with self._lock:
            self._outputs[key] = (stream, video_reader, mic_reader)
        stream.start()
        thread = threading.Thread(
            target=self._output_loop,
            args=(key, stream, video_reader, mic_reader, monitor),
            name=f"websim-audio-{key}",
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)

    def _output_loop(self, key: str, stream, video_reader: PcmReader, mic_reader: PcmReader, monitor: bool) -> None:
        while not self._stop.is_set():
            try:
                block = self._next_block(video_reader, mic_reader, monitor=monitor)
                stream.write(block)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set():
                    log.debug("Audio output %s stopped: %s", key, exc)
                break
        try:
            stream.stop()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    def _next_block(self, video_reader: PcmReader, mic_reader: PcmReader, *, monitor: bool) -> np.ndarray:
        video = self.video.read(video_reader, BLOCK)
        if self.source_muted:
            video = np.zeros_like(video)
        elif self.source_volume != 1.0:
            video = video * float(self.source_volume)
        if self.tone:
            video = video + self._tone_block()
        if monitor:
            mix = video
        else:
            mic = self.mic.read(mic_reader, BLOCK)
            if self.mic_muted:
                mic = np.zeros_like(mic)
            elif self.mic_volume != 1.0:
                mic = mic * float(self.mic_volume)
            mix = video + mic
        return np.clip(mix, -1.0, 1.0).astype(np.float32)

    def _tone_block(self) -> np.ndarray:
        t = (np.arange(BLOCK, dtype=np.float32) + self._tone_phase) / self.rate
        wave = (0.16 * np.sin(2 * math.pi * TONE_HZ * t)).astype(np.float32)
        self._tone_phase = (self._tone_phase + BLOCK) % self.rate
        return np.column_stack([wave, wave])

    # ----------------------------------------------------------------- levels
    def set_levels(
        self,
        *,
        source_volume: float | None = None,
        mic_volume: float | None = None,
        source_muted: bool | None = None,
        mic_muted: bool | None = None,
        tone: bool | None = None,
    ) -> None:
        with self._lock:
            if source_volume is not None:
                self.source_volume = max(0.0, min(1.0, source_volume))
            if mic_volume is not None:
                self.mic_volume = max(0.0, min(1.0, mic_volume))
            if source_muted is not None:
                self.source_muted = bool(source_muted)
            if mic_muted is not None:
                self.mic_muted = bool(mic_muted)
            if tone is not None:
                self.tone = bool(tone)

    def set_monitor(self, enabled: bool) -> None:
        if enabled == self.monitor_enabled:
            return
        self.start(
            mic_name=self.choices["mic"],
            output_name=self.choices["output"],
            monitor_name=self.choices["monitor"],
            monitor=enabled,
        )

    def flush_video(self) -> None:
        self.video.flush()

    def shutdown(self) -> None:
        self.stop()


class VideoAudioTrack:
    """Decodes a video's audio track and feeds it to the engine, in sync."""

    def __init__(self, source, engine: AudioEngine, path: str | Path | None = None) -> None:
        self.source = source
        self.engine = engine
        self.path = str(path or source.path)
        self.available = False
        self._container = None
        self._stream = None
        self._time_base = 1.0
        self._resampler = None
        self._graph = None
        self._graph_speed = 1.0
        self._tempo_broken = False
        self._running = True
        self._generation = -1
        self._was_playing = False
        self._eof = False
        self._audio_end = 0.0
        self._frames_iter = None
        self._thread: threading.Thread | None = None
        try:
            import av

            self._container = av.open(self.path)
            if not self._container.streams.audio:
                self._container.close()
                self._container = None
                return
            self._stream = self._container.streams.audio[0]
            self._time_base = float(self._stream.time_base)
        except Exception as exc:  # noqa: BLE001
            log.debug("No usable audio in %s: %s", self.path, exc)
            self.close()
            return
        self.available = True
        self._audio_end = max(0.0, self.source.position)
        self._thread = threading.Thread(target=self._loop, name="websim-video-audio", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------- loop
    def _loop(self) -> None:
        while self._running:
            state = self.source.snapshot()
            if state.generation != self._generation:
                self._generation = state.generation
                self._restart(state.position, state.speed)
                continue

            if not state.playing:
                if self._was_playing:
                    self.engine.flush_video()
                    self._was_playing = False
                time.sleep(0.02)
                continue

            if not self._was_playing:
                self._was_playing = True
                self._seek(state.position)
                self.engine.flush_video()
                self._audio_end = state.position
                self._eof = False

            if self._set_speed(state.speed):
                self._seek(state.position)
                self.engine.flush_video()
                self._audio_end = state.position
                self._eof = False

            if self._eof:
                time.sleep(0.02)
                continue

            # keep only a short cushion of decoded audio ahead of the video
            if self._audio_end - state.position >= VIDEO_LOOKAHEAD:
                time.sleep(0.006)
                continue

            try:
                self._decode_one()
            except Exception as exc:  # noqa: BLE001
                log.debug("Video audio decode error: %s", exc)
                self._eof = True
                time.sleep(0.05)

    def _restart(self, position: float, speed: float) -> None:
        self._seek(position)
        self._set_speed(speed)
        self.engine.flush_video()
        self._audio_end = position
        self._eof = False

    def _decode_one(self) -> None:
        if self._container is None or self._stream is None:
            return
        if self._frames_iter is None:
            self._frames_iter = self._container.decode(self._stream)
        try:
            frame = next(self._frames_iter, None)
        except Exception:  # noqa: BLE001
            frame = None
        if frame is None:
            self._frames_iter = None
            self._eof = True
            return
        try:
            pts = float(frame.pts * self._time_base) if frame.pts is not None else self._audio_end
        except Exception:  # noqa: BLE001
            pts = self._audio_end

        # After a seek the decoder may hand us a little pre-roll. Drop audio
        # that ends before where the video actually is.
        position = self.source.snapshot().position
        try:
            frame_seconds = int(frame.samples) / float(frame.sample_rate or self.engine.rate)
        except Exception:  # noqa: BLE001
            frame_seconds = 0.02
        if pts + frame_seconds * self._graph_speed < position - 0.035:
            return

        written = 0
        for out in self._stretch(frame):
            pcm = self._pcm(out)
            if pcm is not None and len(pcm):
                self.engine.video.write(pcm, media_pts=pts, speed=self._graph_speed)
                written += len(pcm)
        if written:
            self._audio_end = pts + (written / self.engine.rate) * self._graph_speed

    # ------------------------------------------------------------------- seek
    def _seek(self, position: float) -> None:
        if self._container is None or self._stream is None:
            return
        try:
            self._container.seek(int(max(0.0, position) / self._time_base), stream=self._stream, backward=True)
        except Exception as exc:  # noqa: BLE001
            log.debug("Audio seek failed: %s", exc)
        self._reset_resampler()
        self._graph = None
        self._frames_iter = None
        self._eof = False

    def _reset_resampler(self) -> None:
        try:
            import av

            self._resampler = av.AudioResampler(format="fltp", layout="stereo", rate=self.engine.rate)
        except Exception:  # noqa: BLE001
            self._resampler = None

    # ------------------------------------------------------------------ speed
    def _set_speed(self, speed: float) -> bool:
        if abs(speed - self._graph_speed) < 1e-3:
            return False
        self._graph_speed = float(speed)
        self._graph = None
        self._tempo_broken = False
        self._reset_resampler()
        return True

    def _ensure_graph(self):
        if abs(self._graph_speed - 1.0) < 1e-3 or self._tempo_broken:
            return None
        if self._graph is not None:
            return self._graph
        try:
            import av

            if self._stream is None:
                return None
            graph = av.filter.Graph()
            src = graph.add_abuffer(template=self._stream)
            node = src
            speed = self._graph_speed
            stages = [speed]
            if speed < 0.5:
                stages = [0.5, speed / 0.5]
            elif speed > 2.0:
                stages = [2.0, speed / 2.0]
            for value in stages:
                tempo = graph.add("atempo", f"{max(0.5, min(100.0, value)):.4f}")
                node.link_to(tempo)
                node = tempo
            sink = graph.add("abuffersink")
            node.link_to(sink)
            graph.configure()
            self._graph = graph
            self._graph_in = src
            self._graph_out = sink
            return graph
        except Exception as exc:  # noqa: BLE001
            log.warning("Speed-change audio filter unavailable (%s); keeping original pitch", exc)
            self._tempo_broken = True
            self._graph = None
            return None

    def _stretch(self, frame):
        graph = self._ensure_graph()
        if graph is None or abs(self._graph_speed - 1.0) < 1e-3:
            return [frame]
        try:
            self._graph_in.push(frame)
            out = []
            while True:
                try:
                    pulled = self._graph_out.pull()
                except Exception:  # noqa: BLE001
                    break
                if pulled is not None:
                    out.append(pulled)
            return out or [frame]
        except Exception as exc:  # noqa: BLE001
            log.debug("Audio stretch failed: %s", exc)
            return [frame]

    def _pcm(self, frame) -> np.ndarray | None:
        if self._resampler is None:
            self._reset_resampler()
        if self._resampler is None:
            return None
        try:
            frames = self._resampler.resample(frame)
            out = []
            for f in frames:
                arr = f.to_ndarray()
                if arr.ndim == 2:
                    if arr.shape[0] == 2:
                        arr = arr.T
                    elif arr.shape[1] != 2:
                        arr = np.repeat(arr[:, :1], 2, axis=1)
                out.append(np.ascontiguousarray(arr, dtype=np.float32))
            return np.concatenate(out, axis=0) if out else None
        except Exception as exc:  # noqa: BLE001
            log.debug("Audio resample failed: %s", exc)
            return None

    def close(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._container is not None:
            try:
                self._container.close()
            except Exception:  # noqa: BLE001
                pass
            self._container = None
        self.available = False

    def resync(self) -> None:
        """Re-seek after the audio device changed, without touching video."""
        self.engine.flush_video()
        self._was_playing = False
        self._eof = False
        self._generation = -1
