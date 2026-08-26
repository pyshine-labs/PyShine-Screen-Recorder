"""Preview widget for displaying screen capture frames.

Provides :class:`PreviewWidget` which renders live preview frames from
the screen capture, scaling them to fit while maintaining aspect ratio
and updating the border based on the current recording state.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..app import RecordingState
from ..utils.logger import logger


class PreviewWidget(QWidget):
    """Widget for displaying screen capture preview frames.

    Renders incoming frames scaled to fit the widget while preserving
    aspect ratio.  The border colour changes based on the recording state:
    normal (IDLE), red (RECORDING), or yellow (PAUSED).

    Signals:
        frame_size_changed(int, int): Emitted with (width, height) when a
            new frame arrives.
    """

    frame_size_changed = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_pixmap: QPixmap | None = None
        self._recording_state: RecordingState = RecordingState.IDLE
        self._setup_ui()
        logger.debug("PreviewWidget initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the preview widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "background-color: #000000; "
            "border: 2px solid #232330; "
            "border-radius: 4px;"
        )
        self._label.setMinimumSize(320, 180)
        layout.addWidget(self._label)

    # ── Public API ───────────────────────────────────────────────────────────

    def update_frame(self, frame: QImage) -> None:
        """Update the preview with a new QImage.

        The image is scaled to fit the label while maintaining its
        aspect ratio.

        Args:
            frame: The captured frame as a :class:`QImage`.
        """
        if frame.isNull():
            return

        self._current_pixmap = QPixmap.fromImage(frame)
        self._scale_and_show()
        self.frame_size_changed.emit(frame.width(), frame.height())

    def update_frame_numpy(self, frame: np.ndarray) -> None:
        """Convert a numpy RGB array to QImage and update the preview.

        Args:
            frame: A numpy array with shape (height, width, 3) and dtype
                ``uint8`` in RGB format.
        """
        if frame is None or frame.size == 0:
            return

        height, width, channels = frame.shape
        # Ensure contiguous array for QImage
        contiguous_frame = np.ascontiguousarray(frame)
        bytes_per_line = width * channels

        qimage = QImage(
            contiguous_frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )
        # Keep a reference so the numpy array isn't garbage-collected
        # before QImage is used
        qimage._numpy_ref = contiguous_frame  # type: ignore[attr-defined]

        self.update_frame(qimage)

    def clear_frame(self) -> None:
        """Clear the preview and show a black background."""
        self._current_pixmap = None
        self._label.clear()
        self._label.setStyleSheet(
            "background-color: #000000; "
            "border: 2px solid #232330; "
            "border-radius: 4px;"
        )
        logger.debug("Preview frame cleared")

    def set_recording_state(self, state: RecordingState) -> None:
        """Update the border/overlay based on the recording state.

        Args:
            state: The current :class:`RecordingState`.
        """
        self._recording_state = state

        if state == RecordingState.RECORDING:
            border_style = "2px solid red"
        elif state == RecordingState.PAUSED:
            border_style = "2px solid yellow"
        else:
            border_style = "2px solid #232330"

        self._label.setStyleSheet(
            f"background-color: #000000; "
            f"border: {border_style}; "
            f"border-radius: 4px;"
        )
        logger.debug("Preview border updated for state: %s", state.name)

    # ── Overrides ────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Re-scale the current frame when the widget is resized."""
        super().resizeEvent(event)
        self._scale_and_show()

    # ── Private helpers ──────────────────────────────────────────────────────

    def _scale_and_show(self) -> None:
        """Scale the current pixmap to fit the label and display it."""
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return

        scaled = self._current_pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)