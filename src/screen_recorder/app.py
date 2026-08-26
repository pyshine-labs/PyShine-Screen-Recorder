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
#
# Palette philosophy:
#   • Three surface tiers (bg < surface < elevated) create depth without
#     heavy shadows — matches modern flat-design apps (VS Code, Linear, Notion).
#   • Indigo (#6366f1) accent is professional and less saturated than purple.
#   • Semantic colours (success/danger/warning) are reserved for state, not
#     decoration, so the UI reads clearly at a glance.

DARK_THEME_STYLESHEET = """
/* ── Global ──────────────────────────────────────────────────────────────── */
QWidget {
    background-color: #15151f;
    color: #e8e8f0;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #15151f;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #23232f;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 7px 16px;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #2a2a3a;
    border-color: #4a4a5e;
}

QPushButton:pressed {
    background-color: #1d1d28;
    border-color: #6366f1;
}

QPushButton:disabled {
    background-color: #1a1a24;
    color: #4a4a5e;
    border-color: #232330;
}

/* ── Primary / Accent button ────────────────────────────────────────────── */
QPushButton[class="accent"] {
    background-color: #6366f1;
    color: #ffffff;
    border: 1px solid #5457e5;
    font-weight: 600;
}

QPushButton[class="accent"]:hover {
    background-color: #5457e5;
    border-color: #6366f1;
}

QPushButton[class="accent"]:pressed {
    background-color: #4345d9;
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

/* ── Ghost / flat button (icon-only tool buttons) ───────────────────────── */
QPushButton[class="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}

QPushButton[class="ghost"]:hover {
    background-color: #23232f;
    border-color: #2e2e3d;
}

QPushButton[class="ghost"]:pressed {
    background-color: #1d1d28;
}

QPushButton[class="ghost"]:disabled {
    background-color: transparent;
    color: #3a3a4d;
}

/* ── Menu Bar ────────────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #15151f;
    color: #e8e8f0;
    border-bottom: 1px solid #232330;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #23232f;
}

QMenu {
    background-color: #23232f;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #2e2e3d;
    margin: 4px 8px;
}

/* ── Tool Bar ────────────────────────────────────────────────────────────── */
QToolBar {
    background-color: #15151f;
    border-bottom: 1px solid #232330;
    padding: 4px;
    spacing: 4px;
}

QToolBar::separator {
    width: 1px;
    background-color: #2e2e3d;
    margin: 4px 2px;
}

QToolButton {
    background-color: transparent;
    color: #e8e8f0;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
}

QToolButton:hover {
    background-color: #23232f;
    border-color: #2e2e3d;
}

QToolButton:pressed {
    background-color: #6366f1;
    color: #ffffff;
}

/* ── Status Bar ──────────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #11111a;
    color: #9090a8;
    border-top: 1px solid #232330;
    font-size: 12px;
}

/* ── Tab Widget ──────────────────────────────────────────────────────────── */
QTabWidget::pane {
    background-color: #1a1a24;
    border: 1px solid #232330;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: #23232f;
    color: #9090a8;
    border: 1px solid #2e2e3d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1a1a24;
    color: #6366f1;
    border-bottom: 2px solid #6366f1;
}

QTabBar::tab:hover:!selected {
    background-color: #2a2a3a;
}

/* ── Line Edit ───────────────────────────────────────────────────────────── */
QLineEdit {
    background-color: #1a1a24;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #6366f1;
}

QLineEdit:focus {
    border-color: #6366f1;
}

QLineEdit:disabled {
    background-color: #15151f;
    color: #4a4a5e;
}

/* ── Spin Box ────────────────────────────────────────────────────────────── */
QSpinBox,
QDoubleSpinBox {
    background-color: #1a1a24;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 4px 8px;
}

QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #6366f1;
}

/* ── Combo Box ────────────────────────────────────────────────────────────── */
QComboBox {
    background-color: #1a1a24;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #4a4a5e;
}

QComboBox:focus {
    border-color: #6366f1;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #23232f;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    selection-background-color: #6366f1;
    outline: none;
}

/* ── Check Box ────────────────────────────────────────────────────────────── */
QCheckBox {
    color: #e8e8f0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #2e2e3d;
    border-radius: 4px;
    background-color: #1a1a24;
}

QCheckBox::indicator:checked {
    background-color: #6366f1;
    border-color: #6366f1;
}

QCheckBox::indicator:hover {
    border-color: #6366f1;
}

/* ── Radio Button ─────────────────────────────────────────────────────────── */
QRadioButton {
    color: #e8e8f0;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #2e2e3d;
    border-radius: 9px;
    background-color: #1a1a24;
}

QRadioButton::indicator:checked {
    background-color: #6366f1;
    border-color: #6366f1;
}

/* ── Slider ──────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #23232f;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #6366f1;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: #5457e5;
}

QSlider::sub-page:horizontal {
    background-color: #6366f1;
    border-radius: 3px;
}

/* ── Progress Bar ────────────────────────────────────────────────────────── */
QProgressBar {
    background-color: #23232f;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 4px;
}

/* ── Scroll Bar ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #15151f;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #2e2e3d;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4a4a5e;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #15151f;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #2e2e3d;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #4a4a5e;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #23232f;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ── Group Box ───────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #232330;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    color: #9090a8;
    background-color: #1a1a24;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #6366f1;
}

/* ── Tool Tip ─────────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #23232f;
    color: #e8e8f0;
    border: 1px solid #2e2e3d;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ── Dialog ──────────────────────────────────────────────────────────────── */
QDialog {
    background-color: #15151f;
}

/* ── Label ────────────────────────────────────────────────────────────────── */
QLabel {
    color: #e8e8f0;
    background-color: transparent;
}

/* ── List Widget ─────────────────────────────────────────────────────────── */
QListWidget {
    background-color: #1a1a24;
    color: #e8e8f0;
    border: 1px solid #232330;
    border-radius: 8px;
    outline: none;
}

QListWidget::item {
    padding: 6px;
    border-radius: 6px;
}

QListWidget::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

QListWidget::item:hover:!selected {
    background-color: #23232f;
}

/* ── Tree Widget ─────────────────────────────────────────────────────────── */
QTreeWidget {
    background-color: #1a1a24;
    color: #e8e8f0;
    border: 1px solid #232330;
    border-radius: 8px;
    outline: none;
}

QTreeWidget::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

QTreeWidget::item:hover:!selected {
    background-color: #23232f;
}

QHeaderView::section {
    background-color: #23232f;
    color: #9090a8;
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
        self._recording_worker: Optional[object] = None  # RecordingWorker
        self._audio_capture: Optional[object] = None   # AudioCapture
        self._audio_mixer: Optional[object] = None      # AudioMixer
        self._progress_timer: Optional[QTimer] = None
        self._current_output_path: Optional[str] = None
        self._selected_region = None
        self._last_progress_stats: dict | None = None
        self._recording_overlay: Optional[object] = None  # RecordingOverlay
        self._active_capture_type_key: str = "screen"
        self._active_monitor_index: int = 0

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
            self._app.setOrganizationName("PyShine")
            self._app.setOrganizationDomain(__app_id__)
            self._app.setDesktopFileName(__app_id__)

            # Set application window icon (taskbar, title bar, Alt+Tab)
            icon_path = self._resolve_icon_path("pyshine_logo.png")
            if icon_path:
                from PyQt6.QtGui import QIcon, QPixmap
                icon = QIcon(QPixmap(str(icon_path)))
                self._app.setWindowIcon(icon)
                logger.info("Application icon set: %s", icon_path)
            else:
                logger.warning("Application icon NOT found — pyshine_logo.png missing")

    @staticmethod
    def _resolve_icon_path(name: str):
        """Resolve an icon path for both dev and frozen (EXE) modes."""
        from pathlib import Path
        import sys as _sys
        candidates = []
        if getattr(_sys, "frozen", False):
            base = Path(_sys._MEIPASS) if hasattr(_sys, "_MEIPASS") else Path(_sys.executable).parent
            candidates.append(base / "resources" / "icons" / name)
            candidates.append(base / "icons" / name)
            candidates.append(base / name)
        else:
            root = Path(__file__).parent.parent.parent
            candidates.append(root / "resources" / "icons" / name)
        for c in candidates:
            if c.is_file():
                return c
        return None

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
        """Initialize and start the recording pipeline using native C++ backend.

        The native C++ recorder handles both video (DXGI Desktop Duplication)
        and audio (WASAPI loopback) internally with native threads — NO GIL,
        NO tick sounds, guaranteed A/V sync. Python AudioCapture is NOT needed.
        """
        from datetime import datetime
        from .capture.screen_capture import CaptureConfig, CaptureType
        from .encoding.output_writer import RecordingConfig, OutputFormat
        from .encoding.video_encoder import VideoEncoderConfig, EncoderType
        from .encoding.audio_encoder import AudioEncoderConfig

        settings = self._settings_manager.get()

        try:
            from .capture.native_recorder import NativeRecorder
        except (ImportError, OSError, FileNotFoundError) as e:
            logger.error("Failed to load native recorder: %s", e)
            self._on_recording_error(f"Native recorder DLL not found: {e}")
            return

        # ── Determine capture region ───────────────────────────────────
        source_selector = self._main_window.get_source_selector()
        capture_type_key = source_selector.get_capture_type()
        monitor_index = source_selector.get_monitor_index()

        capture_type_map = {
            "screen": CaptureType.SCREEN,
            "window": CaptureType.SCREEN,
            "region": CaptureType.REGION,
        }
        capture_type = capture_type_map.get(capture_type_key, CaptureType.SCREEN)
        # Store for overlay use during recording
        self._active_capture_type_key = capture_type_key
        self._active_monitor_index = monitor_index

        # ── Screen capture config ──────────────────────────────────────
        capture_config = CaptureConfig(
            capture_type=capture_type,
            monitor_index=monitor_index,
            fps=settings.video.frame_rate,
        )
        if capture_type == CaptureType.REGION and self._selected_region is not None:
            capture_config.region = self._selected_region

        # ── Configure audio ────────────────────────────────────────────
        audio_config = AudioEncoderConfig(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )

        # ── Generate output path ───────────────────────────────────────
        output_dir = settings.general.output_directory
        if not output_dir:
            output_dir = str(Path.home() / "Documents" / "Screen Recordings")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = str(Path(output_dir) / f"recording_{timestamp}.mp4")
        self._current_output_path = output_path

        # ── Recording config ───────────────────────────────────────────
        video_config = VideoEncoderConfig(
            width=1920,
            height=1080,
            fps=settings.video.frame_rate,
            bitrate=0,
            quality_preset='ultrafast',
        )
        recording_config = RecordingConfig(
            output_path=output_path,
            format=OutputFormat.MP4,
            video_config=video_config,
            audio_config=audio_config,
            include_audio=True,
        )

        # ── Create native C++ recorder ────────────────────────────────
        # Native C++ engine uses WASAPI loopback + DXGI Desktop Duplication
        # with native threads — NO GIL, NO tick sounds, guaranteed A/V sync.
        # Audio is handled internally by C++ — do NOT create Python AudioCapture.
        # Preview is disabled to reduce CPU burden.
        fps = settings.video.frame_rate
        bitrate = settings.video.bitrate
        try:
            self._recording_worker = NativeRecorder()
            self._recording_worker.configure(capture_config, recording_config, fps)
            self._recording_worker._video_bitrate = bitrate

            # Set audio capture mode from settings
            mic_enabled = settings.audio.microphone_enabled
            sys_enabled = settings.audio.system_audio_enabled
            # When microphone is off, system audio is auto-enabled
            if not mic_enabled and not sys_enabled:
                sys_enabled = True
            self._recording_worker.set_audio_mode(mic_enabled, sys_enabled)

            # Connect signals
            self._recording_worker.recording_started.connect(self._on_recording_started)
            self._recording_worker.recording_stopped.connect(self._on_recording_stopped)
            self._recording_worker.recording_error.connect(self._on_recording_error)
            self._recording_worker.progress_updated.connect(self._on_progress_updated)
            self._recording_worker.audio_level_updated.connect(self._on_audio_level_updated)

            # Start recording (spawns C++ capture threads + FFmpeg subprocess)
            self._recording_worker.start_recording()
        except Exception as e:
            logger.error("Native recorder failed: %s", e)
            self._on_recording_error(f"Recording failed: {e}")
            self._recording_worker = None
            return

        # ── UI progress timer (main thread only, lightweight) ──────────
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._on_progress_tick)
        self._progress_timer.start(500)

        logger.info("Recording pipeline starting → %s", output_path)

    def _stop_recording_pipeline(self) -> None:
        """Stop the recording pipeline and release resources."""
        # Stop progress timer first (main thread)
        if self._progress_timer is not None:
            self._progress_timer.stop()
            self._progress_timer = None

        # Tell worker to stop and wait for threads to finish (blocking)
        if self._recording_worker is not None:
            try:
                self._recording_worker.stop_recording()
            except Exception:
                logger.exception("Error stopping recording worker")
            self._recording_worker = None

        logger.info("Recording pipeline stopped")

    def _on_progress_updated(self, stats: dict) -> None:
        """Handle progress dict emitted by the recording worker."""
        self._last_progress_stats = stats
        self._apply_progress_to_ui(stats)

    def _on_progress_tick(self) -> None:
        """Periodic UI tick — poll the native recorder for live stats."""
        if self._recording_worker is None or self._main_window is None:
            return
        stats = {
            "duration": self._recording_worker.get_recording_duration(),
            "file_size": self._recording_worker.get_file_size(),
            "fps": getattr(self._recording_worker, "_fps", 30),
        }
        self._last_progress_stats = stats
        self._apply_progress_to_ui(stats)

    def _apply_progress_to_ui(self, stats: dict) -> None:
        """Apply progress stats to the main window status bar."""
        if self._main_window is None:
            return
        duration = stats.get("duration", 0.0)
        fps = stats.get("fps", 0)
        status_bar = self._main_window.get_status_bar()
        status_bar.update_duration(duration)
        status_bar.update_fps(fps)

    def _on_recording_error(self, error: str) -> None:
        """Handle recording error signal from OutputWriter."""
        logger.error("Recording error: %s", error)
        self._hide_recording_overlay()

    def _on_audio_level_updated(self, left: float, right: float) -> None:
        """Update the audio level meter."""
        if self._main_window is not None:
            self._main_window.get_audio_meter().update_levels(left, right)

    def _on_recording_started(self, path: str) -> None:
        """Handle recording started signal from the worker."""
        logger.info("Recording started: %s", path)
        self._show_recording_overlay()

    def _on_recording_stopped(self, path: str) -> None:
        """Handle recording stopped signal from the worker."""
        logger.info("Recording saved: %s", path)
        self._hide_recording_overlay()

    def _show_recording_overlay(self) -> None:
        """Show the dotted boundary overlay around the recorded area."""
        from .capture.recording_overlay import RecordingOverlay
        try:
            self._recording_overlay = RecordingOverlay()
            if self._active_capture_type_key == "region" and self._selected_region is not None:
                self._recording_overlay.show_for_rect(self._selected_region)
            else:
                self._recording_overlay.show_fullscreen(self._active_monitor_index)
        except Exception as e:
            logger.error("Failed to show recording overlay: %s", e)
            self._recording_overlay = None

    def _hide_recording_overlay(self) -> None:
        """Hide the dotted boundary overlay."""
        if self._recording_overlay is not None:
            try:
                self._recording_overlay.hide_overlay()
            except Exception as e:
                logger.error("Failed to hide recording overlay: %s", e)
            self._recording_overlay = None

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
            if self._recording_worker is not None:
                self._recording_worker.pause()
            if self._recording_overlay is not None:
                self._recording_overlay.pause_animation(True)

    def _on_resume_recording(self) -> None:
        """Handle resume recording request from any component."""
        if self._recording_state == RecordingState.PAUSED:
            self.recording_state = RecordingState.RECORDING
            self._update_components_state()
            fps = 30
            if self._settings_manager is not None:
                fps = self._settings_manager.get().video.frame_rate
            if self._recording_worker is not None:
                self._recording_worker.resume(fps)
            if self._recording_overlay is not None:
                self._recording_overlay.pause_animation(False)

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
        """Run the application event loop.

        Returns:
            The exit code from the QApplication event loop.
        """
        # Set Windows AppUserModelID so the taskbar shows our icon, not Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(__app_id__)
        except Exception:
            pass

        # Add file logging for frozen EXE (no console)
        if getattr(sys, "frozen", False):
            import logging
            log_path = Path.home() / "Documents" / "ScreenRecorder" / "debug.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(log_path), encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            logging.getLogger("screen_recorder").addHandler(fh)

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