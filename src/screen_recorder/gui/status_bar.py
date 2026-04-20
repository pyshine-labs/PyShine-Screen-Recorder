"""Status bar widget — displays recording state, duration, file size, and FPS.

Provides a :class:`StatusBar` widget that shows a coloured recording-state
indicator, status text, elapsed duration, estimated file size, and current
frames-per-second.
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
        """Build the status bar layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        # Recording state indicator (coloured circle)
        self._indicator = self._create_status_indicator()
        layout.addWidget(self._indicator)

        # Status text label
        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Duration label
        self._duration_label = QLabel("00:00:00")
        self._duration_label.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        layout.addWidget(self._duration_label)

        # File size label
        self._file_size_label = QLabel("0 MB")
        self._file_size_label.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        layout.addWidget(self._file_size_label)

        # FPS label
        self._fps_label = QLabel("0 fps")
        self._fps_label.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        layout.addWidget(self._fps_label)

        # Set overall status bar style
        self.setStyleSheet(
            "StatusBar { "
            "  background-color: #181828; "
            "  border-top: 1px solid #2d2d44; "
            "}"
        )

    def _create_status_indicator(self) -> QLabel:
        """Create the coloured circle indicator pixmap.

        Returns:
            A :class:`QLabel` displaying a small coloured circle.
        """
        label = QLabel()
        label.setFixedSize(16, 16)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._indicator = label  # Assign before calling _set_indicator_color
        self._set_indicator_color(QColor("#555570"))  # Gray for IDLE
        return label

    def _set_indicator_color(self, color: QColor) -> None:
        """Paint a small circle pixmap with the given colour and set it on the indicator.

        Args:
            color: The fill colour for the indicator circle.
        """
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
        """Update the indicator colour and status text based on recording state.

        Args:
            state: A :class:`RecordingState` enum value (IDLE, RECORDING, PAUSED).
        """
        from ..app import RecordingState

        self._state = state

        # Stop blink timer by default
        self._blink_timer.stop()
        self._blink_visible = True

        if state == RecordingState.IDLE:
            self._set_indicator_color(QColor("#555570"))  # Gray
            self._status_label.setText("Ready")
        elif state == RecordingState.RECORDING:
            self._set_indicator_color(QColor("#ef4444"))  # Red
            self._status_label.setText("Recording…")
            self._blink_timer.start()
        elif state == RecordingState.PAUSED:
            self._set_indicator_color(QColor("#facc15"))  # Yellow
            self._status_label.setText("Paused")

        logger.debug("StatusBar state updated: %s", state.name if state else "None")

    def update_duration(self, seconds: float) -> None:
        """Update the elapsed duration display.

        Args:
            seconds: Elapsed recording time in seconds.
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        self._duration_label.setText(text)
        self.recording_duration_changed.emit(seconds)

    def update_file_size(self, size_bytes: int) -> None:
        """Update the file size display.

        Args:
            size_bytes: Current recording file size in bytes.
        """
        if size_bytes >= 1_073_741_824:  # ≥ 1 GB
            value = size_bytes / 1_073_741_824
            self._file_size_label.setText(f"{value:.1f} GB")
        else:
            value = size_bytes / 1_048_576  # Convert to MB
            self._file_size_label.setText(f"{value:.1f} MB")

    def update_fps(self, fps: float) -> None:
        """Update the FPS display.

        Args:
            fps: Current frames per second.
        """
        self._fps_label.setText(f"{fps:.0f} fps")