from __future__ import annotations

import time

import numpy as np

from websim.audio import AudioEngine, PcmReader
from websim.sources.video import VideoSource


def test_video_audio_track_feeds_the_mixer(sample_video):
    engine = AudioEngine()
    source = VideoSource(sample_video, audio_engine=engine)
    try:
        assert source.audio is not None
        assert source.audio.available
        source.play()
        time.sleep(1.0)
        assert engine.video.write_index > 4800
        first = engine.video.media_at(0)
        assert first is not None
        assert 0.0 <= first < 1.0
        source.pause()
        time.sleep(0.25)
        assert engine.video.write_index == 0, "pause should flush buffered audio"
        source.play()
        time.sleep(0.2)
        assert engine.video.write_index > 0
        source.set_speed(2.0)
        time.sleep(0.3)
        assert engine.video.write_index >= 0
        source.seek(1.5)
        time.sleep(0.4)
        assert engine.video.write_index > 0
    finally:
        source.close()


def test_mixer_levels_and_mutes():
    engine = AudioEngine()
    video_reader = engine.video.new_reader()
    mic_reader = engine.mic.new_reader()

    def feed():
        engine.video.write(np.full((1024, 2), 0.5, dtype=np.float32))
        engine.mic.write(np.full((1024, 2), 0.2, dtype=np.float32))

    feed()
    engine.set_levels(source_volume=0.5, mic_volume=0.25)
    block = engine._next_block(video_reader, mic_reader, monitor=False)
    assert abs(float(block.mean()) - (0.25 + 0.05)) < 0.02

    feed()
    engine.set_levels(source_muted=True)
    block = engine._next_block(video_reader, mic_reader, monitor=False)
    assert abs(float(block.mean()) - 0.05) < 0.02

    feed()
    engine.set_levels(mic_muted=True, source_muted=False)
    block = engine._next_block(video_reader, mic_reader, monitor=False)
    assert abs(float(block.mean()) - 0.25) < 0.02

    feed()
    block = engine._next_block(video_reader, mic_reader, monitor=True)
    assert abs(float(block.mean()) - 0.25) < 0.02  # monitor never carries the mic
    engine.shutdown()


def test_tone_is_added_to_the_virtual_mix():
    engine = AudioEngine()
    video_reader = engine.video.new_reader()
    mic_reader = engine.mic.new_reader()
    engine.video.write(np.zeros((1024, 2), dtype=np.float32))
    engine.set_levels(tone=True)
    block = engine._next_block(video_reader, mic_reader, monitor=False)
    assert np.max(np.abs(block)) > 0.05
    engine.shutdown()


def test_no_output_sentinel_keeps_streams_off():
    engine = AudioEngine()
    engine.start(mic_name="", output_name="__none__", monitor_name="", monitor=False)
    assert engine.devices["output"] == ""
    assert engine.output_active is False
    engine.shutdown()


def test_reader_defaults_to_zero():
    reader = PcmReader()
    assert reader.pos == 0
