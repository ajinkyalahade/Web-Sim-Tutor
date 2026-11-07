from __future__ import annotations

import time

from websim.config import SettingsStore
from websim.ui.main_window import MainWindow
from websim.ui.style import apply_theme


def _spin(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_window_boots_with_test_pattern(app, tmp_path):
    apply_theme(app)
    store = SettingsStore(tmp_path / "settings.json")
    store.settings.global_shortcuts = False
    store.settings.output_name = "__none__"
    window = MainWindow(store, preview_only=True, enable_audio=False)
    window.show()
    try:
        window.start(test_pattern=True)
        _spin(app, 0.6)
        assert window.panel.file_label.text() == "Test pattern"
        assert window.panel.media_btn.isChecked()
        assert "Preview only" in window.status.text()
        assert window.panel.camera_combo.count() >= 1
        assert window.panel.output_combo.count() >= 1

        studio = window.studio
        window.action("blur")
        assert studio.blur_enabled
        window.action("blur")
        assert not studio.blur_enabled

        window.action("overlay_cycle")
        assert studio.overlay_style != "off"
        for _ in range(3):
            window.action("overlay_cycle")
        assert studio.overlay_style == "off"

        window.action("mute_mic")
        assert studio.settings.mic_muted
        window.action("mute_mic")
        assert not studio.settings.mic_muted

        window.action("slower")
        assert studio.settings.speed < 1.0
        window.action("faster")
        assert abs(studio.settings.speed - 1.0) < 1e-6

        window._box_drawn([0.2, 0.2, 0.4, 0.3])
        assert studio.blur_box == [0.2, 0.2, 0.4, 0.3]
        assert window.preview._box == studio.blur_box
        window.action("clear_box")
        assert studio.blur_box is None

        window.close()
        assert studio.loop is None
    finally:
        if not window._closing:
            window.close()
