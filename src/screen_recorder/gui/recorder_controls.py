"""Recorder controls widget — start, stop, pause, region select, and settings.

Provides a :class:`RecorderControls` panel with modern icon buttons for
controlling the recording session.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..utils.logger import logger


class RecorderControls(QWidget):
    """Recording control panel with modern start, stop, pause, region, and settings buttons.

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

    # ── Button style constants ───────────────────────────────────────────────

    _BTN_SIZE = 44

    _BASE_STYLE = (
        "QPushButton {{ "
        "  background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "    stop:0 {bg1}, stop:1 {bg2}); "
        "  color: {fg}; "
        "  border: 1px solid {border}; "
        "  border-radius: 10px; "
        "  font-size: 18px; "
        "  min-width: {size}px; "
        "  max-width: {size}px; "
        "  min-height: {size}px; "
        "  max-height: {size}px; "
        "  padding: 0px; "
        "}} "
        "QPushButton:hover {{ "
        "  background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "    stop:0 {hover1}, stop:1 {hover2}); "
        "  border-color: {accent}; "
        "}} "
        "QPushButton:pressed {{ "
        "  background-color: {pressed}; "
        "}} "
        "QPushButton:disabled {{ "
        "  background-color: #1a1a2e; "
        "  color: #3a3a4e; "
        "  border-color: #2a2a3e; "
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
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Start button (green gradient)
        self._start_btn = self._create_button(
            icon="▶",
            tooltip="Start Recording",
            bg1="#15803d", bg2="#166534",
            hover1="#22c55e", hover2="#16a34a",
            pressed="#15803d",
            fg="#ffffff", border="#22c55e", accent="#4ade80",
        )
        layout.addWidget(self._start_btn)

        # Stop button (red gradient)
        self._stop_btn = self._create_button(
            icon="■",
            tooltip="Stop Recording",
            bg1="#991b1b", bg2="#7f1d1d",
            hover1="#ef4444", hover2="#dc2626",
            pressed="#991b1b",
            fg="#ffffff", border="#ef4444", accent="#fca5a5",
        )
        self._stop_btn.setEnabled(False)
        layout.addWidget(self._stop_btn)

        # Pause / Resume button (amber gradient)
        self._pause_btn = self._create_button(
            icon="⏸",
            tooltip="Pause Recording",
            bg1="#854d0e", bg2="#713f12",
            hover1="#facc15", hover2="#eab308",
            pressed="#854d0e",
            fg="#ffffff", border="#facc15", accent="#fde68a",
        )
        self._pause_btn.setEnabled(False)
        layout.addWidget(self._pause_btn)

        # Separator
        sep = QLabel()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3d3d5c;")
        layout.addWidget(sep)

        # Region select button
        self._region_btn = self._create_button(
            icon="⬚",
            tooltip="Select Region",
            bg1="#312e81", bg2="#1e1b4b",
            hover1="#4f46e5", hover2="#4338ca",
            pressed="#312e81",
            fg="#c7d2fe", border="#6366f1", accent="#a5b4fc",
        )
        layout.addWidget(self._region_btn)

        # Settings button
        self._settings_btn = self._create_button(
            icon="⚙",
            tooltip="Settings",
            bg1="#374151", bg2="#1f2937",
            hover1="#6b7280", hover2="#4b5563",
            pressed="#374151",
            fg="#e5e7eb", border="#6b7280", accent="#d1d5db",
        )
        layout.addWidget(self._settings_btn)

        layout.addStretch()

    def _create_button(
        self,
        icon: str,
        tooltip: str,
        bg1: str, bg2: str,
        hover1: str, hover2: str,
        pressed: str,
        fg: str, border: str, accent: str,
    ) -> QPushButton:
        """Create a modern gradient-styled control button."""
        btn = QPushButton(icon)
        btn.setToolTip(tooltip)
        btn.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        style = self._BASE_STYLE.format(
            bg1=bg1, bg2=bg2,
            hover1=hover1, hover2=hover2,
            pressed=pressed,
            fg=fg, border=border, accent=accent,
            size=self._BTN_SIZE,
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
