from __future__ import annotations

from websim.config import SettingsStore


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.settings.overlay_style == "off"
    store.settings.overlay_style = "ghost"
    store.settings.mic_volume = 42
    store.settings.blur_box = [0.1, 0.2, 0.3, 0.4]
    store.save()

    reloaded = SettingsStore(path)
    assert reloaded.settings.overlay_style == "ghost"
    assert reloaded.settings.mic_volume == 42
    assert reloaded.settings.blur_box == [0.1, 0.2, 0.3, 0.4]


def test_settings_sanitises_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"overlay_style": "nope", "blur_type": "nope", "mic_volume": 900, '
        '"speed": 99, "blur_box": [2, 2, 0, 0], "window_width": 10, "recent_files": ["a", 3]}'
    )
    store = SettingsStore(path)
    assert store.settings.overlay_style == "off"
    assert store.settings.blur_type == "gaussian"
    assert store.settings.mic_volume == 100
    assert store.settings.speed == 3.0
    assert store.settings.blur_box is None
    assert store.settings.window_width >= 900
    assert store.settings.recent_files == ["a"]


def test_remember_file(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.pdf"
    store.remember_file(str(first))
    store.remember_file(str(second))
    store.remember_file(str(first))
    assert store.settings.recent_files[0] == str(first)
    assert store.settings.recent_files.count(str(first)) == 1
    assert store.settings.last_media_dir == str(tmp_path)


def test_corrupt_settings_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    store = SettingsStore(path)
    assert store.settings.speed == 1.0
