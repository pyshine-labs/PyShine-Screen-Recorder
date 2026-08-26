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
        """Build the status bar layout with pill-shaped stat chips."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Recording state indicator (coloured dot + status text)
        self._indicator = self._create_status_indicator()
        layout.addWidget(self._indicator)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            "font-weight: 600; font-size: 13px; color: #e0e0e0;"
        )
        layout.addWidget(self._status_label)

        layout.addStretch()

        # ── Stat chips: Duration | FPS ─────────────────────────────────
        self._duration_label = self._create_stat_chip("⏱", "00:00:00")
        layout.addWidget(self._duration_label)

        self._fps_label = self._create_stat_chip("🎬", "0 fps")
        layout.addWidget(self._fps_label)

        # Overall status bar style — bar appearance with gradient
        self.setStyleSheet(
            "StatusBar { "
            "  background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "    stop:0 #1a1a2e, stop:1 #16213e); "
            "  border-top: 1px solid #3d3d5c; "
            "}"
        )

    def _create_stat_chip(self, icon: str, value: str) -> QLabel:
        """Create a pill-shaped stat chip with icon and value.

        Args:
            icon: Unicode icon character.
            value: Initial value text.

        Returns:
            A styled :class:`QLabel`.
        """
        label = QLabel(f"{icon}  {value}")
        label.setStyleSheet(
            "QLabel { "
            "  background-color: #1e1e2e; "
            "  border: 1px solid #3d3d5c; "
            "  border-radius: 12px; "
            "  padding: 3px 12px; "
            "  font-size: 12px; "
            "  color: #c0c0d0; "
            "  font-weight: 500; "
            "}"
        )
        return label

    def _create_status_indicator(self) -> QLabel:
        """Create the coloured circle indicator pixmap."""
        label = QLabel()
        label.setFixedSize(14, 14)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._indicator = label
        self._set_indicator_color(QColor("#555570"))  # Gray for IDLE
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
            self._set_indicator_color(QColor("#1e1e2e"))  # Dark (hidden)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state) -> None:
        """Update the indicator colour and status text based on recording state."""
        from ..app import RecordingState

        self._state = state
        self._blink_timer.stop()
        self._blink_visible = True

        if state == RecordingState.IDLE:
            self._set_indicator_color(QColor("#555570"))  # Gray
            self._status_label.setText("Ready")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #a0a0b8;"
            )
        elif state == RecordingState.RECORDING:
            self._set_indicator_color(QColor("#ef4444"))  # Red
            self._status_label.setText("Recording")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #ef4444;"
            )
            self._blink_timer.start()
        elif state == RecordingState.PAUSED:
            self._set_indicator_color(QColor("#facc15"))  # Yellow
            self._status_label.setText("Paused")
            self._status_label.setStyleSheet(
                "font-weight: 600; font-size: 13px; color: #facc15;"
            )

        logger.debug("StatusBar state updated: %s", state.name if state else "None")

    def update_duration(self, seconds: float) -> None:
        """Update the elapsed duration display."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        self._duration_label.setText(f"⏱  {text}")
        self.recording_duration_changed.emit(seconds)

    def update_fps(self, fps: float) -> None:
        """Update the FPS display."""
        self._fps_label.setText(f"🎬  {fps:.0f} fps")
