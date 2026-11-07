# Implementation status

Last verified: **7 November 2026** on macOS (Apple Silicon).

## What is done

| Area | Status | Notes |
|---|---|---|
| Dependencies / launcher | done | Python 3.12 via uv; `start.command` and `start.bat` install uv if missing, sync and launch. |
| Virtual camera output | done | 1280×720 @ 30 fps through pyvirtualcam and the OBS camera driver; preview-only fallback with a clear banner. |
| Video playback | done | PyAV decoding, accurate seek, variable speed with pitch-preserving audio, loop, stop. |
| PDF + images | done | Page navigation for PDFs; PNG/JPEG/WebP/BMP/TIFF images with alpha compositing. |
| Webcam | done | OpenCV capture with device enumeration; OBS camera filtered out so the app cannot feed into itself. |
| Background removal | done | MediaPipe selfie segmentation on a background thread (~3 ms per mask on the test Mac). |
| Presenter overlays | done | Cut-out, ghost, corner, freeze + restore. |
| Blur | done | Gaussian, pixelate, box, motion, frosted glass, blackout; whole-frame or feathered drawn box. |
| Audio | done | Video audio + real mic mixed to the virtual cable; separate volumes/mutes; optional headphone monitor (video only). |
| Shortcuts | done | Full in-app set plus pynput global shortcuts; macOS Accessibility is checked and failures are handled. |
| Diagnostics | done | `websim --doctor`, test pattern + tone, preview-only mode, verbose logging. |
| UI | done | Preview, control panel, drag & drop, recent files, always-on-top, setup help, warning banner. |

## Verification performed

- 67 headless tests pass (`uv run pytest`), including simulated Windows camera/audio/OBS cases.
- `ruff` clean; `uv lock --check` clean.
- Wheel and sdist build.
- Live MacBook camera: 720p composition at ~27–30 fps.
- MediaPipe: 640×360 mask in ~3 ms.
- Real microphone: 57,344 frames captured in 1.2 s.
- Video seek / loop / natural end / speed changes; audio pause and seek flush.
- UI render and headless startup (no exceptions).
- `--doctor` output checked on this machine.

## Windows review (7 November 2026)

Fixed after the first Windows report ("not working even after installing OBS"):

- OBS errors: WebSim now tells apart "driver not registered" and "already in use"
  (OBS or another WebSim running); both used to say "install OBS".
- Webcam: DirectShow only (no duplicate entries), MJPG for 720p30, opens off the
  UI thread, detects busy/black cameras; never falls back onto the OBS camera.
- Audio: one host API (WASAPI with auto-convert), never uses the VB-Cable as the
  default mic/headphones (feedback loop), truncated MME names still match.
- MediaPipe load failures are shown with the fix (VC++ runtime / non-ASCII path).
- PDFs from non-ASCII paths; `--doctor` no longer crashes on a cp1252 console.

Not yet verified on real Windows hardware — run the gate below on the Windows PC.

## Still needs hardware setup (not code)

1. Install **OBS Studio 30+**, open it once, Start Virtual Camera, Stop, quit.
2. Install **BlackHole 2ch** (macOS) or **VB-Audio Virtual Cable** (Windows).
3. Grant Camera, Microphone and (for global keys) Accessibility permissions.
4. Run the gate: test pattern + tone in a real Zoom call and a browser webcam site.
5. Run `start.bat` on the Windows test machine and repeat the gate there.

`uv run websim --doctor` reports exactly which of these is missing.

## Original design brief

See `plan.md` for the scope, decisions and build order agreed at the start.
