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
    QSpinBox,
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
        self.setMinimumSize(520, 480)
        self._setup_ui()
        self._load_settings()
        logger.debug("SettingsDialog initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the tabbed settings dialog."""
        layout = QVBoxLayout(self)

        # ── Tab widget ────────────────────────────────────────────────────
        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._create_video_tab(), "Video")
        self._tab_widget.addTab(self._create_audio_tab(), "Audio")
        self._tab_widget.addTab(self._create_general_tab(), "General")
        layout.addWidget(self._tab_widget)

        # ── Dialog buttons ────────────────────────────────────────────────
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self._reset_button = QPushButton("Reset Defaults")
        self._reset_button.setToolTip("Restore all settings to their default values")
        self._button_box.addButton(self._reset_button, QDialogButtonBox.ButtonRole.ResetRole)

        layout.addWidget(self._button_box)

        # ── Connections ───────────────────────────────────────────────────
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)
        self._button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        self._reset_button.clicked.connect(self._on_reset_defaults)

    # ── Video tab ────────────────────────────────────────────────────────────

    def _create_video_tab(self) -> QWidget:
        """Create the Video settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Encoder
        encoder_group = QGroupBox("Encoder")
        encoder_layout = QVBoxLayout(encoder_group)

        encoder_row = QHBoxLayout()
        encoder_row.addWidget(QLabel("Encoder:"))
        self._encoder_combo = QComboBox()
        self._encoder_combo.addItems(["Auto", "NVENC", "QuickSync (QSV)", "AMF", "x264"])
        encoder_row.addWidget(self._encoder_combo)
        encoder_layout.addLayout(encoder_row)

        codec_row = QHBoxLayout()
        codec_row.addWidget(QLabel("Codec:"))
        self._codec_label = QLabel("H.264")
        self._codec_label.setStyleSheet("font-weight: bold;")
        codec_row.addWidget(self._codec_label)
        codec_row.addStretch()
        encoder_layout.addLayout(codec_row)

        layout.addWidget(encoder_group)

        # Quality
        quality_group = QGroupBox("Quality")
        quality_layout = QVBoxLayout(quality_group)

        bitrate_row = QHBoxLayout()
        bitrate_row.addWidget(QLabel("Bitrate:"))
        self._bitrate_spin = QSpinBox()
        self._bitrate_spin.setRange(1000, 50000)
        self._bitrate_spin.setSingleStep(500)
        self._bitrate_spin.setSuffix(" kbps")
        self._bitrate_spin.setValue(5000)
        bitrate_row.addWidget(self._bitrate_spin)
        bitrate_row.addStretch()
        quality_layout.addLayout(bitrate_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frame Rate:"))
        self._fps_combo = QComboBox()
        self._fps_combo.addItems(["15", "24", "30", "60"])
        fps_row.addWidget(self._fps_combo)
        fps_row.addStretch()
        quality_layout.addLayout(fps_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Quality Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(["Ultrafast", "Fast", "Medium", "Slow"])
        preset_row.addWidget(self._preset_combo)
        preset_row.addStretch()
        quality_layout.addLayout(preset_row)

        layout.addWidget(quality_group)
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

        self._sys_audio_enabled_check = QCheckBox("Enable System Audio")
        self._sys_audio_enabled_check.setChecked(False)
        sys_layout.addWidget(self._sys_audio_enabled_check)

        sys_device_row = QHBoxLayout()
        sys_device_row.addWidget(QLabel("Device:"))
        self._sys_audio_device_combo = QComboBox()
        sys_device_row.addWidget(self._sys_audio_device_combo)
        sys_layout.addLayout(sys_device_row)

        layout.addWidget(sys_group)

        # Format
        format_group = QGroupBox("Format")
        format_layout = QVBoxLayout(format_group)

        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("Sample Rate:"))
        self._sample_rate_combo = QComboBox()
        self._sample_rate_combo.addItems(["44100", "48000"])
        sample_row.addWidget(self._sample_rate_combo)
        sample_row.addStretch()
        format_layout.addLayout(sample_row)

        channels_row = QHBoxLayout()
        channels_row.addWidget(QLabel("Channels:"))
        self._channels_combo = QComboBox()
        self._channels_combo.addItems(["Mono", "Stereo"])
        channels_row.addWidget(self._channels_combo)
        channels_row.addStretch()
        format_layout.addLayout(channels_row)

        layout.addWidget(format_group)
        layout.addStretch()

        # Populate audio devices
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

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Filename Template:"))
        self._filename_template_edit = QLineEdit("recording_{timestamp}")
        template_row.addWidget(self._filename_template_edit)
        output_layout.addLayout(template_row)

        layout.addWidget(output_group)

        # Behaviour
        behaviour_group = QGroupBox("Behaviour")
        behaviour_layout = QVBoxLayout(behaviour_group)

        self._minimize_to_tray_check = QCheckBox("Minimize to System Tray")
        self._minimize_to_tray_check.setChecked(True)
        behaviour_layout.addWidget(self._minimize_to_tray_check)

        self._show_notifications_check = QCheckBox("Show Notifications")
        self._show_notifications_check.setChecked(True)
        behaviour_layout.addWidget(self._show_notifications_check)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark"])
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        behaviour_layout.addLayout(theme_row)

        layout.addWidget(behaviour_group)
        layout.addStretch()
        return widget

    # ── Settings I/O ─────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        """Load current settings from SettingsManager into the UI."""
        settings: AppSettings = self._settings_manager.get()

        # Video
        video = settings.video
        encoder_map = {
            "auto": 0, "nvenc": 1, "qsv": 2, "amf": 3, "x264": 4,
        }
        self._encoder_combo.setCurrentIndex(encoder_map.get(video.encoder, 0))
        self._bitrate_spin.setValue(video.bitrate)

        fps_map = {"15": 0, "24": 1, "30": 2, "60": 3}
        self._fps_combo.setCurrentIndex(fps_map.get(str(video.frame_rate), 2))

        preset_map = {"ultrafast": 0, "fast": 1, "medium": 2, "slow": 3}
        self._preset_combo.setCurrentIndex(preset_map.get(video.quality_preset, 2))

        # Audio
        audio = settings.audio
        self._mic_enabled_check.setChecked(audio.microphone_enabled)
        self._sys_audio_enabled_check.setChecked(audio.system_audio_enabled)

        sample_rate_map = {"44100": 0, "48000": 1}
        self._sample_rate_combo.setCurrentIndex(
            sample_rate_map.get(str(audio.sample_rate), 1)
        )
        self._channels_combo.setCurrentIndex(0 if audio.channels == 1 else 1)

        # Select saved microphone device
        if audio.microphone_device:
            idx = self._mic_device_combo.findText(audio.microphone_device, Qt.MatchFlag.MatchContains)
            if idx >= 0:
                self._mic_device_combo.setCurrentIndex(idx)

        # Select saved system audio device
        if audio.system_audio_device:
            idx = self._sys_audio_device_combo.findText(audio.system_audio_device, Qt.MatchFlag.MatchContains)
            if idx >= 0:
                self._sys_audio_device_combo.setCurrentIndex(idx)

        # General
        general = settings.general
        self._output_dir_edit.setText(general.output_directory)
        self._filename_template_edit.setText(general.default_filename_template)
        self._minimize_to_tray_check.setChecked(general.minimize_to_tray)
        self._show_notifications_check.setChecked(general.show_notifications)

        theme_map = {"dark": 0}
        self._theme_combo.setCurrentIndex(theme_map.get(general.theme, 0))

        logger.debug("Settings loaded into UI")

    def _save_settings(self) -> None:
        """Save UI values to SettingsManager and emit ``settings_changed``."""
        # Video
        encoder_keys = ["auto", "nvenc", "qsv", "amf", "x264"]
        fps_keys = [15, 24, 30, 60]
        preset_keys = ["ultrafast", "fast", "medium", "slow"]

        self._settings_manager.update(
            video__encoder=encoder_keys[self._encoder_combo.currentIndex()],
            video__bitrate=self._bitrate_spin.value(),
            video__frame_rate=fps_keys[self._fps_combo.currentIndex()],
            video__quality_preset=preset_keys[self._preset_combo.currentIndex()],
        )

        # Audio
        sample_rate_keys = [44100, 48000]
        channel_keys = [1, 2]

        mic_device = self._mic_device_combo.currentText() if self._mic_device_combo.count() > 0 else None
        sys_device = self._sys_audio_device_combo.currentText() if self._sys_audio_device_combo.count() > 0 else None

        self._settings_manager.update(
            audio__microphone_enabled=self._mic_enabled_check.isChecked(),
            audio__system_audio_enabled=self._sys_audio_enabled_check.isChecked(),
            audio__microphone_device=mic_device,
            audio__system_audio_device=sys_device,
            audio__sample_rate=sample_rate_keys[self._sample_rate_combo.currentIndex()],
            audio__channels=channel_keys[self._channels_combo.currentIndex()],
        )

        # General
        self._settings_manager.update(
            general__output_directory=self._output_dir_edit.text(),
            general__default_filename_template=self._filename_template_edit.text(),
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
        encoder_map = {"auto": 0, "nvenc": 1, "qsv": 2, "amf": 3, "x264": 4}
        self._encoder_combo.setCurrentIndex(encoder_map.get(defaults.video.encoder, 0))
        self._bitrate_spin.setValue(defaults.video.bitrate)

        fps_map = {"15": 0, "24": 1, "30": 2, "60": 3}
        self._fps_combo.setCurrentIndex(fps_map.get(str(defaults.video.frame_rate), 2))

        preset_map = {"ultrafast": 0, "fast": 1, "medium": 2, "slow": 3}
        self._preset_combo.setCurrentIndex(preset_map.get(defaults.video.quality_preset, 2))

        # Audio
        self._mic_enabled_check.setChecked(defaults.audio.microphone_enabled)
        self._sys_audio_enabled_check.setChecked(defaults.audio.system_audio_enabled)
        self._sample_rate_combo.setCurrentIndex(1)  # 48000
        self._channels_combo.setCurrentIndex(1)  # Stereo

        # General
        self._output_dir_edit.setText(defaults.general.output_directory)
        self._filename_template_edit.setText(defaults.general.default_filename_template)
        self._minimize_to_tray_check.setChecked(defaults.general.minimize_to_tray)
        self._show_notifications_check.setChecked(defaults.general.show_notifications)
        self._theme_combo.setCurrentIndex(0)

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
        # Microphone devices
        self._mic_device_combo.clear()
        try:
            input_devices = self._audio_enumerator.get_input_devices()
            for dev in input_devices:
                self._mic_device_combo.addItem(dev.name)
            logger.debug("Populated %d microphone devices", len(input_devices))
        except Exception:
            logger.exception("Failed to enumerate microphone devices")

        # System audio (loopback) devices
        self._sys_audio_device_combo.clear()
        try:
            loopback_devices = self._audio_enumerator.get_loopback_devices()
            for dev in loopback_devices:
                self._sys_audio_device_combo.addItem(dev.name)
            logger.debug("Populated %d loopback devices", len(loopback_devices))
        except Exception:
            logger.exception("Failed to enumerate loopback devices")