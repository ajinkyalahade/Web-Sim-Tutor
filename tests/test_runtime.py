from __future__ import annotations

from websim.doctor import report
from websim.output import VirtualCameraSink, probe_virtual_camera
from websim.shortcuts import GLOBAL_BINDINGS


def test_doctor_report_runs():
    text = report()
    assert "WebSim diagnostics" in text
    assert "Virtual camera" in text
    assert "Audio devices" in text
    assert "Background removal" in text


def test_virtual_camera_sink_fails_gracefully():
    sink = VirtualCameraSink()
    ok = sink.open()
    try:
        if ok:
            assert sink.active
            assert "Live" in sink.status
        else:
            assert not sink.active
            assert sink.error
            assert "OBS" in sink.error or "camera" in sink.error.lower()
    finally:
        sink.close()


def test_probe_virtual_camera_returns_message():
    ok, message = probe_virtual_camera()
    assert isinstance(ok, bool)
    assert isinstance(message, str) and message


def test_global_bindings_match_the_plan():
    expected = {
        "play_pause",
        "stop",
        "back",
        "forward",
        "slower",
        "faster",
        "freeze",
        "webcam",
        "media",
        "blur",
        "mute_video",
        "mute_mic",
        "page_prev",
        "page_next",
    }
    assert expected.issubset(GLOBAL_BINDINGS)
    for value in GLOBAL_BINDINGS.values():
        assert value.startswith("<ctrl>+<alt>+")
