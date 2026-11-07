from __future__ import annotations

import time

from websim.config import SettingsStore
from websim.studio import Studio


def _spin(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _store(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.settings.global_shortcuts = False
    store.settings.output_name = "__none__"
    return store


def test_test_pattern_preview_and_controls(app, tmp_path):
    store = _store(tmp_path)
    studio = Studio(store, preview_only=True, enable_audio=False)
    frames = []
    studio.preview.connect(lambda image: frames.append(image))
    try:
        studio.start(test_pattern=True)
        _spin(app, 0.7)
        assert studio.media_title() == "Test pattern"
        assert studio.compose().shape == (720, 1280, 3)
        assert len(frames) > 3
        assert frames[0].width() == 1280
    finally:
        studio.shutdown()


def test_open_video_and_transport(app, tmp_path, sample_video):
    store = _store(tmp_path)
    studio = Studio(store, preview_only=True, enable_audio=False)
    try:
        studio.start(test_pattern=True)
        studio.open_file(str(sample_video))
        _spin(app, 0.5)
        assert studio.media_title() == sample_video.name
        assert studio.playing()
        studio.pause()
        studio.media_position()
        studio.seek(1.5)
        assert abs(studio.media_position()[0] - 1.5) < 0.1
        studio.set_loop(True)
        studio.set_speed(1.5)
        assert abs(studio.settings.speed - 1.5) < 1e-6
        studio.compose()
    finally:
        studio.shutdown()


def test_freeze_pauses_and_restores(app, tmp_path, sample_video):
    store = _store(tmp_path)
    studio = Studio(store, preview_only=True, enable_audio=False)
    try:
        studio.start(test_pattern=True)
        studio.open_file(str(sample_video))
        _spin(app, 0.4)
        studio.set_overlay("off")
        before_style = studio.overlay_style
        studio.toggle_freeze()
        assert studio.frozen
        assert not studio.playing()
        assert studio.overlay_style != "off"
        studio.toggle_freeze()
        assert not studio.frozen
        assert studio.overlay_style == before_style
        assert studio.playing()
    finally:
        studio.shutdown()


def test_blur_box_roundtrip(app, tmp_path):
    store = _store(tmp_path)
    studio = Studio(store, preview_only=True, enable_audio=False)
    try:
        studio.start(test_pattern=True)
        studio.set_blur_box([0.2, 0.3, 0.4, 0.2])
        assert studio.blur_area == "box"
        assert studio.blur_box == [0.2, 0.3, 0.4, 0.2]
        studio.clear_blur_box()
        assert studio.blur_box is None
        assert studio.blur_area == "whole"
        studio.set_blur_strength(120)
        assert studio.blur_strength == 100
        studio.cycle_overlay()
        studio.cycle_blur_type()
        studio.compose()
    finally:
        studio.shutdown()


def test_audio_disabled_status(app, tmp_path):
    store = _store(tmp_path)
    studio = Studio(store, preview_only=True, enable_audio=False)
    try:
        studio.start(test_pattern=True)
        _spin(app, 0.1)
        assert "Preview only" in studio.status_text()
        assert "Audio disabled" in studio.status_text()
    finally:
        studio.shutdown()
