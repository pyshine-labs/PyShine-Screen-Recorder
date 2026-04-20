"""Audio level meter widget — displays real-time stereo audio levels.

Provides a :class:`AudioLevelMeter` that renders two vertical bars
(Left / Right) using :class:`QPainter`, with a gradient from green
through yellow to red and slow-decaying peak indicators.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QGradient, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..utils.logger import logger


class AudioLevelMeter(QWidget):
    """Real-time stereo audio level meter with peak indicators.

    Displays two vertical bars (L and R channels) with a green→yellow→red
    gradient and white peak-hold markers that decay slowly.

    Attributes:
        _left_level: Current left channel level (0.0–1.0).
        _right_level: Current right channel level (0.0–1.0).
        _left_peak: Current left channel peak level.
        _right_peak: Current right channel peak level.
    """

    BAR_WIDTH = 30
    BAR_BOTTOM_MARGIN = 20  # Space for L / R labels
    BAR_TOP_MARGIN = 6
    BAR_SPACING = 10
    PEAK_DECAY = 0.02  # Peak falloff per paint cycle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._left_level: float = 0.0
        self._right_level: float = 0.0
        self._left_peak: float = 0.0
        self._right_peak: float = 0.0
        self._enabled: bool = True

        self.setMinimumSize(80, 150)
        logger.debug("AudioLevelMeter initialized")

    # ── Qt overrides ────────────────────────────────────────────────────────

    def minimumSizeHint(self) -> QSize:
        """Return the minimum size hint for the widget."""
        return QSize(80, 150)

    def paintEvent(self, event) -> None:  # noqa: N802 – Qt naming convention
        """Draw the stereo level bars with gradient fills and peak markers."""
        if not self._enabled:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Dimensions ──────────────────────────────────────────────────
        total_width = 2 * self.BAR_WIDTH + self.BAR_SPACING
        start_x = (self.width() - total_width) // 2
        bar_height = self.height() - self.BAR_BOTTOM_MARGIN - self.BAR_TOP_MARGIN

        if bar_height <= 0:
            painter.end()
            return

        # ── Gradient (green → yellow → red) ────────────────────────────
        gradient = QLinearGradient(0, self.BAR_TOP_MARGIN + bar_height, 0, self.BAR_TOP_MARGIN)
        gradient.setColorAt(0.0, QColor("#4ade80"))   # Green
        gradient.setColorAt(0.7, QColor("#facc15"))    # Yellow
        gradient.setColorAt(1.0, QColor("#ef4444"))    # Red

        # ── Draw bars ────────────────────────────────────────────────────
        self._draw_bar(painter, start_x, bar_height, self._left_level, self._left_peak, gradient, "L")
        self._draw_bar(
            painter,
            start_x + self.BAR_WIDTH + self.BAR_SPACING,
            bar_height,
            self._right_level,
            self._right_peak,
            gradient,
            "R",
        )

        painter.end()

        # ── Decay peaks ─────────────────────────────────────────────────
        self._left_peak = max(0.0, self._left_peak - self.PEAK_DECAY)
        self._right_peak = max(0.0, self._right_peak - self.PEAK_DECAY)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _draw_bar(
        self,
        painter: QPainter,
        x: int,
        bar_height: int,
        level: float,
        peak: float,
        gradient: QLinearGradient,
        label: str,
    ) -> None:
        """Draw a single level bar with background, fill, and peak marker.

        Args:
            painter: Active painter.
            x: Horizontal start position.
            bar_height: Available bar height in pixels.
            level: Current level value (0.0–1.0).
            peak: Current peak value (0.0–1.0).
            gradient: Fill gradient.
            label: Channel label text ("L" or "R").
        """
        y_top = self.BAR_TOP_MARGIN

        # ── Background ──────────────────────────────────────────────────
        painter.setBrush(QColor("#2a2a3e"))
        painter.setPen(QPen(QColor("#3d3d5c"), 1))
        painter.drawRoundedRect(x, y_top, self.BAR_WIDTH, bar_height, 3, 3)

        # ── Level fill ──────────────────────────────────────────────────
        fill_height = int(bar_height * min(level, 1.0))
        if fill_height > 0:
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            fill_y = y_top + bar_height - fill_height
            painter.drawRoundedRect(x, fill_y, self.BAR_WIDTH, fill_height, 3, 3)

        # ── Peak indicator ───────────────────────────────────────────────
        if peak > 0.01:
            peak_y = y_top + bar_height - int(bar_height * min(peak, 1.0))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(x + 2, peak_y, x + self.BAR_WIDTH - 2, peak_y)

        # ── Label ───────────────────────────────────────────────────────
        painter.setPen(QColor("#a0a0b8"))
        painter.setFont(self.font())
        label_rect_x = x + (self.BAR_WIDTH - 10) // 2
        label_rect_y = y_top + bar_height + 2
        painter.drawText(label_rect_x, label_rect_y + 14, label)

    # ── Public API ───────────────────────────────────────────────────────────

    def update_levels(self, left: float, right: float) -> None:
        """Update the displayed audio levels.

        Args:
            left: Left channel level (0.0–1.0).
            right: Right channel level (0.0–1.0).
        """
        self._left_level = max(0.0, min(1.0, left))
        self._right_level = max(0.0, min(1.0, right))

        # Update peaks if current level exceeds them
        if self._left_level > self._left_peak:
            self._left_peak = self._left_level
        if self._right_level > self._right_peak:
            self._right_peak = self._right_level

        self.update()  # Schedule repaint

    def reset(self) -> None:
        """Reset levels and peaks to zero."""
        self._left_level = 0.0
        self._right_level = 0.0
        self._left_peak = 0.0
        self._right_peak = 0.0
        self.update()

    def set_recording_state(self, state) -> None:
        """Enable or disable the meter based on recording state.

        Args:
            state: A :class:`RecordingState` enum value.
        """
        from ..app import RecordingState

        if state == RecordingState.IDLE:
            self._enabled = False
            self.reset()
        else:
            self._enabled = True

        self.update()