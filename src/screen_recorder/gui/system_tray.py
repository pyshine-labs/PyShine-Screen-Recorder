"""System tray icon manager for the Screen Recorder application.

Provides :class:`TrayIconManager` which creates and manages a
:class:`QSystemTrayIcon` with a context menu for controlling recording
and showing/hiding the main window.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..app import RecordingState
from ..utils.logger import logger


class TrayIconManager(QSystemTrayIcon):
    """System tray icon manager with context menu for recording control.

    Provides a tray icon with a context menu that allows the user to
    start/stop/pause/resume recording, show the main window, and quit
    the application.

    Signals:
        start_recording_triggered: Emitted when "Start Recording" is clicked.
        stop_recording_triggered: Emitted when "Stop Recording" is clicked.
        pause_recording_triggered: Emitted when "Pause Recording" is clicked.
        resume_recording_triggered: Emitted when "Resume Recording" is clicked.
        show_window_triggered: Emitted when "Show Window" is clicked or the
            tray icon is double-clicked.
        quit_triggered: Emitted when "Quit" is clicked.
    """

    start_recording_triggered = pyqtSignal()
    stop_recording_triggered = pyqtSignal()
    pause_recording_triggered = pyqtSignal()
    resume_recording_triggered = pyqtSignal()
    show_window_triggered = pyqtSignal()
    quit_triggered = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._recording_state: RecordingState = RecordingState.IDLE

        # Check system tray availability
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this platform")

        self._create_tray_icon()
        self._menu = self._create_menu()
        self.setContextMenu(self._menu)

        # Connect activation (double-click / trigger)
        self.activated.connect(self._on_activated)

        logger.debug("TrayIconManager initialized")

    # ── Tray icon creation ──────────────────────────────────────────────────

    def _create_tray_icon(self) -> None:
        """Create the QSystemTrayIcon with an application icon."""
        # Try to use the application window icon, fall back to a standard pixmap
        app = QApplication.instance()
        app_icon = app.windowIcon() if app is not None else QIcon()
        if app_icon.isNull():
            # Use a standard pixmap as fallback
            style = QApplication.style() if app is not None else None
            if style is not None:
                app_icon = style.standardIcon(
                    QApplication.style().StandardPixmap.SP_ComputerIcon
                )

        self.setIcon(app_icon)
        self.setToolTip("Screen Recorder - Ready")

    # ── Menu creation ───────────────────────────────────────────────────────

    def _create_menu(self) -> QMenu:
        """Create the context menu with recording controls.

        Returns:
            The configured :class:`QMenu`.
        """
        menu = QMenu()

        # Show Window
        self._show_action = menu.addAction("Show Window")
        self._show_action.triggered.connect(self.show_window_triggered.emit)

        menu.addSeparator()

        # Start Recording
        self._start_action = menu.addAction("Start Recording")
        self._start_action.triggered.connect(self.start_recording_triggered.emit)

        # Stop Recording (disabled by default)
        self._stop_action = menu.addAction("Stop Recording")
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(self.stop_recording_triggered.emit)

        # Pause Recording (disabled by default)
        self._pause_action = menu.addAction("Pause Recording")
        self._pause_action.setEnabled(False)
        self._pause_action.triggered.connect(self.pause_recording_triggered.emit)

        # Resume Recording (disabled by default)
        self._resume_action = menu.addAction("Resume Recording")
        self._resume_action.setEnabled(False)
        self._resume_action.triggered.connect(self.resume_recording_triggered.emit)

        menu.addSeparator()

        # Quit
        self._quit_action = menu.addAction("Quit")
        self._quit_action.triggered.connect(self.quit_triggered.emit)

        return menu

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state: RecordingState) -> None:
        """Update menu item enabled states and tooltip based on recording state.

        Args:
            state: The current :class:`RecordingState`.
        """
        self._recording_state = state

        if state == RecordingState.IDLE:
            self._start_action.setEnabled(True)
            self._stop_action.setEnabled(False)
            self._pause_action.setEnabled(False)
            self._resume_action.setEnabled(False)
            self.setToolTip("Screen Recorder - Ready")

        elif state == RecordingState.RECORDING:
            self._start_action.setEnabled(False)
            self._stop_action.setEnabled(True)
            self._pause_action.setEnabled(True)
            self._resume_action.setEnabled(False)
            self.setToolTip("Screen Recorder - Recording")

        elif state == RecordingState.PAUSED:
            self._start_action.setEnabled(False)
            self._stop_action.setEnabled(True)
            self._pause_action.setEnabled(False)
            self._resume_action.setEnabled(True)
            self.setToolTip("Screen Recorder - Paused")

        logger.debug("TrayIconManager state updated: %s", state.name)

    def show(self) -> None:
        """Show the system tray icon."""
        try:
            QSystemTrayIcon.show(self)
            logger.debug("Tray icon shown")
        except RuntimeError:
            # C++ object already deleted during shutdown
            pass

    def hide(self) -> None:
        """Hide the system tray icon."""
        try:
            QSystemTrayIcon.hide(self)
            logger.debug("Tray icon hidden")
        except RuntimeError:
            # C++ object already deleted during shutdown
            pass

    # ── Private slots ────────────────────────────────────────────────────────

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (click/double-click).

        On double-click or trigger, emit :attr:`show_window_triggered`.

        Args:
            reason: The activation reason from the system tray.
        """
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.show_window_triggered.emit()
            logger.debug("Tray icon activated — show window requested")