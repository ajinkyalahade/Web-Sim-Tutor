"""Right-hand control panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..audio import NO_OUTPUT
from ..blur import BLUR_LABELS
from ..studio import Studio
from .style import MUTED


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def _small(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Small")
    return label


def _slider(minimum: int, maximum: int, value: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return slider


OVERLAY_LABELS = [
    ("off", "Off"),
    ("cutout", "Cut-out (weather presenter)"),
    ("ghost", "Ghost (see-through)"),
    ("corner", "Corner (picture-in-picture)"),
]


class ControlPanel(QWidget):
    requestOpenFile = Signal()
    requestAlwaysOnTop = Signal(bool)
    requestGlobalShortcuts = Signal(bool)
    requestSetupHelp = Signal()

    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self._syncing = False
        self._seeking = False
        self.setObjectName("Panel")
        self.setFixedWidth(380)
        self._build()
        self._wire()
        self.refresh_devices()
        self.sync()
        self._tick()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(16, 14, 16, 18)
        self._layout.setSpacing(12)

        header = QLabel("WebSim")
        header.setObjectName("Heading")
        header_row = QHBoxLayout()
        header_row.addWidget(header)
        header_row.addStretch(1)
        self.badge = QLabel("STUDIO")
        self.badge.setObjectName("Badge")
        header_row.addWidget(self.badge)
        self._layout.addLayout(header_row)

        # ------------------------------------------------------------ source
        source = QGroupBox("SOURCE")
        source_layout = QVBoxLayout(source)
        self.open_btn = QPushButton("Open video, PDF or image…")
        self.open_btn.setObjectName("Primary")
        source_layout.addWidget(self.open_btn)
        self.file_label = _small("No lesson loaded")
        self.file_label.setWordWrap(False)
        source_layout.addWidget(self.file_label)

        mode_row = QHBoxLayout()
        self.webcam_btn = QPushButton("Webcam")
        self.webcam_btn.setCheckable(True)
        self.media_btn = QPushButton("Media")
        self.media_btn.setCheckable(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.webcam_btn)
        group.addButton(self.media_btn)
        mode_row.addWidget(self.webcam_btn)
        mode_row.addWidget(self.media_btn)
        source_layout.addLayout(mode_row)

        page_row = QHBoxLayout()
        self.prev_page_btn = QPushButton("Previous page")
        self.next_page_btn = QPushButton("Next page")
        self.page_label = _small("")
        page_row.addWidget(self.prev_page_btn)
        page_row.addWidget(self.next_page_btn)
        page_row.addWidget(self.page_label)
        page_row.addStretch(1)
        source_layout.addLayout(page_row)
        self._page_row = page_row
        self._layout.addWidget(source)

        # --------------------------------------------------------- transport
        transport = QGroupBox("PLAYBACK")
        t = QVBoxLayout(transport)
        row = QHBoxLayout()
        self.back_btn = QPushButton("−10s")
        self.play_btn = QPushButton("Play")
        self.forward_btn = QPushButton("+10s")
        self.stop_btn = QPushButton("Stop")
        self.freeze_btn = QPushButton("Freeze")
        for button in (self.back_btn, self.play_btn, self.forward_btn, self.stop_btn, self.freeze_btn):
            row.addWidget(button)
        t.addLayout(row)

        seek_row = QHBoxLayout()
        self.seek = _slider(0, 1000, 0)
        self.time_label = _small("0:00 / 0:00")
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.time_label)
        t.addLayout(seek_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed"))
        self.speed = _slider(25, 300, 100)
        self.speed.setSingleStep(5)
        self.speed_label = _small("1.00×")
        speed_row.addWidget(self.speed, 1)
        speed_row.addWidget(self.speed_label)
        t.addLayout(speed_row)

        self.loop_check = QCheckBox("Loop")
        t.addLayout(self._loop_row())
        self._layout.addWidget(transport)

        # ----------------------------------------------------------- pointing
        pointing = QGroupBox("ME ON TOP")
        p = QVBoxLayout(pointing)
        self.overlay = QComboBox()
        for key, label in OVERLAY_LABELS:
            self.overlay.addItem(label, key)
        p.addWidget(self.overlay)
        self.bg_blur = QCheckBox("Blur my background (webcam mode)")
        p.addWidget(self.bg_blur)
        p.addWidget(_muted("Cut-out removes your background so you stand on the slide. Ghost is softer; Corner is the fastest."))
        self._layout.addWidget(pointing)

        # -------------------------------------------------------------- blur
        blur = QGroupBox("BLUR / HIDE")
        b = QGridLayout(blur)
        b.setHorizontalSpacing(8)
        self.blur_check = QCheckBox("Blur on")
        b.addWidget(self.blur_check, 0, 0, 1, 2)
        b.addWidget(QLabel("Style"), 1, 0)
        self.blur_type = QComboBox()
        for key, label in BLUR_LABELS:
            self.blur_type.addItem(label, key)
        b.addWidget(self.blur_type, 1, 1)
        b.addWidget(QLabel("Strength"), 2, 0)
        self.blur_strength = _slider(0, 100, 45)
        b.addWidget(self.blur_strength, 2, 1)
        b.addWidget(QLabel("Area"), 3, 0)
        self.blur_area = QComboBox()
        self.blur_area.addItem("Whole frame", "whole")
        self.blur_area.addItem("Drawn box", "box")
        b.addWidget(self.blur_area, 3, 1)
        self.clear_box_btn = QPushButton("Clear drawn box")
        b.addWidget(self.clear_box_btn, 4, 0, 1, 2)
        b.addWidget(_muted("Tip: drag a rectangle on the preview to hide just that part."), 5, 0, 1, 2)

        # ------------------------------------------------------------- audio
        audio = QGroupBox("AUDIO")
        a = QGridLayout(audio)
        a.setHorizontalSpacing(8)
        self.source_mute = QPushButton("Mute video")
        self.source_mute.setCheckable(True)
        a.addWidget(self.source_mute, 0, 0)
        self.source_volume = _slider(0, 100, 80)
        a.addWidget(self.source_volume, 0, 1)
        self.source_vol_label = _small("80%")
        a.addWidget(self.source_vol_label, 0, 2)

        self.mic_mute = QPushButton("Mute mic")
        self.mic_mute.setCheckable(True)
        a.addWidget(self.mic_mute, 1, 0)
        self.mic_volume = _slider(0, 100, 100)
        a.addWidget(self.mic_volume, 1, 1)
        self.mic_vol_label = _small("100%")
        a.addWidget(self.mic_vol_label, 1, 2)

        self.monitor_check = QCheckBox("Hear video in my headphones")
        a.addWidget(self.monitor_check, 2, 0, 1, 3)

        a.addWidget(QLabel("Mic"), 3, 0)
        self.mic_combo = QComboBox()
        a.addWidget(self.mic_combo, 3, 1, 1, 2)
        a.addWidget(QLabel("Virtual cable"), 4, 0)
        self.output_combo = QComboBox()
        a.addWidget(self.output_combo, 4, 1, 1, 2)
        a.addWidget(QLabel("Headphones"), 5, 0)
        self.monitor_combo = QComboBox()
        a.addWidget(self.monitor_combo, 5, 1, 1, 2)
        self.refresh_audio_btn = QPushButton("Refresh audio devices")
        a.addWidget(self.refresh_audio_btn, 6, 0, 1, 3)
        self.audio_note = _small("")
        self.audio_note.setWordWrap(True)
        a.addWidget(self.audio_note, 7, 0, 1, 3)
        self._layout.addWidget(audio)
        self._layout.addWidget(blur)

        # ------------------------------------------------------------ output
        output = QGroupBox("OUTPUT")
        o = QVBoxLayout(output)
        self.warning = QLabel("")
        self.warning.setObjectName("Warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        o.addWidget(self.warning)
        self.output_status = _small("")
        self.output_status.setWordWrap(True)
        o.addWidget(self.output_status)
        status_row = QHBoxLayout()
        self.retry_btn = QPushButton("Retry virtual camera")
        self.setup_btn = QPushButton("Setup help")
        status_row.addWidget(self.retry_btn)
        status_row.addWidget(self.setup_btn)
        o.addLayout(status_row)

        o.addWidget(QLabel("Camera"))
        self.camera_combo = QComboBox()
        o.addWidget(self.camera_combo)
        self.refresh_cameras_btn = QPushButton("Refresh cameras")
        o.addWidget(self.refresh_cameras_btn)
        self.on_top = QCheckBox("Always on top")
        o.addWidget(self.on_top)
        self.global_shortcuts = QCheckBox("Global shortcuts (work inside Zoom)")
        o.addWidget(self.global_shortcuts)
        self._layout.addWidget(output)

        self._layout.addStretch(1)
        footer = _small("Right-click the preview to clear a blur box.")
        self._layout.addWidget(footer)
        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _loop_row(self):
        row = QHBoxLayout()
        row.addWidget(self.loop_check)
        row.addStretch(1)
        hint = _small("Space play/pause  •  F freeze")
        row.addWidget(hint)
        return row

    # -------------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.open_btn.clicked.connect(self.requestOpenFile.emit)
        self.webcam_btn.clicked.connect(lambda: self.studio.set_mode("webcam"))
        self.media_btn.clicked.connect(lambda: self.studio.set_mode("media"))
        self.back_btn.clicked.connect(lambda: self.studio.nudge(-10))
        self.forward_btn.clicked.connect(lambda: self.studio.nudge(10))
        self.play_btn.clicked.connect(self.studio.play_pause)
        self.stop_btn.clicked.connect(self.studio.stop)
        self.freeze_btn.clicked.connect(self.studio.toggle_freeze)
        self.prev_page_btn.clicked.connect(self.studio.previous_page)
        self.next_page_btn.clicked.connect(self.studio.next_page)
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._seek_dragged)
        self.speed.valueChanged.connect(self._speed_changed)
        self.loop_check.toggled.connect(self._loop_changed)

        self.overlay.currentIndexChanged.connect(self._overlay_changed)
        self.bg_blur.toggled.connect(self._bg_blur_changed)
        self.blur_check.toggled.connect(self._blur_toggled)
        self.blur_type.currentIndexChanged.connect(self._blur_type_changed)
        self.blur_strength.valueChanged.connect(self._blur_strength_changed)
        self.blur_area.currentIndexChanged.connect(self._blur_area_changed)
        self.clear_box_btn.clicked.connect(self.studio.clear_blur_box)

        self.source_volume.valueChanged.connect(self._source_volume_changed)
        self.mic_volume.valueChanged.connect(self._mic_volume_changed)
        self.source_mute.toggled.connect(self._source_mute_changed)
        self.mic_mute.toggled.connect(self._mic_mute_changed)
        self.monitor_check.toggled.connect(self._monitor_changed)
        self.mic_combo.currentIndexChanged.connect(self._mic_device_changed)
        self.output_combo.currentIndexChanged.connect(self._output_device_changed)
        self.monitor_combo.currentIndexChanged.connect(self._monitor_device_changed)
        self.refresh_audio_btn.clicked.connect(self.refresh_devices)
        self.refresh_cameras_btn.clicked.connect(self.refresh_cameras)
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        self.retry_btn.clicked.connect(self.studio.retry_output)
        self.setup_btn.clicked.connect(self.requestSetupHelp.emit)
        self.on_top.toggled.connect(self._on_top_changed)
        self.global_shortcuts.toggled.connect(self._global_changed)

        self.studio.changed.connect(self.sync)
        self.studio.mediaChanged.connect(self.sync)
        self.studio.status.connect(self._status_changed)

    # ----------------------------------------------------------------- devices
    def refresh_devices(self) -> None:
        self._syncing = True
        try:
            self._fill_audio_devices()
            self.refresh_cameras()
        finally:
            self._syncing = False
        self.sync()

    def refresh_cameras(self) -> None:
        was = self._syncing
        self._syncing = True
        try:
            current = self.studio.camera_name() or self.studio.settings.camera_name
            self.camera_combo.clear()
            devices = self.studio.cameras()
            for device in devices:
                self.camera_combo.addItem(device.name, device)
            if devices:
                index = 0
                for i, device in enumerate(devices):
                    if device.name == current:
                        index = i
                        break
                self.camera_combo.setCurrentIndex(index)
        finally:
            self._syncing = was

    def _fill_audio_devices(self) -> None:
        devices = self.studio.audio_devices()
        inputs = [d for d in devices if d.inputs > 0]
        outputs = [d for d in devices if d.outputs > 0]
        virtual = [d for d in outputs if d.is_virtual_output]
        others = [d for d in outputs if not d.is_virtual_output]

        self.mic_combo.clear()
        self.mic_combo.addItem("System default microphone", "")
        for d in inputs:
            self.mic_combo.addItem(d.name, d.name)

        self.output_combo.clear()
        self.output_combo.addItem("None (preview only)", NO_OUTPUT)
        if virtual:
            for d in virtual:
                self.output_combo.addItem(d.name + "  (virtual)", d.name)
        for d in others:
            self.output_combo.addItem(d.name, d.name)

        self.monitor_combo.clear()
        self.monitor_combo.addItem("System default headphones", "")
        for d in others:
            self.monitor_combo.addItem(d.name, d.name)

        self._select_by_data(self.mic_combo, self.studio.engine.devices.get("mic") or self.studio.settings.mic_name)
        self.output_combo.setCurrentIndex(0)
        wanted_output = self.studio.engine.devices.get("output") or self.studio.settings.output_name
        self._select_by_data(self.output_combo, wanted_output)
        self._select_by_data(self.monitor_combo, self.studio.engine.devices.get("monitor") or self.studio.settings.monitor_name)

        if not virtual:
            self.audio_note.setText(
                "No virtual audio device found. Install BlackHole 2ch (Mac) or VB-Cable (Windows) so the app can send audio and your mic to students."
            )
            self.audio_note.setStyleSheet("color: #ffd79b;")
        else:
            virtual_names = {d.name for d in devices if d.is_virtual_output}
            chosen_mic = self.mic_combo.currentData() or self.studio.engine.devices.get("mic") or ""
            if chosen_mic in virtual_names:
                self.audio_note.setText(
                    "You selected a virtual cable as the microphone — that feeds silence. Pick your real microphone."
                )
                self.audio_note.setStyleSheet("color: #ffd79b;")
            else:
                self.audio_note.setText("Students pick this device as their microphone in Zoom / the browser.")
                self.audio_note.setStyleSheet("")

    def _select_by_data(self, combo: QComboBox, value: str) -> None:
        if not value:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data == value:
                combo.setCurrentIndex(i)
                return

    # ---------------------------------------------------------------- handlers
    def _seek_pressed(self) -> None:
        self._seeking = True

    def _seek_dragged(self, value: int) -> None:
        self.time_label.setText(f"{_clock(value / 1000)} / {_clock(self.seek.maximum() / 1000)}")

    def _seek_released(self) -> None:
        self._seeking = False
        self.studio.seek(self.seek.value() / 1000)

    def _speed_changed(self, value: int) -> None:
        speed = value / 100
        self.speed_label.setText(f"{speed:.2f}×")
        if not self._syncing:
            self.studio.set_speed(speed)

    def _loop_changed(self, checked: bool) -> None:
        if not self._syncing:
            self.studio.set_loop(checked)

    def _overlay_changed(self, index: int) -> None:
        if self._syncing:
            return
        self.studio.set_overlay(self.overlay.itemData(index))

    def _bg_blur_changed(self, checked: bool) -> None:
        if not self._syncing:
            self.studio.set_webcam_bg_blur(checked)

    def _blur_toggled(self, checked: bool) -> None:
        if not self._syncing:
            self.studio.set_blur_enabled(checked)

    def _blur_type_changed(self, index: int) -> None:
        if not self._syncing:
            self.studio.set_blur_type(self.blur_type.itemData(index))

    def _blur_strength_changed(self, value: int) -> None:
        if not self._syncing:
            self.studio.set_blur_strength(value)

    def _blur_area_changed(self, index: int) -> None:
        if not self._syncing:
            self.studio.set_blur_area(self.blur_area.itemData(index))
            if self.blur_area.itemData(index) == "box" and self.studio.blur_box is None:
                self.studio.notice.emit("Drag a rectangle on the preview to choose the area.")

    def _source_volume_changed(self, value: int) -> None:
        self.source_vol_label.setText(f"{value}%")
        if not self._syncing:
            self.studio.set_source_volume(value)

    def _mic_volume_changed(self, value: int) -> None:
        self.mic_vol_label.setText(f"{value}%")
        if not self._syncing:
            self.studio.set_mic_volume(value)

    def _source_mute_changed(self, checked: bool) -> None:
        if self._syncing:
            return
        if checked != self.studio.settings.source_muted:
            self.studio.toggle_source_mute()

    def _mic_mute_changed(self, checked: bool) -> None:
        if self._syncing:
            return
        if checked != self.studio.settings.mic_muted:
            self.studio.toggle_mic_mute()

    def _monitor_changed(self, checked: bool) -> None:
        if not self._syncing:
            self.studio.set_monitor(checked)

    def _mic_device_changed(self, index: int) -> None:
        if self._syncing:
            return
        self.studio.set_mic_device(self.mic_combo.itemData(index) or "")

    def _output_device_changed(self, index: int) -> None:
        if self._syncing:
            return
        self.studio.set_output_device(self.output_combo.itemData(index) or "")

    def _monitor_device_changed(self, index: int) -> None:
        if self._syncing:
            return
        self.studio.set_monitor_device(self.monitor_combo.itemData(index) or "")

    def _camera_changed(self, index: int) -> None:
        if self._syncing:
            return
        device = self.camera_combo.itemData(index)
        if device is not None:
            self.studio.set_camera(device)

    def _on_top_changed(self, checked: bool) -> None:
        if not self._syncing:
            self.requestAlwaysOnTop.emit(checked)

    def _global_changed(self, checked: bool) -> None:
        if not self._syncing:
            self.requestGlobalShortcuts.emit(checked)

    def _status_changed(self, text: str) -> None:
        self.output_status.setText(text)

    # -------------------------------------------------------------------- sync
    def sync(self) -> None:
        self._syncing = True
        try:
            studio = self.studio
            self.webcam_btn.setChecked(studio.mode == "webcam")
            self.media_btn.setChecked(studio.mode == "media")

            title = studio.media_title()
            self.file_label.setText(title or "No lesson loaded")
            self.file_label.setToolTip(title)
            self.file_label.setStyleSheet("" if title else f"color: {MUTED};")

            index = self.overlay.findData(studio.overlay_style)
            if index >= 0:
                self.overlay.setCurrentIndex(index)
            self.bg_blur.setChecked(studio.webcam_bg_blur)

            self.blur_check.setChecked(studio.blur_enabled)
            index = self.blur_type.findData(studio.blur_type)
            if index >= 0:
                self.blur_type.setCurrentIndex(index)
            self.blur_strength.setValue(studio.blur_strength)
            index = self.blur_area.findData(studio.blur_area)
            if index >= 0:
                self.blur_area.setCurrentIndex(index)

            self.speed.setValue(int(round(studio.settings.speed * 100)))
            self.speed_label.setText(f"{studio.settings.speed:.2f}×")
            self.loop_check.setChecked(studio.settings.loop)

            self.source_volume.setValue(studio.settings.source_volume)
            self.mic_volume.setValue(studio.settings.mic_volume)
            self.source_vol_label.setText(f"{studio.settings.source_volume}%")
            self.mic_vol_label.setText(f"{studio.settings.mic_volume}%")
            self.source_mute.setChecked(studio.settings.source_muted)
            self.source_mute.setText("Video muted" if studio.settings.source_muted else "Mute video")
            self.mic_mute.setChecked(studio.settings.mic_muted)
            self.mic_mute.setText("Mic muted" if studio.settings.mic_muted else "Mute mic")
            self.monitor_check.setChecked(studio.engine.monitor_enabled or studio.settings.monitor_enabled)
            self._select_by_data(self.mic_combo, studio.engine.devices.get("mic") or studio.settings.mic_name)
            self._select_by_data(self.output_combo, studio.engine.devices.get("output") or studio.settings.output_name)
            self._select_by_data(self.monitor_combo, studio.engine.devices.get("monitor") or studio.settings.monitor_name)
            self.on_top.setChecked(studio.settings.always_on_top)
            self.global_shortcuts.setChecked(studio.settings.global_shortcuts)

            page, count = studio.page_info()
            has_pages = count > 0
            self.prev_page_btn.setVisible(has_pages)
            self.next_page_btn.setVisible(has_pages)
            self.page_label.setVisible(has_pages)
            if has_pages:
                self.page_label.setText(f"Page {page + 1} / {count}")
                self.prev_page_btn.setEnabled(page > 0)
                self.next_page_btn.setEnabled(page < count - 1)

            self._update_warning()
            self._update_media_buttons()
            self._tick()
        finally:
            self._syncing = False

    def _update_warning(self) -> None:
        studio = self.studio
        if studio.sink.active:
            self.warning.hide()
            self.output_status.setText(studio.sink.status)
            return
        if studio.preview_only:
            message = "Preview only (started with --preview-only). Nothing is being sent to a camera."
        else:
            message = studio.sink.error or "Virtual camera is not available."
        self.warning.setText(message)
        self.warning.show()
        self.output_status.setText(studio.sink.status)
        if studio.engine.status:
            self.audio_note.setToolTip(studio.engine.status)

    def _update_media_buttons(self) -> None:
        media = self.studio.media
        transport = bool(media is not None and media.has_transport)
        for button in (self.play_btn, self.back_btn, self.forward_btn, self.stop_btn, self.seek):
            button.setEnabled(transport)
        self.freeze_btn.setEnabled(transport)
        self.play_btn.setText("Pause" if self.studio.playing() else "Play")
        self.freeze_btn.setText("Unfreeze" if self.studio.frozen else "Freeze")
        pdf = bool(media is not None and media.kind == "pdf")
        self.prev_page_btn.setEnabled(pdf and media.page_index > 0)
        self.next_page_btn.setEnabled(pdf and media.page_index < media.page_count - 1)

    def _tick(self) -> None:
        position, duration = self.studio.media_position()
        if duration > 0 and not self._seeking:
            self.seek.blockSignals(True)
            self.seek.setMaximum(int(duration * 1000))
            self.seek.setValue(int(max(0, min(position, duration)) * 1000))
            self.seek.blockSignals(False)
            self.time_label.setText(f"{_clock(position)} / {_clock(duration)}")
        elif duration <= 0 and not self._seeking:
            self.time_label.setText("0:00 / 0:00")
        if not self._syncing:
            self.play_btn.setText("Play" if not self.studio.playing() else "Pause")
            self.freeze_btn.setText("Unfreeze" if self.studio.frozen else "Freeze")


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
