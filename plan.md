# WebSim — Plan

Virtual webcam studio for tutors. Python desktop app, Mac + Windows.

## End state
A tutor double-clicks `start.bat` (Windows) or `start.command` (Mac). WebSim opens and shows up as a **camera** and a **microphone** in any app or website that uses a webcam: Zoom, Meet, Teams, Omegle-style sites and other browser webcam sites. From a control panel (plus keyboard shortcuts) the tutor plays videos, PDFs and images into that camera. They control playback, blur and audio, freeze a frame, and put themselves on top of it to point at things.

**Done =** works in a real Zoom call *and* a browser webcam site, on this Mac and on the Windows test machine, launched only from the start script.

---

## Decisions made

| Topic | Decision |
|---|---|
| Name | WebSim (just a name; it's a desktop app, not websim.ai) |
| Platform | Python desktop app; output goes to a system-wide virtual camera, so every app and browser can see it |
| Where it works | Anything that can pick a webcam: Zoom, Meet, Teams, Omegle-style sites, browser webcam sites |
| Audio | Part of v1. Video sound + your real mic are mixed and sent to a virtual mic. Separate mute/unmute and volume for each |
| Pointing | **Decided: Cut-out mode** (your background is removed so you stand over the frozen frame, like a TV weather presenter). Ghost (see-through webcam) and Corner (picture-in-picture) are available as fallbacks for slow machines |
| Files | All video formats ffmpeg reads (mp4, mov, mkv, avi, webm, wmv, flv, m4v…) + **PDFs** + images (png, jpg, webp, bmp…) — see assumption below |
| Blur | Several types, with a strength slider, on the whole frame or a box you draw |
| Controls | All of them, easy to reach: on-screen panel + in-app shortcuts + global shortcuts (work while Zoom or the browser is focused) + an "always on top" toggle |
| Dependencies | `uv` (pyproject.toml, Python 3.12 pinned) |
| Launch | `start.bat` (Windows) and `start.command` (Mac, double-clickable). Each one installs uv if it's missing, syncs dependencies, then runs the app |
| Testing | This Mac + your Windows machine |

### Assumption to confirm
- **"All types of PD files"**: I read this as *video files* and *PDFs*, and I'm doing both, since PDF support is cheap (render a page and show it like a still frame). Tell me if you meant something else.

---

## Blunt flags

1. **Scope grew.** Audio, global shortcuts, cut-out mode, multiple blur types and PDFs all moved into v1. That's fine, but v1 is now roughly 2× what I first proposed. The order below puts the risky parts first so a failure shows up early, not at the end.
2. **OBS must be installed (camera).** Python can't create a webcam by itself. `pyvirtualcam` uses the virtual camera that OBS installs. On Mac, one-time setup: install OBS 30+, click *Start Virtual Camera*, then *Stop*, then quit OBS. After that OBS never needs to run. In call apps the camera will be named **"OBS Virtual Camera"**. We can't rename it without writing our own driver (Swift, Apple signing, weeks of work).
3. **A virtual audio device must be installed (mic).** Same reason: Python can't create a microphone. Mac: **BlackHole 2ch** (free). Windows: **VB-Audio Virtual Cable** (free). In the call app you select *BlackHole* or *CABLE Output* as your mic. WebSim passes your real mic through it, so **WebSim must be running or students hear nothing**.
4. **Neither is installed on this Mac yet.** I checked: no OBS, no BlackHole. You'll need to install both (they need admin rights plus a system extension approval). Until then the app can run with a preview only.
5. **Mac permissions.** The first run asks for Camera and Microphone permission for Terminal. Global shortcuts also need *Accessibility* permission. The Mac shortcut library (`pynput`) has a history of crashes on newer macOS, so global shortcuts will be a toggle, and if they misbehave they fail safely without taking the app down.
6. **The start scripts need internet on first run** (to install uv, Python 3.12 and the dependencies, about 300 MB, mostly Qt and MediaPipe). Later runs start fast.

---

## Architecture

| Part | Library |
|---|---|
| UI | PySide6 (Qt): preview window + control panel |
| Video + audio decode | PyAV (ffmpeg): accurate seeking, all formats, keeps pitch when you change speed |
| PDF | pypdfium2 (permissive licence, unlike PyMuPDF's AGPL) |
| Webcam capture | OpenCV + `cv2-enumerate-cameras` (real camera names; automatically hides "OBS Virtual Camera" so it can't feed into itself) |
| Background removal | MediaPipe person segmentation |
| Output camera | pyvirtualcam, 1280×720 @ 30fps |
| Audio in/out | sounddevice: mic in, mixed output to the virtual cable, optional output to your own headphones |
| Global shortcuts | pynput |

**One mixing loop at 30fps:** pick the base frame (video / PDF page / image / webcam) → apply blur → overlay you (cut-out / ghost / corner) → send to the virtual camera and the preview.

**Audio:** the video's sound is decoded in its own thread and kept in sync with the video clock (pause, seek and speed all follow it). The mixer combines video audio (volume + mute) and mic (volume + mute) and sends that to the virtual cable. An optional "hear video myself" output goes to your headphones.

### Modes
- **Webcam**: your real camera, optionally with your background blurred.
- **Media**: a video, PDF or image is playing or showing.
- **Me on top**: overlays you on whatever media is showing. Freeze = pause + Me on top, on one key.

### Controls
| Action | Panel | Shortcut (in app) | Global shortcut |
|---|---|---|---|
| Play / pause | ✔ | Space | Ctrl+Alt+Space |
| Stop (back to start, paused) | ✔ | S | Ctrl+Alt+S |
| Back / forward 10s | ✔ | ← / → | Ctrl+Alt+← / → |
| Speed 0.25× – 3× | ✔ | ↓ / ↑ | Ctrl+Alt+↓ / ↑ |
| Seek bar | ✔ | | |
| Loop | ✔ | L | |
| Freeze + Me on top | ✔ | F | Ctrl+Alt+F |
| Pointing style (cut-out / ghost / corner) | ✔ | P | |
| Switch to webcam / media | ✔ | C / V | Ctrl+Alt+C / V |
| Blur on/off, change blur type | ✔ | B / Shift+B | Ctrl+Alt+B |
| Draw a blur box | drag on preview | | |
| Mute video audio | ✔ | M | Ctrl+Alt+M |
| Mute mic | ✔ | N | Ctrl+Alt+N |
| PDF previous / next page | ✔ | PgUp / PgDn | Ctrl+Alt+PgUp / PgDn |
| Always on top | ✔ | | |

(On Mac, Ctrl+Alt is Ctrl+Option.)

### Blur types
Gaussian (soft), Pixelate (mosaic), Box (fast), Motion (streaky), Frosted glass, Blackout (solid cover, for hiding answers). All apply to the whole frame or to a drawn box, with a strength slider.

---

## Build order (checkpoint with you after each one)

1. **Gate (riskiest first):** a test pattern + test tone reach Zoom and a browser webcam site, on Mac and Windows. Needs OBS + BlackHole / VB-Cable installed. If this fails, the plan changes.
2. **Core:** Qt window, webcam passthrough, video playback with every control, output to the virtual camera.
3. **Audio:** video sound in sync, mic passthrough, both mutes and volumes, headphone monitor.
4. **Pointing + blur:** cut-out / ghost / corner, freeze, all blur types, drawn blur box.
5. **Files + shortcuts:** PDFs, images, in-app and global shortcuts, always on top.
6. **Launch:** `start.bat` + `start.command` tested on a clean machine, plus a short README covering the OBS and virtual audio setup.

### Not in v1
Drawing / annotations, playlists, YouTube links, green screen, recording, our own branded camera driver.

---

## Already in the folder
I started setting up before you paused me:
- `pyproject.toml`, `.python-version` (3.12), `src/websim/__init__.py`
- `.venv/` with the dependencies installed via `uv sync` (`uv.lock` written)

No app code yet. Delete these if you want a clean slate; otherwise they get reused.
