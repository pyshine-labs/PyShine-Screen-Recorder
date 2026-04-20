"""Recorder controls widget — start, stop, pause, region select, and settings.

Provides a :class:`RecorderControls` panel with icon buttons for controlling
the recording session.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..utils.logger import logger


class RecorderControls(QWidget):
    """Recording control panel with start, stop, pause, region, and settings buttons.

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

    _BTN_SIZE = 48
    _BASE_STYLE = (
        "QPushButton {{ "
        "  background-color: {bg}; "
        "  color: {fg}; "
        "  border: 1px solid {border}; "
        "  border-radius: 8px; "
        "  font-size: 20px; "
        "  min-width: {size}px; "
        "  max-width: {size}px; "
        "  min-height: {size}px; "
        "  max-height: {size}px; "
        "}} "
        "QPushButton:hover {{ "
        "  background-color: {hover_bg}; "
        "  border-color: #7c3aed; "
        "}} "
        "QPushButton:disabled {{ "
        "  background-color: #1e1e2e; "
        "  color: #555570; "
        "  border-color: #2d2d44; "
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
        """Build the control panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # ── Button row ───────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        # Start button (green)
        self._start_btn = self._create_button(
            icon="▶",
            tooltip="Start Recording",
            bg="#166534",
            fg="#4ade80",
            border="#22c55e",
            hover_bg="#15803d",
        )
        btn_layout.addWidget(self._start_btn)

        # Stop button (red)
        self._stop_btn = self._create_button(
            icon="■",
            tooltip="Stop Recording",
            bg="#7f1d1d",
            fg="#fca5a5",
            border="#ef4444",
            hover_bg="#991b1b",
        )
        self._stop_btn.setEnabled(False)
        btn_layout.addWidget(self._stop_btn)

        # Pause / Resume button (yellow)
        self._pause_btn = self._create_button(
            icon="⏸",
            tooltip="Pause Recording",
            bg="#713f12",
            fg="#fde68a",
            border="#facc15",
            hover_bg="#854d0e",
        )
        self._pause_btn.setEnabled(False)
        btn_layout.addWidget(self._pause_btn)

        # Region select button
        self._region_btn = self._create_button(
            icon="📐",
            tooltip="Select Region",
            bg="#2a2a3e",
            fg="#e0e0e0",
            border="#3d3d5c",
            hover_bg="#3d3d5c",
        )
        btn_layout.addWidget(self._region_btn)

        # Settings button
        self._settings_btn = self._create_button(
            icon="⚙",
            tooltip="Settings",
            bg="#2a2a3e",
            fg="#e0e0e0",
            border="#3d3d5c",
            hover_bg="#3d3d5c",
        )
        btn_layout.addWidget(self._settings_btn)

        layout.addLayout(btn_layout)

        # ── Button labels ───────────────────────────────────────────────
        label_layout = QHBoxLayout()
        label_layout.setSpacing(6)

        for text in ("Start", "Stop", "Pause", "Region", "Settings"):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #a0a0b8; font-size: 10px;")
            lbl.setFixedWidth(self._BTN_SIZE)
            label_layout.addWidget(lbl)

        layout.addLayout(label_layout)

    def _create_button(
        self,
        icon: str,
        tooltip: str,
        bg: str,
        fg: str,
        border: str,
        hover_bg: str,
    ) -> QPushButton:
        """Create a styled control button.

        Args:
            icon: Unicode icon character for the button.
            tooltip: Tooltip text.
            bg: Normal background colour.
            fg: Text/foreground colour.
            border: Border colour.
            hover_bg: Hover background colour.

        Returns:
            A configured :class:`QPushButton`.
        """
        btn = QPushButton(icon)
        btn.setToolTip(tooltip)
        btn.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        style = self._BASE_STYLE.format(
            bg=bg, fg=fg, border=border, hover_bg=hover_bg, size=self._BTN_SIZE
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
        """Update button enabled/disabled states based on recording state.

        Args:
            state: A :class:`RecordingState` enum value (IDLE, RECORDING, PAUSED).
        """
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