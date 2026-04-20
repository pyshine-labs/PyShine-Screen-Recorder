"""Region selector overlay — transparent fullscreen widget for selecting a capture region.

Provides :class:`RegionSelectorOverlay`, a semi-transparent fullscreen widget
that allows the user to click-and-drag to define a rectangular region of the
screen to capture.  The selected region is communicated via Qt signals.

The selector features a professional workflow:
  1. Click-and-drag to draw the initial selection
  2. Adjust using 8 resize handles or drag to move
  3. Preview the captured region in a thumbnail
  4. Confirm (✓ button or Enter) or cancel (✕ button or Escape)
"""

from __future__ import annotations

from enum import Enum, auto

from PyQt6.QtCore import Qt, QRect, pyqtSignal, QPoint
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QFont,
    QCursor,
    QPixmap,
    QFontMetrics,
)
from PyQt6.QtWidgets import QWidget, QApplication

from ..utils.logger import logger


# ── Constants ────────────────────────────────────────────────────────────────

_HANDLE_SIZE = 8          # Resize handle square side length (px)
_MIN_SELECTION = 10       # Minimum selection width/height (px)
_PREVIEW_MAX_W = 200      # Preview thumbnail max width (px)
_PREVIEW_MAX_H = 150      # Preview thumbnail max height (px)
_BTN_HEIGHT = 32           # Button height (px)
_BTN_PADDING = 12         # Horizontal padding inside buttons (px)
_BTN_SPACING = 8          # Gap between Confirm and Cancel buttons (px)
_BTN_RADIUS = 6           # Button corner radius (px)


# ── Internal enums ───────────────────────────────────────────────────────────

class _State(Enum):
    """State machine for the region selector overlay."""
    IDLE = auto()       # No selection yet
    DRAWING = auto()    # Mouse is pressed, drawing the rectangle
    ADJUSTING = auto()  # Selection visible with handles/buttons/preview
    CONFIRMED = auto()  # User confirmed the selection (transient)


class _Handle(Enum):
    """Resize handle positions around the selection rectangle."""
    TOP_LEFT = auto()
    TOP = auto()
    TOP_RIGHT = auto()
    RIGHT = auto()
    BOTTOM_RIGHT = auto()
    BOTTOM = auto()
    BOTTOM_LEFT = auto()
    LEFT = auto()


# ── Cursor mapping for each handle ──────────────────────────────────────────

_HANDLE_CURSORS: dict[_Handle, Qt.CursorShape] = {
    _Handle.TOP_LEFT:     Qt.CursorShape.SizeFDiagCursor,
    _Handle.TOP:          Qt.CursorShape.SizeVerCursor,
    _Handle.TOP_RIGHT:    Qt.CursorShape.SizeBDiagCursor,
    _Handle.RIGHT:        Qt.CursorShape.SizeHorCursor,
    _Handle.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    _Handle.BOTTOM:       Qt.CursorShape.SizeVerCursor,
    _Handle.BOTTOM_LEFT:  Qt.CursorShape.SizeBDiagCursor,
    _Handle.LEFT:         Qt.CursorShape.SizeHorCursor,
}


# ── Main class ───────────────────────────────────────────────────────────────

