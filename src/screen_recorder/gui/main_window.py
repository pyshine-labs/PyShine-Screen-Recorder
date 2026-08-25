"""Main application window — orchestrates all GUI panels.

Provides :class:`MainWindow`, the primary :class:`QMainWindow` that hosts
the source selector, recorder controls, audio meter, history, and status bar
in a compact, professional toolbar-style layout.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from ..app import RecordingState
from ..utils.logger import logger
from .audio_meter import AudioLevelMeter
from .history_panel import HistoryPanel
from .recorder_controls import RecorderControls
from .source_selector import SourceSelector
from .status_bar import StatusBar


class MainWindow(QMainWindow):
    """Primary application window for the Screen Recorder.

    Signals:
        start_recording_requested: Emitted when the user requests to start recording.
        stop_recording_requested: Emitted when the user requests to stop recording.
        pause_recording_requested: Emitted when the user requests to pause recording.
        resume_recording_requested: Emitted when the user requests to resume recording.
        show_settings_requested: Emitted when the user requests the settings dialog.
        region_select_requested: Emitted when the user requests region selection.
    """

    start_recording_requested = pyqtSignal()
    stop_recording_requested = pyqtSignal()
    pause_recording_requested = pyqtSignal()
    resume_recording_requested = pyqtSignal()
    show_settings_requested = pyqtSignal()
    region_select_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._quitting = False

        self.setWindowTitle("Screen Recorder")
        self.setMinimumSize(560, 420)

        # ── Child widgets ────────────────────────────────────────────────
        self._source_selector = SourceSelector()
        self._controls = RecorderControls()
        self._audio_meter = AudioLevelMeter()
        self._history_panel = HistoryPanel()
        self._status_bar = StatusBar()

        self._setup_ui()
        self._connect_signals()

        logger.info("MainWindow created")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build a compact toolbar-style layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── Top toolbar: source selector + controls + audio meter ───────
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        # Source selector (stretches to fill)
        toolbar.addWidget(self._source_selector, 1)

        # Vertical separator
        sep1 = QWidget()
        sep1.setFixedWidth(1)
        sep1.setStyleSheet("background-color: #3d3d5c;")
        toolbar.addWidget(sep1)

        # Control buttons
        toolbar.addWidget(self._controls, 0)

        # Vertical separator
        sep2 = QWidget()
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background-color: #3d3d5c;")
        toolbar.addWidget(sep2)

        # Audio meter
        toolbar.addWidget(self._audio_meter, 0)

        main_layout.addLayout(toolbar)

        # ── History panel fills remaining space ──────────────────────────
        main_layout.addWidget(self._history_panel, 1)

        # ── Status bar at the bottom ────────────────────────────────────
        main_layout.addWidget(self._status_bar)

        # ── Populate history panel with saved recordings ────────────────
        self._history_panel.refresh_history()

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Connect child widget signals to own signals."""
        # RecorderControls → MainWindow signals
        self._controls.start_requested.connect(self.start_recording_requested.emit)
        self._controls.stop_requested.connect(self.stop_recording_requested.emit)
        self._controls.pause_requested.connect(self.pause_recording_requested.emit)
        self._controls.resume_requested.connect(self.resume_recording_requested.emit)
        self._controls.settings_requested.connect(self.show_settings_requested.emit)
        self._controls.region_select_requested.connect(self.region_select_requested.emit)

        logger.debug("MainWindow signals connected")

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state: RecordingState) -> None:
        """Propagate recording state to all child widgets."""
        self._source_selector.set_recording_state(state)
        self._controls.set_recording_state(state)
        self._audio_meter.set_recording_state(state)
        self._status_bar.set_recording_state(state)
        logger.info("MainWindow recording state set: %s", state.name)

    def get_source_selector(self) -> SourceSelector:
        return self._source_selector

    def get_controls(self) -> RecorderControls:
        return self._controls

    def get_status_bar(self) -> StatusBar:
        return self._status_bar

    def get_audio_meter(self) -> AudioLevelMeter:
        return self._audio_meter

    def get_history_panel(self) -> HistoryPanel:
        return self._history_panel

    # ── Window events ────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 – Qt naming convention
        """Minimize to tray instead of closing, unless the app is quitting."""
        if self._quitting:
            event.accept()
            return

        self.hide()
        event.ignore()
        logger.info("MainWindow hidden to system tray")
