"""Status bar widget — displays recording state, duration, file size, and FPS.

Provides a :class:`StatusBar` widget with a professional pill-shaped stats
bar showing the recording-state indicator, status text, elapsed duration,
estimated file size, and current frames-per-second.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..utils.logger import logger


class StatusBar(QWidget):
    """Horizontal status bar showing recording state and statistics.

    Signals:
        recording_duration_changed: Emitted when the displayed duration
            is updated (carries the elapsed seconds as a float).
    """

    from PyQt6.QtCore import pyqtSignal

    recording_duration_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = None  # Will be set via set_recording_state
        self._blink_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._on_blink_timeout)

        self._setup_ui()
        logger.debug("StatusBar initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the status bar layout with clean labelled stats."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(16)

        # Recording state indicator (coloured dot)
        self._indicator = self._create_status_indicator()
        layout.addWidget(self._indicator)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            "font-weight: 600; font-size: 13px; color: #9090a8;"
        )
        layout.addWidget(self._status_label)

        layout.addStretch()

        # ── Stat chips: Duration | FPS ─────────────────────────────────
        # Clean label + value layout (no emojis) — reads as a pro dashboard.
        self._duration_label = self._create_stat_chip("DURATION", "00:00:00")
        layout.addWidget(self._duration_label)

        layout.addWidget(self._make_sep())

        self._fps_label = self._create_stat_chip("FPS", "0")
        layout.addWidget(self._fps_label)

        # Overall status bar style
        self.setStyleSheet(
            "StatusBar { "
            "  background-color: #11111a; "
            "  border-top: 1px solid #232330; "
            "}"
        )

    @staticmethod
    def _make_sep() -> QWidget:
        """Subtle vertical dot separator between stat groups."""
        from PyQt6.QtWidgets import QWidget as _W
        sep = _W()
        sep.setFixedSize(3, 3)
        sep.setStyleSheet("background-color: #2e2e3d; border-radius: 1px;")
        return sep

    def _create_stat_chip(self, label: str, value: str) -> QWidget:
        """Create a clean stat readout: uppercase label above value.

        Args:
            label: Uppercase stat label (e.g. "DURATION").
            value: Initial value text.

        Returns:
            A styled :class:`QWidget` containing the label/value pair.
        """
        from PyQt6.QtWidgets import QVBoxLayout, QLabel
        chip = QWidget()
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(0)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; color: #6a6a82; "
            "letter-spacing: 1px;"
        )
        chip_layout.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #e8e8f0; "
            "font-family: 'Consolas', 'Segoe UI Mono', monospace;"
        )
        chip_layout.addWidget(val)

        # Store the value label for later updates
        chip.setProperty("value_label", val)
        # Keep a direct ref for the type-safe API below
        chip._value_label = val  # type: ignore[attr-defined]
        return chip

    def _create_status_indicator(self) -> QLabel:
        """Create the coloured circle indicator pixmap."""
        label = QLabel()
        label.setFixedSize(14, 14)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._indicator = label
        self._set_indicator_color(QColor("#4a4a5e"))  # Neutral for IDLE
        return label

    def _set_indicator_color(self, color: QColor) -> None:
        """Paint a small circle pixmap with the given colour."""
        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.end()

        self._indicator.setPixmap(pixmap)

    # ── Blink timer ─────────────────────────────────────────────────────────

    def _on_blink_timeout(self) -> None:
        """Toggle blink visibility for the recording indicator."""
        self._blink_visible = not self._blink_visible
        if self._blink_visible:
            self._set_indicator_color(QColor("#ef4444"))  # Red
        else:
            self._set_indicator_color(QColor("#15151f"))  # Dark (hidden)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state) -> None:
        """Update the indicator colour and status text based on recording state."""
        from ..app import RecordingState

        self._state = state
        self._blink_timer.stop()
        self._blink_visible = True

        if state == RecordingState.IDLE:
            self._set_indicator_color(QColor("#4a4a5e"))  # Neutral
            self._status_label.setText("Ready")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #9090a8;"
            )
        elif state == RecordingState.RECORDING:
            self._set_indicator_color(QColor("#ef4444"))  # Red
            self._status_label.setText("Recording")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #ef4444;"
            )
            self._blink_timer.start()
        elif state == RecordingState.PAUSED:
            self._set_indicator_color(QColor("#f59e0b"))  # Amber
            self._status_label.setText("Paused")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #f59e0b;"
            )

        logger.debug("StatusBar state updated: %s", state.name if state else "None")

    def show_saving_indicator(self) -> None:
        """Show a 'Saving…' status while the final MP4 is being muxed.

        Uses a steady amber indicator (no blink — muxing is not recording)
        and a 'Saving…' label so the user knows the app is still working
        even though the recording has stopped.
        """
        self._blink_timer.stop()
        self._blink_visible = True
        self._set_indicator_color(QColor("#f59e0b"))  # Amber
        self._status_label.setText("Saving…")
        self._status_label.setStyleSheet(
            "font-weight: 600; font-size: 13px; color: #f59e0b;"
        )
        logger.debug("StatusBar showing saving indicator")

    def update_duration(self, seconds: float) -> None:
        """Update the elapsed duration display."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        self._duration_label._value_label.setText(text)
        self.recording_duration_changed.emit(seconds)

    def update_fps(self, fps: float) -> None:
        """Update the FPS display."""
        self._fps_label._value_label.setText(f"{fps:.0f}")
