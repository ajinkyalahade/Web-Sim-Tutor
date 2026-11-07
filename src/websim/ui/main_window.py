"""Main window: preview, panel, menus, shortcuts and drag & drop."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..config import SettingsStore
from ..studio import Studio
from .panel import ControlPanel
from .preview import PreviewWidget

log = logging.getLogger(__name__)

IN_APP_SHORTCUTS = {
    "Space": "play_pause",
    "S": "stop",
    "Left": "back",
    "Right": "forward",
    "Down": "slower",
    "Up": "faster",
    "L": "loop",
    "F": "freeze",
    "P": "overlay_cycle",
    "C": "webcam",
    "V": "media",
    "B": "blur",
    "Shift+B": "blur_cycle",
    "M": "mute_video",
    "N": "mute_mic",
    "PgUp": "page_prev",
    "PgDn": "page_next",
    "Escape": "clear_box",
}

SETUP_HTML = """
<h3>One-time setup</h3>
<p><b>1. Virtual camera (required).</b> Install <b>OBS Studio 30+</b>, open it once, click
<b>Start Virtual Camera</b>, then <b>Stop</b>, then quit OBS. You never need OBS running
again. In Zoom or a browser camera test, choose <b>OBS Virtual Camera</b>.</p>
<p><b>2. Virtual microphone (required for audio).</b> Mac: install <b>BlackHole 2ch</b>.
Windows: install <b>VB-Audio Virtual Cable</b>. In WebSim pick that device as the
<i>Virtual cable</b>; in Zoom / the browser pick <b>BlackHole 2ch</b> or <b>CABLE Output</b>
as the microphone.</p>
<p><b>3. Permissions.</b> Allow Camera and Microphone for Terminal (Mac). Global
shortcuts also need Accessibility. Restart WebSim after granting them.</p>
<p><b>4. Check it.</b> Use <i>File → Camera test pattern</i> and look at WebSim in Zoom's
camera preview. You should see moving colour bars and hear a 440 Hz tone in the
microphone meter.</p>
<p>Details and troubleshooting are in <b>README.md</b> in this folder.</p>
"""


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore, *, preview_only: bool = False, enable_audio: bool = True) -> None:
        super().__init__()
        self.store = store
        self.studio = Studio(store, preview_only=preview_only, enable_audio=enable_audio)
        self.shortcuts = None
        self._started = False
        self._closing = False
        self._was_maximized = False

        self.setWindowTitle("WebSim — camera studio")
        self.setMinimumSize(1080, 660)
        self.resize(store.settings.window_width, store.settings.window_height)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.preview = PreviewWidget()
        self.panel = ControlPanel(self.studio)

        self.banner = QLabel("")
        self.banner.setObjectName("Warning")
        self.banner.setWordWrap(True)
        self.banner_btn = QPushButton("Setup help")
        self.banner_btn.setObjectName("Chip")
        self.banner_btn.clicked.connect(self.show_setup)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(14, 8, 14, 8)
        banner_row.addWidget(self.banner, 1)
        banner_row.addWidget(self.banner_btn)
        banner_wrap = QWidget()
        banner_wrap.setLayout(banner_row)
        self.banner_wrap = banner_wrap
        self.banner_wrap.hide()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.preview)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.banner_wrap)
        column.addWidget(splitter, 1)
        layout.addLayout(column)
        self.setCentralWidget(root)

        self.status = QLabel("Starting…")
        self.status.setObjectName("Muted")
        self.fps = QLabel("—")
        self.fps.setObjectName("Muted")
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.fps)

        self._build_menu()
        self._wire()
        self._build_shortcuts()

    # ------------------------------------------------------------------ startup
    def start(self, *, test_pattern: bool = False, open_path: str | None = None) -> None:
        self._started = True
        self.studio.start(test_pattern=test_pattern)
        self.panel.refresh_devices()
        self._apply_always_on_top(self.store.settings.always_on_top)
        if self.store.settings.global_shortcuts:
            self.panel.global_shortcuts.blockSignals(True)
            self.panel.global_shortcuts.setChecked(True)
            self.panel.global_shortcuts.blockSignals(False)
            self._toggle_global_shortcuts(True)
        if open_path:
            self.open_file(open_path)
        else:
            self.studio.changed.emit()

    # --------------------------------------------------------------------- menu
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("Open lesson…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_file)
        file_menu.addAction(open_action)

        self.recent_menu = file_menu.addMenu("Recent")
        self._rebuild_recent()

        test_action = QAction("Camera test pattern (with tone)", self)
        test_action.triggered.connect(lambda: self.studio.open_test_pattern(tone=True))
        file_menu.addAction(test_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        # StandardKey.Quit is empty on Windows, so add Ctrl+Q explicitly there.
        quit_keys = QKeySequence.keyBindings(QKeySequence.StandardKey.Quit) or [QKeySequence("Ctrl+Q")]
        quit_action.setShortcuts(quit_keys)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        self.on_top_action = QAction("Always on top", self)
        self.on_top_action.setCheckable(True)
        self.on_top_action.setChecked(self.store.settings.always_on_top)
        self.on_top_action.toggled.connect(self._set_always_on_top)
        view_menu.addAction(self.on_top_action)
        full_action = QAction("Full screen preview", self)
        full_action.setShortcut("F11")
        full_action.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(full_action)

        help_menu = self.menuBar().addMenu("&Help")
        setup_action = QAction("Setup guide…", self)
        setup_action.triggered.connect(self.show_setup)
        help_menu.addAction(setup_action)
        doctor_action = QAction("Diagnostics…", self)
        doctor_action.triggered.connect(self.show_diagnostics)
        help_menu.addAction(doctor_action)

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        files = [p for p in self.store.settings.recent_files if Path(p).is_file()]
        if not files:
            empty = QAction("No recent files", self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for path in files[:8]:
            action = QAction(Path(path).name, self)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_file(p))
            self.recent_menu.addAction(action)

    # --------------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.panel.requestOpenFile.connect(self.choose_file)
        self.panel.requestAlwaysOnTop.connect(self._set_always_on_top)
        self.panel.requestGlobalShortcuts.connect(self._toggle_global_shortcuts)
        self.panel.requestSetupHelp.connect(self.show_setup)

        self.preview.boxDrawn.connect(self._box_drawn)
        self.preview.boxCleared.connect(self.studio.clear_blur_box)

        self.studio.preview.connect(self.preview.set_image)
        self.studio.changed.connect(self._sync_preview)
        self.studio.mediaChanged.connect(self._media_changed)
        self.studio.position.connect(self._position_changed)
        self.studio.status.connect(self._status_changed)
        self.studio.notice.connect(self._notice)
        self.studio.stats.connect(self._stats)

    def _build_shortcuts(self) -> None:
        self._shortcuts = []
        for keys, action in IN_APP_SHORTCUTS.items():
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda name=action: self.action(name))
            self._shortcuts.append(shortcut)

    # ------------------------------------------------------------------ actions
    def action(self, name: str) -> None:
        studio = self.studio
        if name == "play_pause":
            studio.play_pause()
        elif name == "stop":
            studio.stop()
        elif name == "back":
            studio.nudge(-10)
        elif name == "forward":
            studio.nudge(10)
        elif name == "slower":
            studio.change_speed(-0.25)
            self._flash_speed()
        elif name == "faster":
            studio.change_speed(0.25)
            self._flash_speed()
        elif name == "loop":
            studio.set_loop(not studio.settings.loop)
        elif name == "freeze":
            studio.toggle_freeze()
        elif name == "overlay_cycle":
            studio.cycle_overlay()
        elif name == "webcam":
            studio.set_mode("webcam")
        elif name == "media":
            studio.set_mode("media")
        elif name == "blur":
            studio.set_blur_enabled(not studio.blur_enabled)
        elif name == "blur_cycle":
            studio.cycle_blur_type()
        elif name == "mute_video":
            studio.toggle_source_mute()
        elif name == "mute_mic":
            studio.toggle_mic_mute()
        elif name == "page_prev":
            studio.previous_page()
        elif name == "page_next":
            studio.next_page()
        elif name == "clear_box":
            studio.clear_blur_box()
        elif name == "open":
            self.choose_file()
        self.panel.sync()

    def _flash_speed(self) -> None:
        self.statusBar().showMessage(f"Speed {self.studio.settings.speed:.2f}×", 1200)

    # ------------------------------------------------------------------- files
    def choose_file(self) -> None:
        from ..sources import FILTER

        start = self.store.settings.last_media_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open a lesson", start, FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        self._pending_open = path
        self.studio.open_file(path)
        self._rebuild_recent()
        self.panel.refresh_devices()

    # ---------------------------------------------------------------- callbacks
    def _box_drawn(self, box: list) -> None:
        self.studio.set_blur_box(box)
        self.studio.set_blur_enabled(True)
        self.statusBar().showMessage("Blur box set — drag again to replace, right-click to clear", 4000)
        self.panel.sync()

    def _sync_preview(self) -> None:
        self.preview.set_box(self.studio.blur_box if self.studio.blur_area == "box" else None)
        self._update_banner()
        self._status_changed(self.studio.status_text())
        self._update_title()

    def _update_banner(self) -> None:
        if self.studio.sink.active or self.studio.preview_only:
            self.banner_wrap.hide()
            return
        # sink.error already holds the specific, platform-aware fix.
        message = self.studio.sink.error or (
            "Virtual camera unavailable — preview only. Install OBS Studio 30+, open it once, "
            "start/stop its virtual camera, then click Retry."
        )
        self.banner.setText(message)
        self.banner_wrap.show()

    def _media_changed(self) -> None:
        self._update_title()
        self.preview.set_box(None)
        self._rebuild_recent()

    def _update_title(self) -> None:
        title = self.studio.media_title()
        self.setWindowTitle(f"WebSim — {title}" if title else "WebSim — camera studio")

    def _position_changed(self, position: float, duration: float) -> None:
        pass

    def _status_changed(self, text: str) -> None:
        self.status.setText(text)

    def _notice(self, message: str) -> None:
        self.statusBar().showMessage(message, 7000)

    def _stats(self, fps: float) -> None:
        self.fps.setText(f"{fps:4.1f} fps")

    # ------------------------------------------------------------------ window
    def _set_always_on_top(self, checked: bool) -> None:
        self.store.settings.always_on_top = bool(checked)
        self.store.save()
        if self.on_top_action.isChecked() != checked:
            self.on_top_action.setChecked(checked)
        self._apply_always_on_top(checked)
        self.panel.on_top.setChecked(checked)

    def _apply_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        if flags != self.windowFlags():
            self.setWindowFlags(flags)
            if self.isVisible():
                self.show()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_global_shortcuts(self, enabled: bool) -> None:
        self.store.settings.global_shortcuts = bool(enabled)
        self.store.save()
        if enabled:
            from ..shortcuts import GlobalShortcuts

            if self.shortcuts is None:
                self.shortcuts = GlobalShortcuts()
                self.shortcuts.triggered.connect(self.action, Qt.ConnectionType.QueuedConnection)
                self.shortcuts.failed.connect(self._shortcuts_failed)
            if not self.shortcuts.start():
                self.panel.global_shortcuts.setChecked(False)
        else:
            if self.shortcuts is not None:
                self.shortcuts.stop()

    def _shortcuts_failed(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        self.store.settings.global_shortcuts = False
        self.store.save()
        self.panel.global_shortcuts.setChecked(False)

    # -------------------------------------------------------------------- help
    def show_setup(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("WebSim setup")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(SETUP_HTML)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def show_diagnostics(self) -> None:
        from ..doctor import report

        box = QMessageBox(self)
        box.setWindowTitle("WebSim diagnostics")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(report())
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # ---------------------------------------------------------------- drag/drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802, ANN001
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())
                break
        event.acceptProposedAction()

    # ------------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._closing:
            event.accept()
            return
        self._closing = True
        self.store.settings.window_width = max(900, self.width())
        self.store.settings.window_height = max(600, self.height())
        self.store.settings.always_on_top = self.is_always_on_top()
        self.store.save()
        if self.shortcuts is not None:
            self.shortcuts.stop()
        try:
            self.studio.shutdown()
        except Exception as exc:  # noqa: BLE001
            log.warning("Shutdown error: %s", exc)
        event.accept()

    def is_always_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
