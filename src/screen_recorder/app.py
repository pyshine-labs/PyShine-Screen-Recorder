"""Main application module for the Screen Recorder.

This module contains the central orchestrator class and the entry point
function that initializes the QApplication, sets up the dark theme,
and manages the application lifecycle.
"""

from __future__ import annotations

import sys
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QCoreApplication, QTimer
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import QApplication

from . import __app_id__, __app_name__, __version__
from .utils.logger import logger


class RecordingState(Enum):
    """Enum representing the current recording state of the application."""

    IDLE = auto()
    RECORDING = auto()
    PAUSED = auto()


# ── Dark theme stylesheet ────────────────────────────────────────────────────

DARK_THEME_STYLESHEET = """
/* ── Global ──────────────────────────────────────────────────────────────── */
QWidget {
    background-color: #1e1e2e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #1e1e2e;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 7px 16px;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #3d3d5c;
    border-color: #7c3aed;
}

QPushButton:pressed {
    background-color: #7c3aed;
    color: #ffffff;
}

QPushButton:disabled {
    background-color: #1e1e2e;
    color: #555570;
    border-color: #2d2d44;
}

/* ── Primary / Accent button ────────────────────────────────────────────── */
QPushButton[class="accent"] {
    background-color: #7c3aed;
    color: #ffffff;
    border: 1px solid #6d28d9;
    font-weight: bold;
}

QPushButton[class="accent"]:hover {
    background-color: #6d28d9;
}

QPushButton[class="accent"]:pressed {
    background-color: #5b21b6;
}

/* ── Danger button ───────────────────────────────────────────────────────── */
QPushButton[class="danger"] {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
}

QPushButton[class="danger"]:hover {
    background-color: #b91c1c;
}

/* ── Menu Bar ────────────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #1e1e2e;
    color: #e0e0e0;
    border-bottom: 1px solid #2d2d44;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #2d2d44;
}

QMenu {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #7c3aed;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #3d3d5c;
    margin: 4px 8px;
}

/* ── Tool Bar ────────────────────────────────────────────────────────────── */
QToolBar {
    background-color: #1e1e2e;
    border-bottom: 1px solid #2d2d44;
    padding: 4px;
    spacing: 4px;
}

QToolBar::separator {
    width: 1px;
    background-color: #3d3d5c;
    margin: 4px 2px;
}

QToolButton {
    background-color: transparent;
    color: #e0e0e0;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
}

QToolButton:hover {
    background-color: #2d2d44;
    border-color: #3d3d5c;
}

QToolButton:pressed {
    background-color: #7c3aed;
    color: #ffffff;
}

/* ── Status Bar ──────────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #181828;
    color: #a0a0b8;
    border-top: 1px solid #2d2d44;
    font-size: 12px;
}

/* ── Tab Widget ──────────────────────────────────────────────────────────── */
QTabWidget::pane {
    background-color: #1e1e2e;
    border: 1px solid #2d2d44;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: #2d2d44;
    color: #a0a0b8;
    border: 1px solid #3d3d5c;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #7c3aed;
    border-bottom: 2px solid #7c3aed;
}

QTabBar::tab:hover:!selected {
    background-color: #3d3d5c;
}

/* ── Line Edit ───────────────────────────────────────────────────────────── */
QLineEdit {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #7c3aed;
}

QLineEdit:focus {
    border-color: #7c3aed;
}

QLineEdit:disabled {
    background-color: #1e1e2e;
    color: #555570;
}

/* ── Spin Box ────────────────────────────────────────────────────────────── */
QSpinBox,
QDoubleSpinBox {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 4px 8px;
}

QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #7c3aed;
}

/* ── Combo Box ────────────────────────────────────────────────────────────── */
QComboBox {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #7c3aed;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    selection-background-color: #7c3aed;
}

/* ── Check Box ────────────────────────────────────────────────────────────── */
QCheckBox {
    color: #e0e0e0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3d3d5c;
    border-radius: 4px;
    background-color: #2d2d44;
}

QCheckBox::indicator:checked {
    background-color: #7c3aed;
    border-color: #7c3aed;
}

QCheckBox::indicator:hover {
    border-color: #7c3aed;
}

/* ── Radio Button ─────────────────────────────────────────────────────────── */
QRadioButton {
    color: #e0e0e0;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3d3d5c;
    border-radius: 9px;
    background-color: #2d2d44;
}

QRadioButton::indicator:checked {
    background-color: #7c3aed;
    border-color: #7c3aed;
}

/* ── Slider ──────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #2d2d44;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #7c3aed;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: #6d28d9;
}

QSlider::sub-page:horizontal {
    background-color: #7c3aed;
    border-radius: 3px;
}

/* ── Progress Bar ────────────────────────────────────────────────────────── */
QProgressBar {
    background-color: #2d2d44;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #7c3aed;
    border-radius: 4px;
}

/* ── Scroll Bar ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #1e1e2e;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #3d3d5c;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #7c3aed;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #1e1e2e;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #3d3d5c;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #7c3aed;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #2d2d44;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ── Group Box ───────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #2d2d44;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #a0a0b8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #7c3aed;
}

/* ── Tool Tip ─────────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #2d2d44;
    color: #e0e0e0;
    border: 1px solid #3d3d5c;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ── Dialog ──────────────────────────────────────────────────────────────── */
QDialog {
    background-color: #1e1e2e;
}

/* ── Label ────────────────────────────────────────────────────────────────── */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

/* ── List Widget ─────────────────────────────────────────────────────────── */
QListWidget {
    background-color: #1e1e2e;
    color: #e0e0e0;
    border: 1px solid #2d2d44;
    border-radius: 6px;
    outline: none;
}

QListWidget::item {
    padding: 6px;
    border-radius: 4px;
}

QListWidget::item:selected {
    background-color: #7c3aed;
    color: #ffffff;
}

QListWidget::item:hover:!selected {
    background-color: #2d2d44;
}

/* ── Tree Widget ─────────────────────────────────────────────────────────── */
QTreeWidget {
    background-color: #1e1e2e;
    color: #e0e0e0;
    border: 1px solid #2d2d44;
    border-radius: 6px;
    outline: none;
}

QTreeWidget::item:selected {
    background-color: #7c3aed;
    color: #ffffff;
}

QTreeWidget::item:hover:!selected {
    background-color: #2d2d44;
}

QHeaderView::section {
    background-color: #2d2d44;
    color: #a0a0b8;
    border: none;
    padding: 6px;
    font-weight: bold;
}

/* ── System Tray Context Menu ────────────────────────────────────────────── */
QSystemTrayIcon {
    background-color: transparent;
}
"""


