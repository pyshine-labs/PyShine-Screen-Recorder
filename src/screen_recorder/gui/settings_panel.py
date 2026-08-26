"""Settings dialog with tabbed interface for the Screen Recorder application.

Provides :class:`SettingsDialog` which allows the user to configure video,
audio, and general application settings.  Changes are persisted via
:class:`~screen_recorder.config.settings_manager.SettingsManager`.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..app import RecordingState
from ..audio.device_enumerator import AudioDeviceEnumerator
from ..config.settings_manager import AppSettings, SettingsManager
from ..utils.logger import logger


class SettingsDialog(QDialog):
    """Tabbed settings dialog for the Screen Recorder.

    Signals:
        settings_changed: Emitted when settings are saved (OK or Apply).
    """

    settings_changed = pyqtSignal()

    def __init__(self, settings_manager: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._audio_enumerator = AudioDeviceEnumerator()

        self.setWindowTitle("Settings")
        self.setMinimumSize(460, 400)
        self._setup_ui()
        self._load_settings()
        logger.debug("SettingsDialog initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the tabbed settings dialog."""
        layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._create_video_tab(), "Video")
        self._tab_widget.addTab(self._create_audio_tab(), "Audio")
        self._tab_widget.addTab(self._create_general_tab(), "General")
        layout.addWidget(self._tab_widget)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self._reset_button = QPushButton("Reset Defaults")
        self._reset_button.setToolTip("Restore all settings to their default values")
        self._button_box.addButton(self._reset_button, QDialogButtonBox.ButtonRole.ResetRole)

        layout.addWidget(self._button_box)

        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)
        self._button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        self._reset_button.clicked.connect(self._on_reset_defaults)

    # ── Video tab ────────────────────────────────────────────────────────────

    def _create_video_tab(self) -> QWidget:
        """Create the Video settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Recording info
        info_group = QGroupBox("Recording")
        info_layout = QVBoxLayout(info_group)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frame Rate:"))
        self._fps_combo = QComboBox()
        self._fps_combo.addItems(["30 fps (Smooth)", "24 fps (Cinema)"])
        fps_row.addWidget(self._fps_combo)
        fps_row.addStretch()
        info_layout.addLayout(fps_row)

        # Video bitrate option
        bitrate_row = QHBoxLayout()
        bitrate_row.addWidget(QLabel("Bitrate:"))
        self._bitrate_combo = QComboBox()
        self._bitrate_combo.addItems([
            "Near-Lossless (CRF 1 — best playable)",
            "2 Mbps (Low)",
            "4 Mbps (Medium)",
            "8 Mbps (High)",
            "12 Mbps (Very High)",
            "20 Mbps (Ultra)",
        ])
        bitrate_row.addWidget(self._bitrate_combo)
        bitrate_row.addStretch()
        info_layout.addLayout(bitrate_row)

        encoder_note = QLabel(
            "Encoder: GPU capture (DXGI) + x264\n"
            "Quality: Near-lossless (CRF 1, 720p) — universally playable"
        )
        encoder_note.setStyleSheet("color: gray; font-size: 11px;")
        encoder_note.setWordWrap(True)
        info_layout.addWidget(encoder_note)

        layout.addWidget(info_group)
        layout.addStretch()
        return widget

    # ── Audio tab ────────────────────────────────────────────────────────────

    def _create_audio_tab(self) -> QWidget:
        """Create the Audio settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Microphone
        mic_group = QGroupBox("Microphone")
        mic_layout = QVBoxLayout(mic_group)

        self._mic_enabled_check = QCheckBox("Enable Microphone")
        self._mic_enabled_check.setChecked(True)
        mic_layout.addWidget(self._mic_enabled_check)

        mic_device_row = QHBoxLayout()
        mic_device_row.addWidget(QLabel("Device:"))
        self._mic_device_combo = QComboBox()
        mic_device_row.addWidget(self._mic_device_combo)
        mic_layout.addLayout(mic_device_row)

        layout.addWidget(mic_group)

        # System audio
        sys_group = QGroupBox("System Audio")
        sys_layout = QVBoxLayout(sys_group)

        self._sys_audio_enabled_check = QCheckBox("Enable System Audio (capture what you hear)")
        self._sys_audio_enabled_check.setChecked(False)
        sys_layout.addWidget(self._sys_audio_enabled_check)

        sys_note = QLabel("When microphone is off, system audio is automatically enabled.")
        sys_note.setStyleSheet("color: gray; font-size: 11px;")
        sys_note.setWordWrap(True)
        sys_layout.addWidget(sys_note)

        layout.addWidget(sys_group)

        # Format
        format_group = QGroupBox("Format")
        format_layout = QVBoxLayout(format_group)

        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("Sample Rate:"))
        self._sample_rate_combo = QComboBox()
        self._sample_rate_combo.addItems(["48000 Hz (Recommended)", "44100 Hz (CD Quality)"])
        sample_row.addWidget(self._sample_rate_combo)
        sample_row.addStretch()
        format_layout.addLayout(sample_row)

        channels_row = QHBoxLayout()
        channels_row.addWidget(QLabel("Channels:"))
        self._channels_combo = QComboBox()
        self._channels_combo.addItems(["Stereo", "Mono"])
        channels_row.addWidget(self._channels_combo)
        channels_row.addStretch()
        format_layout.addLayout(channels_row)

        layout.addWidget(format_group)
        layout.addStretch()

        self._populate_audio_devices()

        return widget

    # ── General tab ──────────────────────────────────────────────────────────

    def _create_general_tab(self) -> QWidget:
        """Create the General settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Output
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Output Directory:"))
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("Documents/Screen Recordings")
        dir_row.addWidget(self._output_dir_edit)
        self._browse_button = QPushButton("Browse…")
        self._browse_button.clicked.connect(self._browse_output_directory)
        dir_row.addWidget(self._browse_button)
        output_layout.addLayout(dir_row)

        layout.addWidget(output_group)

        # Behaviour
        behaviour_group = QGroupBox("Behaviour")
        behaviour_layout = QVBoxLayout(behaviour_group)

        self._minimize_to_tray_check = QCheckBox("Minimize to System Tray when recording")
        self._minimize_to_tray_check.setChecked(True)
        behaviour_layout.addWidget(self._minimize_to_tray_check)

        self._show_notifications_check = QCheckBox("Show Notifications")
        self._show_notifications_check.setChecked(True)
        behaviour_layout.addWidget(self._show_notifications_check)

        # Hotkey info
        hotkey_label = QLabel("Hotkey: Press F9 to start/stop recording")
        hotkey_label.setStyleSheet("color: gray; font-size: 11px;")
        behaviour_layout.addWidget(hotkey_label)

        layout.addWidget(behaviour_group)
        layout.addStretch()
        return widget

    # ── Settings I/O ─────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        """Load current settings from SettingsManager into the UI."""
        settings: AppSettings = self._settings_manager.get()

        # Video - map fps to combo index (0=30, 1=24)
        video = settings.video
        fps_map = {30: 0, 24: 1}
        self._fps_combo.setCurrentIndex(fps_map.get(video.frame_rate, 0))

        # Bitrate — map stored kbps to combo index
        bitrate_map = {0: 0, 2000: 1, 4000: 2, 8000: 3, 12000: 4, 20000: 5}
        self._bitrate_combo.setCurrentIndex(bitrate_map.get(video.bitrate, 0))

        # Audio
        audio = settings.audio
        self._mic_enabled_check.setChecked(audio.microphone_enabled)
        self._sys_audio_enabled_check.setChecked(audio.system_audio_enabled)

        sample_rate_map = {48000: 0, 44100: 1}
        self._sample_rate_combo.setCurrentIndex(
            sample_rate_map.get(audio.sample_rate, 0)
        )
        self._channels_combo.setCurrentIndex(0 if audio.channels == 2 else 1)

        if audio.microphone_device:
            idx = self._mic_device_combo.findText(audio.microphone_device, Qt.MatchFlag.MatchContains)
            if idx >= 0:
                self._mic_device_combo.setCurrentIndex(idx)

        # General
        general = settings.general
        self._output_dir_edit.setText(general.output_directory)
        self._minimize_to_tray_check.setChecked(general.minimize_to_tray)
        self._show_notifications_check.setChecked(general.show_notifications)

        logger.debug("Settings loaded into UI")

    def _save_settings(self) -> None:
        """Save UI values to SettingsManager and emit ``settings_changed``."""
        # Video
        fps_keys = [30, 24]
        bitrate_keys = [0, 2000, 4000, 8000, 12000, 20000]  # 0 = CRF mode

        self._settings_manager.update(
            video__encoder="auto",
            video__bitrate=bitrate_keys[self._bitrate_combo.currentIndex()],
            video__frame_rate=fps_keys[self._fps_combo.currentIndex()],
            video__quality_preset="ultrafast",
            video__codec="h264",
        )

        # Audio
        sample_rate_keys = [48000, 44100]
        channel_keys = [2, 1]  # combo index 0 = Stereo (2ch), 1 = Mono (1ch)

        mic_device = self._mic_device_combo.currentText() if self._mic_device_combo.count() > 0 else None

        self._settings_manager.update(
            audio__microphone_enabled=self._mic_enabled_check.isChecked(),
            audio__system_audio_enabled=self._sys_audio_enabled_check.isChecked(),
            audio__microphone_device=mic_device,
            audio__system_audio_device=None,
            audio__sample_rate=sample_rate_keys[self._sample_rate_combo.currentIndex()],
            audio__channels=channel_keys[self._channels_combo.currentIndex()],
        )

        # General
        self._settings_manager.update(
            general__output_directory=self._output_dir_edit.text(),
            general__minimize_to_tray=self._minimize_to_tray_check.isChecked(),
            general__show_notifications=self._show_notifications_check.isChecked(),
            general__theme="dark",
        )

        self.settings_changed.emit()
        logger.info("Settings saved")

    def _reset_defaults(self) -> None:
        """Reset all settings to their default values in the UI."""
        defaults = AppSettings()

        # Video
        self._fps_combo.setCurrentIndex(0)  # 30fps
        self._bitrate_combo.setCurrentIndex(0)  # Auto (CRF)

        # Audio
        self._mic_enabled_check.setChecked(defaults.audio.microphone_enabled)
        self._sys_audio_enabled_check.setChecked(defaults.audio.system_audio_enabled)
        self._sample_rate_combo.setCurrentIndex(0)  # 48000 Hz
        self._channels_combo.setCurrentIndex(0)  # Stereo

        # General
        self._output_dir_edit.setText(defaults.general.output_directory)
        self._minimize_to_tray_check.setChecked(defaults.general.minimize_to_tray)
        self._show_notifications_check.setChecked(defaults.general.show_notifications)

        logger.debug("Settings reset to defaults in UI")

    # ── Private slots ────────────────────────────────────────────────────────

    def _on_ok(self) -> None:
        """Save settings and close the dialog."""
        self._save_settings()
        self.accept()

    def _on_apply(self) -> None:
        """Save settings without closing the dialog."""
        self._save_settings()

    def _on_reset_defaults(self) -> None:
        """Reset UI to default values (does not save until OK/Apply)."""
        self._reset_defaults()

    def _browse_output_directory(self) -> None:
        """Open a directory chooser dialog and update the output directory field."""
        current = self._output_dir_edit.text()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            current if current else "",
        )
        if directory:
            self._output_dir_edit.setText(directory)

    def _populate_audio_devices(self) -> None:
        """Populate audio device combo boxes from AudioDeviceEnumerator."""
        self._mic_device_combo.clear()
        try:
            input_devices = self._audio_enumerator.get_input_devices()
            for dev in input_devices:
                self._mic_device_combo.addItem(dev.name)
            logger.debug("Populated %d microphone devices", len(input_devices))
        except Exception:
            logger.exception("Failed to enumerate microphone devices")
