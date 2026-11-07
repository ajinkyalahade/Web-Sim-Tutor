"""Windows-specific behaviour, simulated so it runs on any OS."""

from __future__ import annotations

import time
from types import SimpleNamespace

import cv2
import pytest

from websim import audio
from websim.output import VirtualCameraSink, _friendly_error
from websim.sources import webcam

# --------------------------------------------------------------- virtual camera


def test_windows_obs_in_use_is_not_reported_as_missing():
    message = _friendly_error(RuntimeError("virtual camera output could not be started"), "Windows")
    assert "already in use" in message
    assert "Install OBS" not in message


def test_windows_obs_driver_not_registered():
    message = _friendly_error(RuntimeError("OBS Virtual Camera device not found! Did you install OBS?"), "Windows")
    assert "not registered" in message
    assert "Start Virtual Camera" in message


def test_windows_never_shows_macos_permission_text():
    message = _friendly_error(RuntimeError("permission denied"), "Windows")
    assert "macOS" not in message


def test_sink_asks_for_the_obs_backend_only(monkeypatch):
    import pyvirtualcam

    seen = {}

    def fake_camera(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("virtual camera output could not be started")

    monkeypatch.setattr(pyvirtualcam, "Camera", fake_camera)
    monkeypatch.setattr("websim.output.platform.system", lambda: "Windows")
    sink = VirtualCameraSink()
    assert sink.open() is False
    assert seen["backend"] == "obs"
    assert "already in use" in sink.error


# ----------------------------------------------------------------------- webcam


def _fake_enumerate(apiPreference=0):
    msmf = [SimpleNamespace(index=0, name="Integrated Camera", backend=cv2.CAP_MSMF)]
    dshow = [
        SimpleNamespace(index=0, name="Integrated Camera", backend=cv2.CAP_DSHOW),
        SimpleNamespace(index=1, name="OBS Virtual Camera", backend=cv2.CAP_DSHOW),
    ]
    if apiPreference == cv2.CAP_DSHOW:
        return dshow
    if apiPreference == cv2.CAP_MSMF:
        return msmf
    # CAP_ANY: what the library returns by default — every camera twice
    return [SimpleNamespace(index=i.index + i.backend, name=i.name, backend=0) for i in msmf + dshow]


def test_windows_cameras_are_listed_once_with_directshow(monkeypatch):
    import cv2_enumerate_cameras

    monkeypatch.setattr(cv2_enumerate_cameras, "enumerate_cameras", _fake_enumerate)
    devices = webcam.list_cameras(system="Windows")
    assert [(d.index, d.name, d.backend) for d in devices] == [(0, "Integrated Camera", cv2.CAP_DSHOW)]
    with_virtual = webcam.list_cameras(include_virtual=True, system="Windows")
    assert [d.name for d in with_virtual] == ["Integrated Camera", "OBS Virtual Camera"]


def test_windows_fallback_list_uses_directshow(monkeypatch):
    import cv2_enumerate_cameras

    monkeypatch.setattr(cv2_enumerate_cameras, "enumerate_cameras", lambda apiPreference=0: [])
    devices = webcam.list_cameras(system="Windows")
    assert devices and all(d.backend == cv2.CAP_DSHOW for d in devices)


def test_explicit_backend_never_falls_back_to_another_backend():
    # Index 0 on another backend could be a different camera (or OBS itself).
    assert webcam.open_attempts(0, cv2.CAP_DSHOW, "Windows") == [(0, cv2.CAP_DSHOW)]


def test_offset_indices_are_decoded_correctly():
    assert (1, cv2.CAP_MSMF) in webcam.open_attempts(1401, 0, "Windows")
    assert (2, cv2.CAP_DSHOW) in webcam.open_attempts(702, 0, "Windows")
    mac = webcam.open_attempts(1201, 0, "Darwin")
    assert mac[0] == (1201, None)
    assert (1, cv2.CAP_AVFOUNDATION) in mac


# ------------------------------------------------------------------------ audio

CABLE = "CABLE Input (VB-Audio Virtual Cable)"
HOSTAPIS = ["MME", "Windows DirectSound", "Windows WASAPI", "Windows WDM-KS"]
# (name, hostapi, inputs, outputs) in PortAudio's Windows order
DEVICES = [
    ("Microsoft Sound Mapper - Input", 0, 2, 0),
    ("Microphone (Realtek(R) Audio)", 0, 2, 0),
    ("Microsoft Sound Mapper - Output", 0, 0, 2),
    (CABLE[:31], 0, 0, 2),
    ("Speakers (Realtek(R) Audio)", 0, 0, 2),
    ("Microphone (Realtek(R) Audio)", 1, 2, 0),
    (CABLE, 1, 0, 2),
    ("Speakers (Realtek(R) Audio)", 1, 0, 2),
    ("Microphone (Realtek(R) Audio)", 2, 2, 0),
    (CABLE, 2, 0, 2),
    ("Speakers (Realtek(R) Audio)", 2, 0, 2),
    (CABLE, 3, 0, 2),
]


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass

    def write(self, block):
        time.sleep(0.01)


class FakeSd:
    def __init__(self, broken: set[int] | None = None):
        self.broken = broken or set()
        self.default = SimpleNamespace(device=[0, 2])  # MME defaults, like real PortAudio
        self.opened: list[int] = []

    def query_hostapis(self, index=None):
        apis = []
        for i, name in enumerate(HOSTAPIS):
            members = [d for d, dev in enumerate(DEVICES) if dev[1] == i]
            ins = [d for d in members if DEVICES[d][2]]
            outs = [d for d in members if DEVICES[d][3]]
            apis.append({
                "name": name,
                "devices": members,
                "default_input_device": ins[0] if ins else -1,
                "default_output_device": outs[-1] if outs else -1,
            })
        return apis if index is None else apis[index]

    def query_devices(self, index=None):
        rows = [
            {"name": n, "hostapi": h, "max_input_channels": i, "max_output_channels": o, "default_samplerate": 44100.0}
            for n, h, i, o in DEVICES
        ]
        return rows if index is None else rows[index]

    def WasapiSettings(self, auto_convert=False):  # noqa: N802
        return ("wasapi", auto_convert)

    def check_output_settings(self, device, **kwargs):
        if device in self.broken:
            raise RuntimeError("Invalid sample rate")

    def check_input_settings(self, device, **kwargs):
        if device in self.broken:
            raise RuntimeError("Invalid sample rate")

    def OutputStream(self, device, **kwargs):  # noqa: N802
        self.opened.append(device)
        return FakeStream(device=device, **kwargs)

    def InputStream(self, device, **kwargs):  # noqa: N802
        self.opened.append(device)
        return FakeStream(device=device, **kwargs)


@pytest.fixture
def windows_sd(monkeypatch):
    fake = FakeSd()
    monkeypatch.setattr(audio, "sd", fake)
    monkeypatch.setattr(audio, "_system", lambda: "Windows")
    return fake


def test_windows_lists_each_device_once(windows_sd):
    devices = audio.list_audio_devices()
    assert {d.hostapi for d in devices} == {"Windows WASAPI"}
    assert [d.name for d in devices].count(CABLE) == 1
    assert audio.guess_virtual_output(devices) == CABLE


def test_windows_defaults_come_from_the_shown_hostapi(windows_sd):
    assert audio.default_input_name() == "Microphone (Realtek(R) Audio)"
    assert audio.default_output_name() == "Speakers (Realtek(R) Audio)"


def test_truncated_mme_name_from_old_settings_still_resolves(windows_sd):
    candidates = audio.device_candidates(CABLE[:31], want_output=True)
    hosts = [HOSTAPIS[DEVICES[i][1]] for i in candidates]
    assert hosts == ["Windows WASAPI", "Windows DirectSound", "MME"]  # never WDM-KS


def test_wasapi_streams_get_auto_convert(windows_sd):
    assert audio.extra_settings(9) == ("wasapi", True)
    assert audio.extra_settings(6) is None


def test_output_falls_back_when_wasapi_refuses(monkeypatch):
    fake = FakeSd(broken={9})  # WASAPI copy of the cable fails
    monkeypatch.setattr(audio, "sd", fake)
    monkeypatch.setattr(audio, "_system", lambda: "Windows")
    engine = audio.AudioEngine()
    try:
        engine.start(output_name=CABLE)
        assert engine.output_active
        assert 6 in fake.opened  # the DirectSound copy
    finally:
        engine.stop()


def test_non_windows_is_unchanged(monkeypatch):
    fake = FakeSd()
    monkeypatch.setattr(audio, "sd", fake)
    monkeypatch.setattr(audio, "_system", lambda: "Darwin")
    assert audio.preferred_hostapi() is None
    assert len(audio.list_audio_devices()) == len(DEVICES)


VOICEMEETER = "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)"


def test_default_mic_and_headphones_skip_the_virtual_cable(monkeypatch):
    fake = FakeSd()
    monkeypatch.setattr(audio, "sd", fake)
    monkeypatch.setattr(audio, "_system", lambda: "Windows")
    real_query = fake.query_hostapis

    def cable_is_default(index=None):
        apis = real_query()
        apis[2]["default_output_device"] = 9  # WASAPI CABLE Input = default playback
        return apis if index is None else apis[index]

    monkeypatch.setattr(fake, "query_hostapis", cable_is_default)
    assert audio.default_output_name() == "Speakers (Realtek(R) Audio)"


def test_cable_input_beats_voicemeeter():
    devices = [
        audio.AudioDevice(0, VOICEMEETER, 0, 2),
        audio.AudioDevice(1, CABLE, 0, 2),
    ]
    assert audio.guess_virtual_output(devices) == CABLE


# ---------------------------------------------------------------- async webcam


class FakeCapture:
    open_delay = 0.0
    opened = True
    frames = True
    instances: list[FakeCapture] = []

    def __init__(self, index, backend=None):
        time.sleep(self.open_delay)
        self.index, self.backend = index, backend
        self.props: dict[int, float] = {}
        self.released = False
        FakeCapture.instances.append(self)

    def isOpened(self):  # noqa: N802
        return self.opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def read(self):
        time.sleep(0.005)
        if not self.frames:
            return False, None
        import numpy as np

        return True, np.zeros((720, 1280, 3), dtype=np.uint8)

    def release(self):
        self.released = True


@pytest.fixture
def fake_capture(monkeypatch):
    class Capture(FakeCapture):
        instances: list = []

    Capture.instances = FakeCapture.instances = []
    monkeypatch.setattr(webcam.cv2, "VideoCapture", Capture)
    return Capture


def _wait(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_webcam_opens_off_the_calling_thread(fake_capture):
    fake_capture.open_delay = 0.5
    started = time.monotonic()
    source = webcam.WebcamSource(0, "Slow camera", cv2.CAP_DSHOW)
    try:
        assert time.monotonic() - started < 0.2, "constructor must not block on the driver"
        assert source.opening and source.available
        assert _wait(lambda: source.frame() is not None)
        capture = fake_capture.instances[0]
        assert capture.props[cv2.CAP_PROP_FOURCC] == cv2.VideoWriter_fourcc(*"MJPG")
    finally:
        source.close()
    assert fake_capture.instances[0].released


def test_webcam_failure_is_reported_through_the_callback(fake_capture):
    fake_capture.opened = False
    errors: list[str] = []
    source = webcam.WebcamSource(0, "Busy camera", cv2.CAP_DSHOW, on_error=errors.append)
    try:
        assert _wait(lambda: bool(errors))
        assert not source.available
        assert "Busy camera" in errors[0]
    finally:
        source.close()


def test_black_directshow_camera_retries_without_mjpg(fake_capture, monkeypatch):
    monkeypatch.setattr(webcam, "NO_FRAME_TIMEOUT", 0.1)
    fake_capture.frames = False
    errors: list[str] = []
    source = webcam.WebcamSource(0, "Black camera", cv2.CAP_DSHOW, on_error=errors.append)
    try:
        assert _wait(lambda: bool(errors))
        assert len(fake_capture.instances) == 2
        assert cv2.CAP_PROP_FOURCC not in fake_capture.instances[1].props
        assert "No picture" in errors[0]
    finally:
        source.close()


# ---------------------------------------------------------------- misc Windows


def test_mediapipe_hints():
    from websim.segmenter import mediapipe_hint

    assert "Visual C++" in mediapipe_hint(ImportError("DLL load failed while importing _framework_bindings"), "Windows")
    assert mediapipe_hint(ImportError("DLL load failed"), "Darwin") == ""


def test_pdf_opens_from_a_non_ascii_path(sample_pdf, tmp_path):
    from websim.sources.pdf import PdfSource

    target = tmp_path / "leçon é.pdf"
    target.write_bytes(sample_pdf.read_bytes())
    source = PdfSource(target)
    try:
        assert source.page_count == 2
    finally:
        source.close()


def test_doctor_survives_a_cp1252_console(monkeypatch):
    import io
    import sys

    from websim import app

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    assert app.main(["--doctor"]) == 0
    stream.flush()
    assert b"WebSim diagnostics" in raw.getvalue()


def test_banner_shows_the_specific_obs_error(app, tmp_path):
    from websim.config import SettingsStore
    from websim.ui.main_window import MainWindow

    store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(store, enable_audio=False)
    try:
        window.studio.sink.error = _friendly_error(
            RuntimeError("virtual camera output could not be started"), "Windows"
        )
        window._update_banner()
        assert "already in use" in window.banner.text()
    finally:
        window.studio.shutdown()
        window.close()