class ScreenRecorderApp:
    """Central orchestrator for the Screen Recorder application.

    Manages the QApplication lifecycle, coordinates components, and
    maintains the global recording state.

    Attributes:
        recording_state: The current recording state (IDLE, RECORDING, PAUSED).
    """

    def __init__(self) -> None:
        self._app: Optional[QApplication] = None
        self._main_window = None
        self._tray_manager = None
        self._hotkey_manager = None
        self._settings_manager = None
        self._recording_state: RecordingState = RecordingState.IDLE

        # ── Recording pipeline components ────────────────────────────────
        self._screen_capture: Optional[object] = None  # ScreenCapture
        self._output_writer: Optional[object] = None   # OutputWriter
        self._audio_capture: Optional[object] = None   # AudioCapture
        self._audio_mixer: Optional[object] = None      # AudioMixer
        self._capture_timer: Optional[QTimer] = None
        self._progress_timer: Optional[QTimer] = None
        self._current_output_path: Optional[str] = None
        self._selected_region = None

        logger.info("ScreenRecorderApp initialized")

    @property
    def recording_state(self) -> RecordingState:
        """Get the current recording state."""
        return self._recording_state

    @recording_state.setter
    def recording_state(self, state: RecordingState) -> None:
        """Set the recording state and notify components.

        Args:
            state: The new recording state.
        """
        self._recording_state = state
        logger.info("Recording state changed to: %s", state.name)

    def _setup_high_dpi(self) -> None:
        """Configure High DPI scaling for crisp rendering on HiDPI displays."""
        # AA_EnableHighDpiScaling and AA_UseHighDpiPixmaps are deprecated
        # in Qt6 (enabled by default), but we set them for explicit clarity
        # and compatibility with any Qt6 builds that may still respect them.
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    def _apply_dark_theme(self) -> None:
        """Apply the dark theme stylesheet to the application."""
        if self._app is not None:
            self._app.setStyleSheet(DARK_THEME_STYLESHEET)

    def _set_application_metadata(self) -> None:
        """Set application metadata on the QApplication instance."""
        if self._app is not None:
            self._app.setApplicationName(__app_name__)
            self._app.setApplicationVersion(__version__)
            self._app.setOrganizationName("ScreenRecorder")
            self._app.setOrganizationDomain(__app_id__)
            self._app.setDesktopFileName(__app_id__)

    def _create_components(self) -> None:
        """Create and wire up all application components.

        Components are created in dependency order:
        1. SettingsManager (no dependencies)
        2. MainWindow (depends on settings)
        3. TrayIconManager (depends on window)
        4. HotkeyManager (depends on app)
        """
        # Import here to avoid circular imports at module level
        from .config.settings_manager import SettingsManager
        from .gui.main_window import MainWindow
        from .gui.system_tray import TrayIconManager
        from .config.hotkey_manager import HotkeyManager

        # 1. Settings — loaded first so other components can read config
        self._settings_manager = SettingsManager()
        logger.info("SettingsManager created")

        # 2. Main window — the primary UI
        self._main_window = MainWindow()
        logger.info("MainWindow created")

        # 3. System tray — provides minimized controls
        self._tray_manager = TrayIconManager()
        self._tray_manager.show()
        logger.info("TrayIconManager created")

        # 4. Global hotkeys — start/stop/pause shortcuts
        self._hotkey_manager = HotkeyManager()
        self._hotkey_manager.register_hotkeys()
        logger.info("HotkeyManager created")

        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect signals between components for coordinated behaviour."""
        if self._main_window is None or self._tray_manager is None:
            return

        # Tray → App actions
        self._tray_manager.start_recording_triggered.connect(self._on_start_recording)
        self._tray_manager.stop_recording_triggered.connect(self._on_stop_recording)
        self._tray_manager.pause_recording_triggered.connect(self._on_pause_recording)
        self._tray_manager.resume_recording_triggered.connect(self._on_resume_recording)
        self._tray_manager.show_window_triggered.connect(self._on_show_window)
        self._tray_manager.quit_triggered.connect(self._on_quit)

        # MainWindow → App actions
        self._main_window.start_recording_requested.connect(self._on_start_recording)
        self._main_window.stop_recording_requested.connect(self._on_stop_recording)
        self._main_window.pause_recording_requested.connect(self._on_pause_recording)
        self._main_window.resume_recording_requested.connect(self._on_resume_recording)
        self._main_window.show_settings_requested.connect(self._on_show_settings)
        self._main_window.region_select_requested.connect(self._on_select_region)

        # Hotkey → App actions (F9 toggles start/stop)
        if self._hotkey_manager is not None:
            self._hotkey_manager.start_triggered.connect(self._on_toggle_recording)
            self._hotkey_manager.pause_triggered.connect(self._on_pause_recording)

    # ── Recording pipeline ─────────────────────────────────────────────────

    def _start_recording_pipeline(self) -> None:
        """Initialize and start the recording pipeline."""
        from datetime import datetime
        from .capture.screen_capture import ScreenCapture, CaptureConfig, CaptureType
        from .encoding.output_writer import OutputWriter, RecordingConfig, OutputFormat
        from .encoding.video_encoder import VideoEncoderConfig, EncoderType
        from .encoding.audio_encoder import AudioEncoderConfig
        from .audio.audio_capture import AudioCapture, AudioCaptureConfig
        from .audio.audio_mixer import AudioMixer

        settings = self._settings_manager.get()

        # ── Determine encoder type ─────────────────────────────────────
        encoder_map = {
            "auto": EncoderType.AUTO,
            "nvenc": EncoderType.NVENC,
            "qsv": EncoderType.QSV,
            "amf": EncoderType.AMF,
            "x264": EncoderType.X264,
        }
        encoder_type = encoder_map.get(settings.video.encoder, EncoderType.AUTO)

        # ── Determine capture region ───────────────────────────────────
        source_selector = self._main_window.get_source_selector()
        capture_type_key = source_selector.get_capture_type()
        monitor_index = source_selector.get_monitor_index()

        capture_type_map = {
            "screen": CaptureType.SCREEN,
            "window": CaptureType.SCREEN,  # Window capture uses same method
            "region": CaptureType.REGION,
        }
        capture_type = capture_type_map.get(capture_type_key, CaptureType.SCREEN)

        # ── Configure screen capture ────────────────────────────────────
        capture_config = CaptureConfig(
            capture_type=capture_type,
            monitor_index=monitor_index,
            fps=settings.video.frame_rate,
        )
        # If region was previously selected, use it
        if capture_type == CaptureType.REGION and self._selected_region is not None:
            capture_config.region = self._selected_region

        self._screen_capture = ScreenCapture()
        self._screen_capture.configure(capture_config)
        self._screen_capture.start()

        # ── Probe actual capture dimensions ─────────────────────────────
        probe_frame = self._screen_capture.capture_frame()
        if probe_frame is not None:
            actual_height, actual_width = probe_frame.shape[:2]
            logger.info("Detected capture dimensions: %dx%d", actual_width, actual_height)
        else:
            actual_width, actual_height = 1920, 1080
            logger.warning("Could not probe frame dimensions, using defaults: %dx%d", actual_width, actual_height)

        # ── Configure video encoder ─────────────────────────────────────
        video_config = VideoEncoderConfig(
            width=actual_width,
            height=actual_height,
            fps=settings.video.frame_rate,
            bitrate=settings.video.bitrate,
            encoder=encoder_type,
            quality_preset=settings.video.quality_preset,
        )

        # ── Configure audio ────────────────────────────────────────────
        audio_config = AudioEncoderConfig(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )

        # ── Configure and start audio capture ──────────────────────────
        audio_actually_started = False
        if settings.audio.microphone_enabled or settings.audio.system_audio_enabled:
            audio_capture_config = AudioCaptureConfig(
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
                enable_microphone=settings.audio.microphone_enabled,
                enable_system_audio=settings.audio.system_audio_enabled,
            )
            self._audio_capture = AudioCapture()
            self._audio_capture.configure(audio_capture_config)
            self._audio_capture.level_updated.connect(self._on_audio_level_updated)
            self._audio_capture.start()
            audio_actually_started = self._audio_capture.is_capturing()

        # ── Sync audio sample rate to actual capture rate ────────────────
        if self._audio_capture is not None and audio_actually_started:
            actual_rate = self._audio_capture.get_actual_sample_rate()
            if actual_rate != audio_config.sample_rate:
                logger.info(
                    "Adjusting audio sample rate from %d to %d to match capture device",
                    audio_config.sample_rate, actual_rate,
                )
                audio_config = AudioEncoderConfig(
                    sample_rate=actual_rate,
                    channels=audio_config.channels,
                    codec=audio_config.codec,
                    bitrate=audio_config.bitrate,
                    channel_layout=audio_config.channel_layout,
                )

        # ── Sync actual channel count from capture to encoder (Bug #27) ──
        if self._audio_capture is not None and audio_actually_started:
            actual_channels = self._audio_capture.get_actual_channels()
            if actual_channels != audio_config.channels:
                logger.info(
                    "Channel sync: configured=%d, actual=%d — adjusting encoder",
                    audio_config.channels, actual_channels,
                )
                audio_config.channels = actual_channels
                audio_config.channel_layout = "mono" if actual_channels == 1 else "stereo"

        # ── Generate output path ───────────────────────────────────────
        output_dir = settings.general.output_directory
        if not output_dir:
            output_dir = str(Path.home() / "Documents" / "Screen Recordings")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = str(Path(output_dir) / f"recording_{timestamp}.mp4")

        # ── Configure and start output writer ───────────────────────────
        recording_config = RecordingConfig(
            output_path=output_path,
            format=OutputFormat.MP4,
            video_config=video_config,
            audio_config=audio_config,
            include_audio=audio_actually_started,
        )

        self._output_writer = OutputWriter()
        self._output_writer.configure(recording_config)
        self._output_writer.recording_started.connect(self._on_recording_started)
        self._output_writer.recording_stopped.connect(self._on_recording_stopped)
        self._output_writer.recording_error.connect(self._on_recording_error)
        self._output_writer.progress_updated.connect(self._on_update_progress)
        self._output_writer.start()

        # ── Connect audio data to output writer ─────────────────────────
        if self._audio_capture is not None and self._output_writer is not None:
            self._audio_capture.audio_data.connect(self._output_writer.write_audio_data)

        # ── Start capture timer ────────────────────────────────────────
        fps = settings.video.frame_rate
        interval_ms = max(1, 1000 // fps)
        self._capture_timer = QTimer()
        self._capture_timer.timeout.connect(self._on_capture_frame)
        self._capture_timer.start(interval_ms)

        # ── Start progress timer ────────────────────────────────────────
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._on_update_progress)
        self._progress_timer.start(500)  # Update every 500ms

        self._current_output_path = output_path
        logger.info("Recording pipeline started → %s", output_path)

    def _stop_recording_pipeline(self) -> None:
        """Stop the recording pipeline and release resources."""
        # Stop capture timer
        if self._capture_timer is not None:
            self._capture_timer.stop()
            self._capture_timer = None

        # Stop progress timer
        if self._progress_timer is not None:
            self._progress_timer.stop()
            self._progress_timer = None

        # Stop audio capture
        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None

        # Stop output writer
        if self._output_writer is not None:
            self._output_writer.stop()
            self._output_writer = None

        # Stop screen capture
        if self._screen_capture is not None:
            self._screen_capture.stop()
            self._screen_capture = None

        logger.info("Recording pipeline stopped")

    def _on_capture_frame(self) -> None:
        """Capture a single frame and write it to the output."""
        if self._screen_capture is None or self._output_writer is None:
            return
        if self._recording_state != RecordingState.RECORDING:
            return

        frame = self._screen_capture.capture_frame()
        if frame is not None:
            self._output_writer.write_video_frame(frame, 0)  # timestamp managed by writer

            # Update preview every 3rd frame to reduce overhead
            if self._main_window is not None and self._output_writer._video_frame_count % 3 == 0:
                self._main_window.get_preview_widget().update_frame_numpy(frame)

    def _on_audio_level_updated(self, left: float, right: float) -> None:
        """Update the audio level meter."""
        if self._main_window is not None:
            self._main_window.get_audio_meter().update_levels(left, right)

    def _on_update_progress(self) -> None:
        """Update status bar with recording progress."""
        if self._output_writer is None or self._main_window is None:
            return

        duration = self._output_writer.get_recording_duration()
        file_size = self._output_writer.get_file_size()

        status_bar = self._main_window.get_status_bar()
        status_bar.update_duration(duration)
        status_bar.update_file_size(file_size)

    def _on_recording_started(self, path: str) -> None:
        """Handle recording started signal from OutputWriter."""
        logger.info("Recording started: %s", path)

    def _on_recording_stopped(self, path: str) -> None:
        """Handle recording stopped signal from OutputWriter."""
        logger.info("Recording saved: %s", path)

    def _on_recording_error(self, error: str) -> None:
        """Handle recording error signal from OutputWriter."""
        logger.error("Recording error: %s", error)

    # ── Thumbnail & history helpers ────────────────────────────────────────

    def _generate_thumbnail(self, video_path: str) -> str | None:
        """Generate a thumbnail from the first frame of a video file.

        Returns the path to the saved thumbnail PNG, or None on failure.
        """
        import av
        from PIL import Image

        try:
            with av.open(video_path) as container:
                stream = container.streams.video[0]
                frame = next(container.decode(stream))
                img = frame.to_image()
                img = img.resize((96, 64), Image.Resampling.LANCZOS)

                # Save to app data directory
                from PyQt6.QtCore import QStandardPaths
                data_dir = Path(QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation
                )) / "screen_recorder"
                data_dir.mkdir(parents=True, exist_ok=True)

                # Use UUID to avoid filename collisions
                from uuid import uuid4
                thumb_filename = f"{uuid4().hex}_thumb.png"
                thumb_path = data_dir / thumb_filename
                img.save(str(thumb_path), "PNG")

                logger.info("Generated thumbnail: %s", thumb_path)
                return str(thumb_path)
        except Exception as exc:
            logger.warning("Failed to generate thumbnail for %s: %s", video_path, exc)
            return None

    def _probe_video_metadata(self, video_path: str) -> tuple[int, int, int, float]:
        """Probe video file for width, height, frame rate, and duration.

        Returns (width, height, frame_rate, duration_seconds).
        """
        import av

        try:
            with av.open(video_path) as container:
                stream = container.streams.video[0]
                width = stream.codec_context.width
                height = stream.codec_context.height
                frame_rate = int(stream.average_rate) if stream.average_rate else 30
                duration = float(stream.duration * stream.time_base) if stream.duration and stream.time_base else 0.0
                return width, height, frame_rate, duration
        except Exception as exc:
            logger.warning("Failed to probe video metadata for %s: %s", video_path, exc)
            return 1920, 1080, 30, 0.0

    def _save_recording_to_history(self) -> None:
        """Save the completed recording to history with a thumbnail."""
        import os
        from uuid import uuid4
        from datetime import datetime
        from .config.recording_history import RecordingEntry, RecordingHistory

        if not self._current_output_path or not os.path.isfile(self._current_output_path):
            logger.warning("Cannot save to history: output file not found at %s", self._current_output_path)
            return

        try:
            file_path = self._current_output_path
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            created_at = datetime.now().isoformat()

            # Probe video metadata
            width, height, frame_rate, duration = self._probe_video_metadata(file_path)

            # Generate thumbnail
            thumbnail_path = self._generate_thumbnail(file_path)

            entry = RecordingEntry(
                id=str(uuid4()),
                file_path=file_path,
                file_name=file_name,
                created_at=created_at,
                duration=duration,
                file_size=file_size,
                width=width,
                height=height,
                frame_rate=frame_rate,
                thumbnail_path=thumbnail_path,
            )

            history = RecordingHistory()
            history.add_entry(entry)

            # Refresh the history panel in the UI
            if self._main_window is not None:
                self._main_window.get_history_panel().refresh_history()

            logger.info("Recording saved to history: %s", file_name)
        except Exception as exc:
            logger.error("Failed to save recording to history: %s", exc)

    # ── Recording state handlers ───────────────────────────────────────────

    def _on_start_recording(self) -> None:
        """Handle start recording request from any component."""
        if self._recording_state == RecordingState.IDLE:
            self.recording_state = RecordingState.RECORDING
            self._update_components_state()
            self._start_recording_pipeline()

    def _on_stop_recording(self) -> None:
        """Handle stop recording request from any component."""
        if self._recording_state in (RecordingState.RECORDING, RecordingState.PAUSED):
            self.recording_state = RecordingState.IDLE
            self._update_components_state()
            self._stop_recording_pipeline()
            self._save_recording_to_history()

    def _on_pause_recording(self) -> None:
        """Handle pause recording request from any component."""
        if self._recording_state == RecordingState.RECORDING:
            self.recording_state = RecordingState.PAUSED
            self._update_components_state()
            if self._capture_timer is not None:
                self._capture_timer.stop()
            if self._output_writer is not None:
                self._output_writer.pause()
            if self._audio_capture is not None:
                self._audio_capture.pause()

    def _on_resume_recording(self) -> None:
        """Handle resume recording request from any component."""
        if self._recording_state == RecordingState.PAUSED:
            self.recording_state = RecordingState.RECORDING
            self._update_components_state()
            if self._capture_timer is not None and self._settings_manager is not None:
                fps = self._settings_manager.get().video.frame_rate
                self._capture_timer.start(max(1, 1000 // fps))
            if self._output_writer is not None:
                self._output_writer.resume()
            if self._audio_capture is not None:
                self._audio_capture.resume()

    def _on_toggle_recording(self) -> None:
        """Toggle recording on/off (used by global hotkey F9)."""
        if self._recording_state == RecordingState.IDLE:
            self._on_start_recording()
        elif self._recording_state in (RecordingState.RECORDING, RecordingState.PAUSED):
            self._on_stop_recording()

    def _on_show_settings(self) -> None:
        """Handle show settings request."""
        from .gui.settings_panel import SettingsDialog
        dialog = SettingsDialog(self._settings_manager, self._main_window)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _on_select_region(self) -> None:
        """Handle region selection request."""
        from .capture.region_selector import RegionSelectorOverlay
        selector = RegionSelectorOverlay(self._main_window)
        selector.region_selected.connect(self._on_region_selected)
        selector.start_selection()

    def _on_settings_changed(self) -> None:
        """Handle settings changed."""
        logger.info("Settings changed")

    def _on_region_selected(self, region) -> None:
        """Handle region selected."""
        self._selected_region = region
        logger.info("Region selected: %s", region)

    def _on_show_window(self) -> None:
        """Handle show window request from the tray icon."""
        if self._main_window is not None:
            self._main_window.show()
            self._main_window.activateWindow()
            self._main_window.raise_()

    def _on_quit(self) -> None:
        """Handle quit request — clean up and exit."""
        logger.info("Quit requested")
        self._cleanup()
        if self._app is not None:
            self._app.quit()

    def _update_components_state(self) -> None:
        """Propagate the current recording state to all UI components."""
        if self._main_window is not None:
            self._main_window.set_recording_state(self._recording_state)

        if self._tray_manager is not None:
            self._tray_manager.set_recording_state(self._recording_state)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def _cleanup(self) -> None:
        """Release resources and clean up before exit."""
        logger.info("Cleaning up application resources")

        # Stop recording pipeline if active
        if self._recording_state != RecordingState.IDLE:
            self._stop_recording_pipeline()

        if self._hotkey_manager is not None:
            self._hotkey_manager.unregister_all()
        if self._tray_manager is not None:
            try:
                self._tray_manager.hide()
            except RuntimeError:
                pass  # C++ object already deleted during Qt shutdown
            try:
                self._tray_manager.deleteLater()
            except RuntimeError:
                pass
        if self._settings_manager is not None:
            self._settings_manager.save()

    def run(self) -> int:
        """Initialize and run the application event loop.

        Returns:
            The exit code from the QApplication event loop.
        """
        self._setup_high_dpi()
        self._app = QApplication(sys.argv)
        self._set_application_metadata()
        self._apply_dark_theme()
        self._create_components()

        if self._main_window is not None:
            self._main_window.show()

        logger.info("%s v%s starting…", __app_name__, __version__)
        exit_code = self._app.exec()
        self._cleanup()
        logger.info("%s exited with code %d", __app_name__, exit_code)
        return exit_code


def main() -> None:
    """Application entry point.

    Creates the ``ScreenRecorderApp`` instance and starts the Qt event loop.
    This function is referenced by the ``screen-recorder`` console script
    defined in ``pyproject.toml``.
    """
    app = ScreenRecorderApp()
    sys.exit(app.run())