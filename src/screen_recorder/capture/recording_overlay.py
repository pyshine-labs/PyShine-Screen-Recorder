"""Recording overlay — lightweight transparent widget showing the capture boundary.

Provides :class:`RecordingOverlay`, a frameless, always-on-top, click-through
widget that draws animated dotted lines around the area currently being recorded.

The overlay is non-interactive (clicks pass through to the underlying apps)
and covers only the recorded region — for fullscreen recording it draws a
border around the entire screen, for region recording it borders the selected
rectangle.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QApplication

from ..utils.logger import logger


class RecordingOverlay(QWidget):
    """Transparent, click-through overlay with animated dotted border.

    Shows the user which area of the screen is currently being recorded
    by drawing an animated marching-ants dotted rectangle around it.

    The overlay is completely non-interactive — it passes all mouse
    events through to the applications below.
    """

    # ── Animation constants ──────────────────────────────────────────
    _DASH_LEN = 8          # Dotted line dash length (px)
    _DASH_GAP = 6          # Gap between dashes (px)
    _ANIM_INTERVAL_MS = 80  # Animation refresh rate (ms)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ── Window flags: frameless, always-on-top, click-through ────
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # ── Translucent, click-through background ─────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # ── Colors ───────────────────────────────────────────────────
        self._border_color = QColor(0, 120, 215, 255)   # Blue
        self._accent_color = QColor(220, 38, 38, 255)    # Red (REC indicator)

        # ── Animation state ─────────────────────────────────────────
        self._dash_offset: float = 0.0
        self._pulse_state: float = 0.0

        # ── Animation timer ─────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._paused = False

    # ── Public API ───────────────────────────────────────────────────

    def show_for_rect(self, rect: QRect) -> None:
        """Show the overlay bordering the given rectangle.

        Args:
            rect: The screen rectangle (in virtual screen coords) that is
                  being recorded. The overlay will cover this area plus
                  a small margin for the border.
        """
        if not rect.isValid() or rect.isNull():
            logger.warning("RecordingOverlay: invalid rect %s", rect)
            return

        # Resize widget to exactly the recorded rectangle.
        # The border is drawn inside the widget edges.
        self.setGeometry(rect)

        self._paused = False
        if not self._timer.isActive():
            self._timer.start(self._ANIM_INTERVAL_MS)

        self.show()
        self.raise_()
        logger.info("RecordingOverlay shown for rect: %s", rect)

    def show_fullscreen(self, monitor_index: int = 0) -> None:
        """Show the overlay bordering the entire screen.

        Args:
            monitor_index: The monitor to cover (0 = primary).
        """
        screens = QApplication.screens()
        if monitor_index < 0 or monitor_index >= len(screens):
            monitor_index = 0
        rect = screens[monitor_index].geometry()
        self.show_for_rect(rect)

    def pause_animation(self, paused: bool) -> None:
        """Pause/resume the marching-ants animation (for pause state).

        Args:
            paused: True to freeze the animation, False to resume.
        """
        self._paused = paused
        if paused:
            self._timer.stop()
        else:
            if not self._timer.isActive():
                self._timer.start(self._ANIM_INTERVAL_MS)

    def hide_overlay(self) -> None:
        """Hide the overlay and stop the animation."""
        self._timer.stop()
        self.hide()
        logger.info("RecordingOverlay hidden")

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 – Qt naming
        """Draw the animated dotted border around the recorded area."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        # Draw border inside the widget bounds
        border_rect = self.rect().adjusted(0, 0, -1, -1)

        # ── Animated dotted line (marching ants) ──────────────────────
        # Alternate colors for a visible marching effect:
        #   blue dashes with red offset gaps
        pen = QPen(self._border_color, 2)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        dash_pattern = [
            float(self._DASH_LEN), float(self._DASH_GAP),
            float(self._DASH_LEN), float(self._DASH_GAP),
        ]
        pen.setDashPattern(dash_pattern)
        pen.setDashOffset(self._dash_offset)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(border_rect)

        # ── Secondary offset line for depth (red, offset by half) ────
        pen2 = QPen(self._accent_color, 2)
        pen2.setStyle(Qt.PenStyle.CustomDashLine)
        pen2.setDashPattern(dash_pattern)
        pen2.setDashOffset(self._dash_offset + (self._DASH_LEN + self._DASH_GAP) / 2.0)
        painter.setPen(pen2)
        painter.drawRect(border_rect)

        # ── REC indicator (top-left corner badge) ────────────────────
        badge_size = 8
        badge_margin = 8
        badge_x = badge_margin
        badge_y = badge_margin
        # Pulse opacity for visibility
        alpha = int(180 + 75 * (0.5 + 0.5 * self._pulse_state))
        pulse_color = QColor(220, 38, 38, min(255, alpha))
        painter.setBrush(pulse_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(badge_x + badge_size / 2,
                                    badge_y + badge_size / 2),
                            badge_size / 2, badge_size / 2)

        # ── "REC" text next to the badge ──────────────────────────────
        painter.setPen(QColor(255, 255, 255, 230))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_x + badge_size + 6, badge_y + badge_size + 2, "REC")

    # ── Internal ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        """Advance the animation offset for the marching-ants effect."""
        if not self._paused:
            self._dash_offset -= 1.0  # Move dashes inward
            if self._dash_offset < -(self._DASH_LEN + self._DASH_GAP):
                self._dash_offset = 0.0
            self._pulse_state = (self._pulse_state + 0.15) % 2.0
            self.update()  # Trigger repaint