class RegionSelectorOverlay(QWidget):
    """A transparent fullscreen overlay for selecting a screen region.

    The overlay covers the entire virtual screen (all monitors) with a
    semi-transparent dark layer.  The user can click-and-drag to define a
    rectangular selection which is shown as a clear (non-darkened) area
    with a blue border, resize handles, dimension/position labels, and
    confirm/cancel buttons.

    After drawing, the selection persists in the ADJUSTING state where
    the user can:

    - Drag any of 8 resize handles to adjust the selection size
    - Click inside the selection and drag to move it
    - Click ✓ Confirm or press Enter to confirm
    - Click ✕ Cancel or press Escape to cancel
    - View a live preview thumbnail of the selected region

    Signals:
        region_selected: Emitted with a :class:`QRect` when the user
            confirms a selection.
        selection_cancelled: Emitted when the user cancels selection.
    """

    region_selected = pyqtSignal(QRect)
    selection_cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ── Window flags: frameless, always-on-top, tool window ─────
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # ── Translucent background ──────────────────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── State machine ───────────────────────────────────────────
        self._state: _State = _State.IDLE

        # ── Selection state ─────────────────────────────────────────
        self._start_pos: QPoint | None = None
        self._end_pos: QPoint | None = None
        self._selection_rect: QRect = QRect()

        # ── Handle / move drag state ────────────────────────────────
        self._active_handle: _Handle | None = None
        self._is_moving: bool = False
        self._drag_origin: QPoint = QPoint()
        self._drag_rect_origin: QRect = QRect()

        # ── Button hover state ──────────────────────────────────────
        self._confirm_hovered: bool = False
        self._cancel_hovered: bool = False

        # ── Preview cache ───────────────────────────────────────────
        self._preview_pixmap: QPixmap | None = None
        self._preview_rect_cache: QRect = QRect()

        # ── Appearance ──────────────────────────────────────────────
        self._overlay_color = QColor(0, 0, 0, 180)
        self._border_color = QColor(0, 120, 215)  # Blue accent
        self._border_width: int = 2
        self._label_font = QFont("Segoe UI", 10)
        self._button_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self._handle_fill = QColor(255, 255, 255)
        self._handle_border = QColor(0, 120, 215)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def start_selection(self) -> None:
        """Show the overlay on all screens and begin region selection.

        The widget is resized to cover the entire virtual screen and
        shown in a modal-like fashion.  The cursor is changed to a
        crosshair.
        """
        logger.info("Starting region selection")

        # Determine the virtual screen geometry (union of all screens)
        virtual_rect = QRect()
        for screen in QApplication.screens():
            virtual_rect = virtual_rect.united(screen.geometry())

        self.setGeometry(virtual_rect)

        # Reset all state
        self._state = _State.IDLE
        self._start_pos = None
        self._end_pos = None
        self._selection_rect = QRect()
        self._active_handle = None
        self._is_moving = False
        self._confirm_hovered = False
        self._cancel_hovered = False
        self._preview_pixmap = None
        self._preview_rect_cache = QRect()

        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.show()
        self.activateWindow()
        self.setFocus()

    def get_selected_region(self) -> QRect:
        """Return the current selection rectangle.

        Returns:
            A :class:`QRect` describing the selected region, or a null
            rect if no selection has been made.
        """
        return self._selection_rect

    # ── Handle geometry ──────────────────────────────────────────────────────

    def _get_handle_rects(self) -> dict[_Handle, QRect]:
        """Return the 8 handle rects for the current selection."""
        r = self._selection_rect
        hs = _HANDLE_SIZE
        half = hs // 2

        return {
            _Handle.TOP_LEFT:     QRect(r.left() - half, r.top() - half, hs, hs),
            _Handle.TOP:          QRect(r.center().x() - half, r.top() - half, hs, hs),
            _Handle.TOP_RIGHT:    QRect(r.right() - half + 1, r.top() - half, hs, hs),
            _Handle.RIGHT:        QRect(r.right() - half + 1, r.center().y() - half, hs, hs),
            _Handle.BOTTOM_RIGHT: QRect(r.right() - half + 1, r.bottom() - half + 1, hs, hs),
            _Handle.BOTTOM:       QRect(r.center().x() - half, r.bottom() - half + 1, hs, hs),
            _Handle.BOTTOM_LEFT:  QRect(r.left() - half, r.bottom() - half + 1, hs, hs),
            _Handle.LEFT:         QRect(r.left() - half, r.center().y() - half, hs, hs),
        }

    def _hit_test_handle(self, pos: QPoint) -> _Handle | None:
        """Return which handle is under *pos*, or ``None``."""
        for handle, rect in self._get_handle_rects().items():
            if rect.contains(pos):
                return handle
        return None

    def _hit_test_move(self, pos: QPoint) -> bool:
        """Return ``True`` if *pos* is inside the selection but not on a handle."""
        return self._selection_rect.contains(pos) and self._hit_test_handle(pos) is None

    # ── Button geometry ──────────────────────────────────────────────────────

    def _get_confirm_button_rect(self) -> QRect:
        """Return the rect for the ✓ Confirm button."""
        if not self._selection_rect.isValid():
            return QRect()

        fm = QFontMetrics(self._button_font)
        text_w = fm.horizontalAdvance("✓ Confirm")
        btn_w = text_w + _BTN_PADDING * 2

        # Position: centered below the selection
        bar_x = self._selection_rect.center().x() - (btn_w + _BTN_SPACING + 80) // 2
        bar_y = self._selection_rect.bottom() + 10

        return QRect(bar_x, bar_y, btn_w, _BTN_HEIGHT)

    def _get_cancel_button_rect(self) -> QRect:
        """Return the rect for the ✕ Cancel button."""
        confirm = self._get_confirm_button_rect()
        if not confirm.isValid():
            return QRect()

        fm = QFontMetrics(self._button_font)
        text_w = fm.horizontalAdvance("✕ Cancel")
        btn_w = text_w + _BTN_PADDING * 2

        return QRect(confirm.right() + _BTN_SPACING, confirm.top(), btn_w, _BTN_HEIGHT)

    def _hit_test_confirm(self, pos: QPoint) -> bool:
        """Return ``True`` if *pos* is inside the Confirm button."""
        return self._get_confirm_button_rect().contains(pos)

    def _hit_test_cancel(self, pos: QPoint) -> bool:
        """Return ``True`` if *pos* is inside the Cancel button."""
        return self._get_cancel_button_rect().contains(pos)

    # ── Cursor management ────────────────────────────────────────────────────

    def _update_cursor(self, pos: QPoint) -> None:
        """Set the cursor shape based on what is under *pos*."""
        if self._state == _State.DRAWING:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        if self._state != _State.ADJUSTING:
            return

        # Handles have highest priority
        handle = self._hit_test_handle(pos)
        if handle is not None:
            self.setCursor(QCursor(_HANDLE_CURSORS[handle]))
            return

        # Buttons
        if self._hit_test_confirm(pos) or self._hit_test_cancel(pos):
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            return

        # Move area
        if self._hit_test_move(pos):
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return

        # Default
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ── Preview ──────────────────────────────────────────────────────────────

    def _update_preview(self) -> None:
        """Capture a screenshot of the selected region for the thumbnail.

        The preview is cached and only re-captured when the selection
        rectangle changes, to avoid performance issues.
        """
        if not self._selection_rect.isValid() or self._selection_rect.isNull():
            self._preview_pixmap = None
            return

        # Only re-capture if the rect changed
        if self._selection_rect == self._preview_rect_cache and self._preview_pixmap is not None:
            return

        self._preview_rect_cache = QRect(self._selection_rect)

        # Find which screen the selection centre is on
        screen = QApplication.screenAt(self._selection_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            self._preview_pixmap = None
            return

        try:
            full_pixmap = screen.grabWindow(0)
            geo = screen.geometry()

            # Map selection rect to screen-local coordinates
            local_rect = QRect(
                self._selection_rect.left() - geo.left(),
                self._selection_rect.top() - geo.top(),
                self._selection_rect.width(),
                self._selection_rect.height(),
            ).intersected(QRect(0, 0, full_pixmap.width(), full_pixmap.height()))

            if local_rect.isValid() and local_rect.width() > 0 and local_rect.height() > 0:
                cropped = full_pixmap.copy(local_rect)
                self._preview_pixmap = cropped.scaled(
                    _PREVIEW_MAX_W, _PREVIEW_MAX_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                self._preview_pixmap = None
        except Exception:
            logger.debug("Failed to capture preview thumbnail", exc_info=True)
            self._preview_pixmap = None

    # ── Confirm / Cancel ─────────────────────────────────────────────────────

    def _confirm_selection(self) -> None:
        """Confirm the current selection and emit ``region_selected``."""
        if self._selection_rect.isValid() and not self._selection_rect.isNull():
            # Enforce minimum size
            if (self._selection_rect.width() < _MIN_SELECTION
                    or self._selection_rect.height() < _MIN_SELECTION):
                logger.debug("Selection too small (%s), cancelling", self._selection_rect.size())
                self._cancel_selection()
                return

            self._state = _State.CONFIRMED
            logger.info("Region confirmed: %s", self._selection_rect)
            self.hide()
            self.region_selected.emit(self._selection_rect)
        else:
            logger.debug("No valid selection to confirm")

    def _cancel_selection(self) -> None:
        """Cancel the selection and emit ``selection_cancelled``."""
        self._state = _State.IDLE
        self._selection_rect = QRect()
        logger.info("Region selection cancelled")
        self.hide()
        self.selection_cancelled.emit()

    # ── Painting ──────────────────────────────────────────────────────────────

    def _paint_event(self, event) -> None:  # noqa: ANN001 — Qt event
        """Draw the dark overlay with the clear selection rectangle."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Dark overlay over the entire widget ─────────────────────
        painter.fillRect(self.rect(), self._overlay_color)

        if self._selection_rect.isValid() and not self._selection_rect.isNull():
            # ── Clear (transparent) the selected region ─────────────
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self._selection_rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # ── Blue border around selection ────────────────────────
            pen = QPen(self._border_color, self._border_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._selection_rect)

            # ── Dimension label (W × H) above selection ─────────────
            width = self._selection_rect.width()
            height = self._selection_rect.height()
            dim_text = f"{width} × {height}"

            painter.setFont(self._label_font)
            font_metrics = painter.fontMetrics()
            dim_br = font_metrics.boundingRect(dim_text)

            label_y = self._selection_rect.top() - dim_br.height() - 6
            if label_y < 0:
                label_y = self._selection_rect.bottom() + 6

            bg_rect = dim_br.adjusted(-4, -2, 4, 2)
            bg_rect.moveCenter(
                QPoint(self._selection_rect.center().x(),
                       label_y + dim_br.height() // 2)
            )
            painter.fillRect(bg_rect, QColor(0, 120, 215, 220))

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, dim_text)

            # ── Position label (X, Y) at top-left of selection ──────
            pos_text = f"{self._selection_rect.x()}, {self._selection_rect.y()}"
            pos_br = font_metrics.boundingRect(pos_text)

            pos_bg = pos_br.adjusted(-4, -2, 4, 2)
            pos_bg.moveTopLeft(QPoint(
                self._selection_rect.left(),
                self._selection_rect.top() - pos_bg.height() - 4,
            ))

            # If it would overlap with the dimension label, move it inside
            dim_label_bottom = label_y + dim_br.height() // 2 + dim_br.height() // 2 + 4
            if pos_bg.top() < dim_label_bottom and pos_bg.bottom() > label_y - dim_br.height() // 2 - 4:
                pos_bg.moveTopLeft(QPoint(
                    self._selection_rect.left() + 4,
                    self._selection_rect.top() + 4,
                ))

            painter.fillRect(pos_bg, QColor(0, 0, 0, 160))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(pos_bg, Qt.AlignmentFlag.AlignCenter, pos_text)

            # ── ADJUSTING-state extras ──────────────────────────────
            if self._state == _State.ADJUSTING:
                self._draw_handles(painter)
                self._draw_preview(painter)
                self._draw_buttons(painter)

        painter.end()

    # ── Handle drawing ───────────────────────────────────────────────────────

    def _draw_handles(self, painter: QPainter) -> None:
        """Draw the 8 resize handle knobs."""
        pen = QPen(self._handle_border, 1)
        painter.setPen(pen)
        painter.setBrush(self._handle_fill)

        for rect in self._get_handle_rects().values():
            painter.drawRect(rect)

    # ── Preview drawing ──────────────────────────────────────────────────────

    def _draw_preview(self, painter: QPainter) -> None:
        """Draw the preview thumbnail in the bottom-right corner of the selection."""
        self._update_preview()

        if self._preview_pixmap is None:
            return

        pm = self._preview_pixmap
        margin = 8

        # Position in the bottom-right corner of the selection
        px = self._selection_rect.right() - pm.width() - margin
        py = self._selection_rect.bottom() - pm.height() - margin

        # Draw drop shadow
        shadow_offset = 3
        shadow_rect = QRect(
            px + shadow_offset, py + shadow_offset,
            pm.width(), pm.height(),
        )
        painter.fillRect(shadow_rect, QColor(0, 0, 0, 80))

        # Draw border with rounded corners
        border_rect = QRect(px - 2, py - 2, pm.width() + 4, pm.height() + 4)
        painter.setPen(QPen(self._border_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(border_rect, 4, 4)

        # Draw the pixmap
        painter.drawPixmap(px, py, pm)

    # ── Button drawing ──────────────────────────────────────────────────────

    def _draw_buttons(self, painter: QPainter) -> None:
        """Draw the Confirm and Cancel buttons below the selection."""
        confirm_rect = self._get_confirm_button_rect()
        cancel_rect = self._get_cancel_button_rect()

        if not confirm_rect.isValid():
            return

        # ── Confirm button ──────────────────────────────────────────
        if self._confirm_hovered:
            confirm_bg = QColor(0, 160, 70, 220)
        else:
            confirm_bg = QColor(0, 120, 50, 180)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(confirm_bg)
        painter.drawRoundedRect(confirm_rect, _BTN_RADIUS, _BTN_RADIUS)

        # Button border
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(confirm_rect, _BTN_RADIUS, _BTN_RADIUS)

        painter.setFont(self._button_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(confirm_rect, Qt.AlignmentFlag.AlignCenter, "✓ Confirm")

        # ── Cancel button ──────────────────────────────────────────
        if self._cancel_hovered:
            cancel_bg = QColor(220, 50, 50, 220)
        else:
            cancel_bg = QColor(180, 35, 35, 180)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(cancel_bg)
        painter.drawRoundedRect(cancel_rect, _BTN_RADIUS, _BTN_RADIUS)

        # Button border
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(cancel_rect, _BTN_RADIUS, _BTN_RADIUS)

        painter.setFont(self._button_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(cancel_rect, Qt.AlignmentFlag.AlignCenter, "✕ Cancel")

    # Qt paintEvent override
    def paintEvent(self, event) -> None:  # noqa: N802
        self._paint_event(event)

    # ── Mouse events ─────────────────────────────────────────────────────────

    def _mouse_press_event(self, event) -> None:  # noqa: ANN001
        """Handle mouse press based on current state."""
        if event.button() != Qt.MouseButton.LeftButton:
            # Right-click cancels during ADJUSTING
            if event.button() == Qt.MouseButton.RightButton and self._state == _State.ADJUSTING:
                self._cancel_selection()
            return

        pos = event.globalPosition().toPoint()

        if self._state == _State.IDLE:
            # Start drawing a new selection
            self._state = _State.DRAWING
            self._start_pos = pos
            self._end_pos = pos
            self._selection_rect = QRect(pos, pos)
            self._preview_pixmap = None
            self._preview_rect_cache = QRect()
            self.update()

        elif self._state == _State.ADJUSTING:
            # Check buttons first (highest priority)
            if self._hit_test_confirm(pos):
                self._confirm_selection()
                return
            if self._hit_test_cancel(pos):
                self._cancel_selection()
                return

            # Check resize handles
            handle = self._hit_test_handle(pos)
            if handle is not None:
                self._active_handle = handle
                self._drag_origin = pos
                self._drag_rect_origin = QRect(self._selection_rect)
                return

            # Check move (inside selection, not on handle)
            if self._hit_test_move(pos):
                self._is_moving = True
                self._drag_origin = pos
                self._drag_rect_origin = QRect(self._selection_rect)
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return

            # Click outside selection — start a new drawing
            self._state = _State.DRAWING
            self._start_pos = pos
            self._end_pos = pos
            self._selection_rect = QRect(pos, pos)
            self._preview_pixmap = None
            self._preview_rect_cache = QRect()
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._mouse_press_event(event)

    def _mouse_move_event(self, event) -> None:  # noqa: ANN001
        """Handle mouse move based on current state."""
        pos = event.globalPosition().toPoint()

        if self._state == _State.DRAWING:
            if self._start_pos is not None:
                self._end_pos = pos
                self._selection_rect = QRect(self._start_pos, self._end_pos).normalized()
                self.update()

        elif self._state == _State.ADJUSTING:
            if self._active_handle is not None:
                # Resizing via handle
                self._resize_by_handle(pos)
                self.update()
            elif self._is_moving:
                # Moving the entire selection
                delta = pos - self._drag_origin
                self._selection_rect = self._drag_rect_origin.translated(delta)
                self.update()
            else:
                # Update cursor and button hover state
                old_confirm = self._confirm_hovered
                old_cancel = self._cancel_hovered
                self._confirm_hovered = self._hit_test_confirm(pos)
                self._cancel_hovered = self._hit_test_cancel(pos)
                self._update_cursor(pos)
                if self._confirm_hovered != old_confirm or self._cancel_hovered != old_cancel:
                    self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._mouse_move_event(event)

    def _mouse_release_event(self, event) -> None:  # noqa: ANN001
        """Handle mouse release — transition to ADJUSTING state."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._state == _State.DRAWING:
            # Transition to ADJUSTING instead of confirming immediately
            pos = event.globalPosition().toPoint()
            if self._start_pos is not None:
                self._end_pos = pos
                self._selection_rect = QRect(self._start_pos, self._end_pos).normalized()

            # Enforce minimum size to enter ADJUSTING
            if (self._selection_rect.isValid()
                    and not self._selection_rect.isNull()
                    and self._selection_rect.width() >= _MIN_SELECTION
                    and self._selection_rect.height() >= _MIN_SELECTION):
                self._state = _State.ADJUSTING
                self._preview_pixmap = None
                self._preview_rect_cache = QRect()
                logger.debug(
                    "Selection drawn → ADJUSTING state: %s",
                    self._selection_rect,
                )
            else:
                # Too small — reset to IDLE
                self._state = _State.IDLE
                self._selection_rect = QRect()
                logger.debug("Selection too small, resetting to IDLE")

            self.update()

        elif self._state == _State.ADJUSTING:
            # Release after handle drag or move
            self._active_handle = None
            if self._is_moving:
                self._is_moving = False
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self._update_cursor(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._mouse_release_event(event)

    # ── Handle resize logic ──────────────────────────────────────────────────

    def _resize_by_handle(self, pos: QPoint) -> None:
        """Resize the selection rect based on the active handle and mouse position."""
        r = self._drag_rect_origin
        delta = pos - self._drag_origin

        handle = self._active_handle
        if handle is None:
            return

        if handle == _Handle.TOP_LEFT:
            self._selection_rect = QRect(
                QPoint(r.left() + delta.x(), r.top() + delta.y()),
                r.bottomRight(),
            ).normalized()

        elif handle == _Handle.TOP:
            self._selection_rect = QRect(
                QPoint(r.left(), r.top() + delta.y()),
                r.bottomRight(),
            ).normalized()

        elif handle == _Handle.TOP_RIGHT:
            self._selection_rect = QRect(
                QPoint(r.left(), r.top() + delta.y()),
                QPoint(r.right() + delta.x(), r.bottom()),
            ).normalized()

        elif handle == _Handle.RIGHT:
            self._selection_rect = QRect(
                r.topLeft(),
                QPoint(r.right() + delta.x(), r.bottom()),
            ).normalized()

        elif handle == _Handle.BOTTOM_RIGHT:
            self._selection_rect = QRect(
                r.topLeft(),
                QPoint(r.right() + delta.x(), r.bottom() + delta.y()),
            ).normalized()

        elif handle == _Handle.BOTTOM:
            self._selection_rect = QRect(
                r.topLeft(),
                QPoint(r.right(), r.bottom() + delta.y()),
            ).normalized()

        elif handle == _Handle.BOTTOM_LEFT:
            self._selection_rect = QRect(
                QPoint(r.left() + delta.x(), r.top()),
                QPoint(r.right(), r.bottom() + delta.y()),
            ).normalized()

        elif handle == _Handle.LEFT:
            self._selection_rect = QRect(
                QPoint(r.left() + delta.x(), r.top()),
                r.bottomRight(),
            ).normalized()

    # ── Keyboard events ─────────────────────────────────────────────────────

    def _key_press_event(self, event) -> None:  # noqa: ANN001
        """Handle Enter to confirm selection and Escape to cancel."""
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self._cancel_selection()

        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._state in (_State.ADJUSTING, _State.DRAWING):
                self._confirm_selection()
            else:
                logger.debug("Enter pressed but no valid selection")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self._key_press_event(event)