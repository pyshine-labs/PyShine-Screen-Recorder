"""Recorder controls widget — start, stop, pause, region select, and settings.

Provides a :class:`RecorderControls` panel with professional circular icon
buttons for controlling the recording session.  Buttons use semantic solid
colours (green = start, red = stop, amber = pause, indigo = region, neutral
grey = settings) with consistent geometry and hover/pressed states.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..utils.logger import logger


class RecorderControls(QWidget):
    """Recording control panel with professional circular icon buttons.

    Signals:
        start_requested: Emitted when the Start button is clicked.
        stop_requested: Emitted when the Stop button is clicked.
        pause_requested: Emitted when the Pause button is clicked.
        resume_requested: Emitted when the Resume button is clicked (Pause in PAUSED state).
        settings_requested: Emitted when the Settings button is clicked.
        region_select_requested: Emitted when the Region Select button is clicked.
    """

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    region_select_requested = pyqtSignal()

    # ── Geometry ───────────────────────────────────────────────────────────
    _BTN_SIZE = 34  # Circular button diameter (compact)

    # ── Shared button stylesheet template ──────────────────────────────────
    # Solid semantic colour with subtle top→bottom gradient for depth.
    _STYLE = (
        "QPushButton {{ "
        "  background-color: {bg}; "
        "  color: {fg}; "
        "  border: 1px solid {border}; "
        "  border-radius: {r}px; "
        "  font-size: 16px; "
        "  min-width: {size}px; max-width: {size}px; "
        "  min-height: {size}px; max-height: {size}px; "
        "  padding: 0px; "
        "}} "
        "QPushButton:hover {{ "
        "  background-color: {hover}; "
        "  border-color: {accent}; "
        "}} "
        "QPushButton:pressed {{ "
        "  background-color: {pressed}; "
        "}} "
        "QPushButton:disabled {{ "
        "  background-color: #1a1a24; "
        "  color: #3a3a4d; "
        "  border-color: #232330; "
        "}}"
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_paused = False
        self._setup_ui()
        self._connect_signals()
        logger.debug("RecorderControls initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the control panel as a horizontal toolbar."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        # ── Start (green) ──────────────────────────────────────────────
        self._start_btn = self._create_button(
            icon="▶",
            tooltip="Start Recording",
            bg="#15803d", hover="#16a34a", pressed="#166534",
            border="#22c55e", accent="#4ade80", fg="#ffffff",
        )
        layout.addWidget(self._start_btn)

        # ── Stop (red) ─────────────────────────────────────────────────
        self._stop_btn = self._create_button(
            icon="■",
            tooltip="Stop Recording",
            bg="#991b1b", hover="#dc2626", pressed="#7f1d1d",
            border="#ef4444", accent="#fca5a5", fg="#ffffff",
        )
        self._stop_btn.setEnabled(False)
        layout.addWidget(self._stop_btn)

        # ── Pause / Resume (amber) ─────────────────────────────────────
        self._pause_btn = self._create_button(
            icon="⏸",
            tooltip="Pause Recording",
            bg="#854d0e", hover="#eab308", pressed="#713f12",
            border="#facc15", accent="#fde68a", fg="#ffffff",
        )
        self._pause_btn.setEnabled(False)
        layout.addWidget(self._pause_btn)

        layout.addSpacing(4)

        # ── Region select (indigo) ────────────────────────────────────
        self._region_btn = self._create_button(
            icon="⬚",
            tooltip="Select Region",
            bg="#312e81", hover="#4f46e5", pressed="#1e1b4b",
            border="#6366f1", accent="#a5b4fc", fg="#e0e7ff",
        )
        layout.addWidget(self._region_btn)

        # ── Settings (neutral grey) ───────────────────────────────────
        self._settings_btn = self._create_button(
            icon="⚙",
            tooltip="Settings",
            bg="#23232f", hover="#2a2a3a", pressed="#1d1d28",
            border="#2e2e3d", accent="#4a4a5e", fg="#e8e8f0",
        )
        layout.addWidget(self._settings_btn)

        layout.addStretch()

    def _create_button(
        self,
        icon: str,
        tooltip: str,
        bg: str, hover: str, pressed: str,
        border: str, accent: str, fg: str,
    ) -> QPushButton:
        """Create a circular icon button with semantic colouring."""
        btn = QPushButton(icon)
        btn.setToolTip(tooltip)
        btn.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        style = self._STYLE.format(
            bg=bg, hover=hover, pressed=pressed,
            fg=fg, border=border, accent=accent,
            size=self._BTN_SIZE,
            r=self._BTN_SIZE // 2,  # circular
        )
        btn.setStyleSheet(style)
        return btn

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Connect button clicks to own signals."""
        self._start_btn.clicked.connect(self.start_requested.emit)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        self._region_btn.clicked.connect(self.region_select_requested.emit)

    def _on_pause_clicked(self) -> None:
        """Handle pause/resume button click based on current state."""
        if self._is_paused:
            logger.debug("Resume clicked")
            self.resume_requested.emit()
        else:
            logger.debug("Pause clicked")
            self.pause_requested.emit()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state) -> None:
        """Update button enabled/disabled states based on recording state."""
        from ..app import RecordingState

        if state == RecordingState.IDLE:
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            self._pause_btn.setText("⏸")
            self._pause_btn.setToolTip("Pause Recording")
            self._is_paused = False
            self._region_btn.setEnabled(True)

        elif state == RecordingState.RECORDING:
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText("⏸")
            self._pause_btn.setToolTip("Pause Recording")
            self._is_paused = False
            self._region_btn.setEnabled(False)

        elif state == RecordingState.PAUSED:
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText("▶")
            self._pause_btn.setToolTip("Resume Recording")
            self._is_paused = True
            self._region_btn.setEnabled(False)

        logger.debug("RecorderControls state updated: %s", state.name)
