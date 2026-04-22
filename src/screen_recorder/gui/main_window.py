"""Main application window — orchestrates all GUI panels.

Provides :class:`MainWindow`, the primary :class:`QMainWindow` that hosts
the source selector, preview, recorder controls, audio meter, and status bar.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..app import RecordingState
from ..utils.logger import logger
from .audio_meter import AudioLevelMeter
from .history_panel import HistoryPanel
from .preview_widget import PreviewWidget
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
        self.setMinimumSize(800, 600)

        # ── Child widgets ────────────────────────────────────────────────
        self._source_selector = SourceSelector()
        self._preview_widget = PreviewWidget()
        self._controls = RecorderControls()
        self._audio_meter = AudioLevelMeter()
        self._history_panel = HistoryPanel()
        self._status_bar = StatusBar()

        self._setup_ui()
        self._connect_signals()

        logger.info("MainWindow created")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the main window layout with a splitter arrangement."""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ── Horizontal splitter ──────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # ── Left panel: source selector + preview ────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        left_layout.addWidget(self._source_selector)
        left_layout.addWidget(self._preview_widget, 1)  # Stretch factor 1

        # ── Right panel: controls + audio meter ──────────────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        right_layout.addWidget(self._controls)
        right_layout.addWidget(self._audio_meter)
        right_layout.addWidget(self._history_panel, 1)  # stretch factor 1 so it fills space

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        # Set initial splitter sizes (70% left, 30% right)
        splitter.setSizes([560, 240])

        main_layout.addWidget(splitter, 1)  # Stretch factor 1

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
        """Propagate recording state to all child widgets.

        Args:
            state: The current :class:`RecordingState` (IDLE, RECORDING, PAUSED).
        """
        self._source_selector.set_recording_state(state)
        self._preview_widget.set_recording_state(state)
        self._controls.set_recording_state(state)
        self._audio_meter.set_recording_state(state)
        self._status_bar.set_recording_state(state)
        logger.info("MainWindow recording state set: %s", state.name)

    def get_source_selector(self) -> SourceSelector:
        """Return the source selector widget."""
        return self._source_selector

    def get_preview_widget(self) -> PreviewWidget:
        """Return the preview widget."""
        return self._preview_widget

    def get_controls(self) -> RecorderControls:
        """Return the recorder controls widget."""
        return self._controls

    def get_status_bar(self) -> StatusBar:
        """Return the status bar widget."""
        return self._status_bar

    def get_audio_meter(self) -> AudioLevelMeter:
        """Return the audio level meter widget."""
        return self._audio_meter

    def get_history_panel(self) -> HistoryPanel:
        """Return the history panel widget."""
        return self._history_panel

    # ── Window events ────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 – Qt naming convention
        """Minimize to tray instead of closing, unless the app is quitting.

        Hides the window and ignores the close event.  When the app is
        actually quitting (``_quitting`` flag set), the event is accepted.
        """
        if self._quitting:
            event.accept()
            return

        # Minimize to system tray instead of closing
        self.hide()
        event.ignore()
        logger.info("MainWindow hidden to system tray")