"""Recording overlay — lightweight transparent widget showing the capture boundary.

Provides :class:`RecordingOverlay`, a frameless, always-on-top, click-through
widget that draws animated dotted lines around the area currently being recorded.

The overlay is non-interactive (clicks pass through to the underlying apps)
and covers only the recorded region — for fullscreen recording it draws a
border around the entire screen, for region recording it borders the selected
rectangle.

**Capture-exclusion strategy:** the widget is expanded by ``_BORDER_MARGIN``
pixels on every side so the animated border is drawn OUTSIDE the recorded
rectangle. The C++ DXGI capture engine only reads pixels INSIDE the region,
so the border is never part of the video — no reliance on
``SetWindowDisplayAffinity`` (which may be unsupported on older Windows).
"""

from __future__ import annotations

import ctypes

from PyQt6.QtCore import Qt, QRect, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QApplication

from ..utils.logger import logger

# ── Win32 SetWindowDisplayAffinity (belt-and-suspenders, may not be supported) ─
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
_USER32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_USER32.SetWindowDisplayAffinity.restype = ctypes.c_int


def _exclude_from_capture(hwnd) -> bool:
    """Best-effort exclusion of a window from screen capture (Win10 2004+)."""
    try:
        return bool(_USER32.SetWindowDisplayAffinity(
            ctypes.c_void_p(int(hwnd)), _WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


class RecordingOverlay(QWidget):
    """Transparent, click-through overlay with animated dotted border.

    Shows the user which area of the screen is currently being recorded
    by drawing an animated marching-ants dotted rectangle around it.

    The border is drawn in a margin OUTSIDE the recorded rectangle so it
    is visible on screen but never captured in the recorded video.
    """

    # ── Layout / animation constants ─────────────────────────────────
    _BORDER_MARGIN = 8           # Px outside the recorded rect (border + badge live here)
    _DASH_LEN = 8               # Dotted line dash length (px)
    _DASH_GAP = 6               # Gap between dashes (px)
    _ANIM_INTERVAL_MS = 80      # Animation refresh rate (ms)
    _BADGE_SIZE = 6             # REC dot diameter (must fit in margin)

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
        self._accent_color = QColor(220, 38, 38, 255)    # Red (REC dot)

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

        The widget is expanded by ``_BORDER_MARGIN`` on all sides so the
        border is drawn OUTSIDE the captured region and never appears in
        the recorded video.

        Args:
            rect: The screen rectangle (in virtual screen coords) that is
                  being recorded.
        """
        if not rect.isValid() or rect.isNull():
            logger.warning("RecordingOverlay: invalid rect %s", rect)
            return

        m = self._BORDER_MARGIN
        # Expand geometry so the border ring sits outside the recorded pixels.
        self.setGeometry(rect.adjusted(-m, -m, m, m))

        self._paused = False
        if not self._timer.isActive():
            self._timer.start(self._ANIM_INTERVAL_MS)

        self.show()
        self.raise_()

        # Best-effort DWM capture exclusion (works on Win10 2004+).
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        _exclude_from_capture(int(self.winId()))

        logger.info("RecordingOverlay shown for rect: %s (margin=%d)", rect, m)

    def show_fullscreen(self, monitor_index: int = 0) -> None:
        """Show the overlay bordering the entire screen."""
        screens = QApplication.screens()
        if monitor_index < 0 or monitor_index >= len(screens):
            monitor_index = 0
        rect = screens[monitor_index].geometry()
        self.show_for_rect(rect)

    def pause_animation(self, paused: bool) -> None:
        """Pause/resume the marching-ants animation."""
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

    # ── Qt event hooks ────────────────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802 – Qt naming
        """Re-apply capture exclusion whenever the window is shown."""
        super().showEvent(event)
        _exclude_from_capture(int(self.winId()))

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 – Qt naming
        """Draw the animated dotted border and REC dot in the margin ring.

        All drawing happens within ``_BORDER_MARGIN`` pixels of the widget
        edge — i.e. OUTSIDE the recorded rectangle — so nothing leaks into
        the captured video.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Border at the very outer edge of the widget (inside the margin ring).
        border_rect = self.rect().adjusted(0, 0, -1, -1)

        # ── Animated dotted line (marching ants, blue) ───────────────
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

        # ── REC dot (top-left corner, inside the margin ring) ────────
        # Fits entirely within _BORDER_MARGIN so it's outside the captured rect.
        badge_x = 1.0
        badge_y = 1.0
        alpha = int(180 + 75 * (0.5 + 0.5 * self._pulse_state))
        pulse_color = QColor(220, 38, 38, min(255, alpha))
        painter.setBrush(pulse_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QPointF(badge_x + self._BADGE_SIZE / 2,
                    badge_y + self._BADGE_SIZE / 2),
            self._BADGE_SIZE / 2, self._BADGE_SIZE / 2)

    # ── Internal ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        """Advance the animation offset for the marching-ants effect."""
        if not self._paused:
            self._dash_offset -= 1.0  # Move dashes inward
            if self._dash_offset < -(self._DASH_LEN + self._DASH_GAP):
                self._dash_offset = 0.0
            self._pulse_state = (self._pulse_state + 0.15) % 2.0
            self.update()  # Trigger repaint
