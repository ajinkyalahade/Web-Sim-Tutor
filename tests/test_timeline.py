from __future__ import annotations

import numpy as np

from websim.audio import PcmReader, PcmTimeline, StreamResampler


def _block(value: float, frames: int = 1024) -> np.ndarray:
    return np.full((frames, 2), value, dtype=np.float32)


def test_read_advances_and_reports_buffered():
    timeline = PcmTimeline()
    reader = timeline.new_reader()
    timeline.write(_block(0.5, 1000))
    assert timeline.buffered(reader) == 1000
    out = timeline.read(reader, 512)
    assert np.allclose(out, 0.5)
    assert timeline.buffered(reader) == 488


def test_underrun_does_not_skip_audio():
    timeline = PcmTimeline()
    reader = timeline.new_reader()
    timeline.write(_block(0.25, 100))
    out = timeline.read(reader, 1000)
    assert np.allclose(out[:100], 0.25)
    assert np.allclose(out[100:], 0.0)
    assert reader.pos == 100
    timeline.write(_block(0.75, 100))
    out = timeline.read(reader, 50)
    assert np.allclose(out, 0.75)


def test_multiple_readers_are_independent():
    timeline = PcmTimeline()
    a = timeline.new_reader()
    b = timeline.new_reader()
    timeline.write(_block(0.3, 2000))
    first = timeline.read(a, 1024)
    second = timeline.read(b, 1024)
    assert np.allclose(first, 0.3)
    assert np.allclose(second, 0.3)
    assert a.pos == 1024 and b.pos == 1024


def test_flush_resets_readers():
    timeline = PcmTimeline()
    reader = timeline.new_reader()
    timeline.write(_block(0.6, 3000))
    timeline.read(reader, 2048)
    timeline.flush()
    assert timeline.write_index == 0
    assert reader.pos == 0
    assert timeline.buffered(reader) == 0


def test_media_time_mapping_with_speed():
    timeline = PcmTimeline()
    timeline.write(_block(0.1, 4800), media_pts=10.0, speed=2.0)
    assert abs(timeline.media_at(0) - 10.0) < 1e-6
    assert abs(timeline.media_at(4800) - 10.2) < 1e-3


def test_trimming_keeps_recent_audio():
    timeline = PcmTimeline(max_seconds=0.1)
    timeline.write(_block(0.2, 48000))
    assert timeline.write_index == 48000
    assert len(timeline._chunks) == 1
    # one more chunk pushes the first out
    timeline.write(_block(0.9, 4800))
    reader = timeline.new_reader()
    assert len(timeline._chunks) <= 2
    assert reader.pos == 52800


def test_stream_resampler_length_and_values():
    resampler = StreamResampler(44100, 48000)
    mono = np.sin(np.arange(4410) * 0.05).astype(np.float32)
    out = resampler.process(mono)
    assert len(out) > 4700
    assert out.dtype == np.float32
    assert np.max(np.abs(out)) <= 1.01


def test_reader_can_be_positioned():
    reader = PcmReader(512)
    assert reader.pos == 512
    reader.snap(-5)
    assert reader.pos == 0
