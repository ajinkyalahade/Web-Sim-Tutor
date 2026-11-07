"""Test fixtures. Everything (including temp files) stays inside the repo."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tests" / "_artifacts"
TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("WEBSIM_HOME", str(TMP / "home"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def sample_video() -> Path:
    import av

    path = TMP / "sample.mp4"
    if path.exists():
        return path
    container = av.open(str(path), "w")
    vstream = container.add_stream("libx264", rate=30)
    vstream.width, vstream.height, vstream.pix_fmt = 320, 180, "yuv420p"
    astream = container.add_stream("aac", rate=48000)
    astream.layout = "stereo"
    for i in range(90):
        arr = np.zeros((180, 320, 3), dtype=np.uint8)
        arr[:, :, 1] = 20 + i * 2
        arr[:20, :, :] = (0, 0, 200)
        frame = av.VideoFrame.from_ndarray(arr, format="bgr24")
        frame.pts = i
        for packet in vstream.encode(frame):
            container.mux(packet)
    for i in range(90):
        samples = np.zeros((2, 1024), dtype=np.float32)
        samples[0] = np.sin(np.arange(1024) * 2 * np.pi * 440 / 48000) * 0.2
        samples[1] = samples[0]
        frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="stereo")
        frame.sample_rate = 48000
        frame.pts = i * 1024
        for packet in astream.encode(frame):
            container.mux(packet)
    for packet in vstream.encode():
        container.mux(packet)
    for packet in astream.encode():
        container.mux(packet)
    container.close()
    return path


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    path = TMP / "sample.pdf"
    if path.exists():
        return path
    streams = []
    for label in (b"Page one", b"Page two"):
        streams.append(b"BT /F1 24 Tf 40 150 Td (" + label + b") Tj ET")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 5 0 R /Resources << /Font << /F1 7 0 R >> >> >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 6 0 R /Resources << /Font << /F1 7 0 R >> >> >>",
        b"<< /Length " + str(len(streams[0])).encode() + b" >> stream\n" + streams[0] + b"\nendstream",
        b"<< /Length " + str(len(streams[1])).encode() + b" >> stream\n" + streams[1] + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_at).encode()
        + b"\n%%EOF\n"
    )
    path.write_bytes(pdf)
    return path


@pytest.fixture(scope="session")
def sample_image() -> Path:
    import cv2

    path = TMP / "sample.png"
    if not path.exists():
        image = np.zeros((300, 400, 3), dtype=np.uint8)
        image[:, :] = (40, 80, 160)
        cv2.rectangle(image, (60, 60), (340, 240), (230, 220, 90), -1)
        cv2.imwrite(str(path), image)
    return path
