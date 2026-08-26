"""Audio level meter widget — displays real-time stereo audio levels.

Provides :class:`AudioLevelMeter` that renders two horizontal bars
(Left / Right) using :class:`QPainter`, with a gradient from green
through amber to red and slow-decaying peak indicators.  The horizontal
layout keeps the meter narrow so it fits beside the controls in a
compact main window.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..utils.logger import logger


class AudioLevelMeter(QWidget):
    """Real-time stereo audio level meter with horizontal bars.

    Displays two horizontal bars (L and R channels) stacked vertically,
    each filling left→right with a green→amber→red gradient and white
    peak-hold markers that decay slowly.

    Attributes:
        _left_level: Current left channel level (0.0–1.0).
        _right_level: Current right channel level (0.0–1.0).
        _left_peak: Current left channel peak level.
        _right_peak: Current right channel peak level.
    """

    # Geometry — horizontal bars stacked vertically
    BAR_HEIGHT = 8          # Thickness of each bar
    BAR_SPACING = 4         # Vertical gap between L and R bars
    SIDE_MARGIN = 14        # Left/right margin (for "L" / "R" label)
    TOP_MARGIN = 2
    BOTTOM_MARGIN = 2
    PEAK_DECAY = 0.02       # Peak falloff per paint cycle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._left_level: float = 0.0
        self._right_level: float = 0.0
        self._left_peak: float = 0.0
        self._right_peak: float = 0.0
        self._enabled: bool = True

        # Narrow horizontal meter — fits beside the control buttons.
        self.setMinimumSize(140, 28)
        self.setFixedHeight(28)
        logger.debug("AudioLevelMeter initialized (horizontal)")

    # ── Qt overrides ────────────────────────────────────────────────────────

    def minimumSizeHint(self) -> QSize:
        return QSize(140, 28)

    def sizeHint(self) -> QSize:
        return QSize(180, 28)

    def paintEvent(self, event) -> None:  # noqa: N802 – Qt naming convention
        """Draw the two horizontal level bars with gradient fills and peak markers."""
        if not self._enabled:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = w - 2 * self.SIDE_MARGIN
        if bar_w <= 0:
            painter.end()
            return

        # ── Gradient (green → amber → red), horizontal ─────────────────
        gradient = QLinearGradient(self.SIDE_MARGIN, 0, self.SIDE_MARGIN + bar_w, 0)
        gradient.setColorAt(0.0, QColor("#22c55e"))   # Green
        gradient.setColorAt(0.7, QColor("#f59e0b"))    # Amber
        gradient.setColorAt(1.0, QColor("#ef4444"))    # Red

        # ── Draw L and R bars ──────────────────────────────────────────
        self._draw_bar(painter, 0, bar_w, self._left_level, self._left_peak, gradient, "L")
        self._draw_bar(
            painter,
            self.BAR_HEIGHT + self.BAR_SPACING,
            bar_w,
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
        y_offset: int,
        bar_w: int,
        level: float,
        peak: float,
        gradient: QLinearGradient,
        label: str,
    ) -> None:
        """Draw a single horizontal level bar with background, fill, peak, label.

        Args:
            painter: Active painter.
            y_offset: Vertical offset from widget top.
            bar_w: Available bar width in pixels.
            level: Current level value (0.0–1.0).
            peak: Current peak value (0.0–1.0).
            gradient: Fill gradient.
            label: Channel label text ("L" or "R").
        """
        y = self.TOP_MARGIN + y_offset

        # ── Background track ────────────────────────────────────────────
        painter.setBrush(QColor("#1a1a24"))
        painter.setPen(QPen(QColor("#232330"), 1))
        painter.drawRoundedRect(self.SIDE_MARGIN, y, bar_w, self.BAR_HEIGHT, 4, 4)

        # ── Level fill (left→right) ────────────────────────────────────
        fill_w = int(bar_w * min(level, 1.0))
        if fill_w > 0:
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.SIDE_MARGIN, y, fill_w, self.BAR_HEIGHT, 4, 4)

        # ── Peak marker (vertical line) ────────────────────────────────
        if peak > 0.01:
            peak_x = self.SIDE_MARGIN + int(bar_w * min(peak, 1.0))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(peak_x, y + 1, peak_x, y + self.BAR_HEIGHT - 1)

        # ── Channel label (left of bar) ────────────────────────────────
        painter.setPen(QColor("#6a6a82"))
        font = painter.font()
        from PyQt6.QtGui import QFont
        small = QFont(font)
        small.setPointSize(7)
        small.setBold(True)
        painter.setFont(small)
        painter.drawText(2, y + self.BAR_HEIGHT - 1, label)

    # ── Public API ───────────────────────────────────────────────────────────

    def update_levels(self, left: float, right: float) -> None:
        """Update the displayed audio levels.

        Args:
            left: Left channel level (0.0–1.0).
            right: Right channel level (0.0–1.0).
        """
        self._left_level = max(0.0, min(1.0, left))
        self._right_level = max(0.0, min(1.0, right))

        if self._left_level > self._left_peak:
            self._left_peak = self._left_level
        if self._right_level > self._right_peak:
            self._right_peak = self._right_level

        self.update()

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
