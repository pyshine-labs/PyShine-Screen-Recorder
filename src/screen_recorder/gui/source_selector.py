"""Source selector widget — choose capture type and monitor.

Provides a :class:`SourceSelector` with combo boxes for capture type
(Full Screen, Window, Custom Region) and monitor selection, plus a
thumbnail preview area.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..capture.display_info import DisplayInfo
from ..utils.logger import logger


class SourceSelector(QWidget):
    """Widget for selecting the capture source type and target monitor.

    Signals:
        source_changed: Emitted when the capture type changes.
            Payload is one of ``"screen"``, ``"window"``, or ``"region"``.
        monitor_selected: Emitted when a different monitor is chosen.
            Payload is the 0-based monitor index.
    """

    source_changed = pyqtSignal(str)
    monitor_selected = pyqtSignal(int)

    # Capture type constants
    CAPTURE_TYPES = ["Full Screen", "Window", "Custom Region"]
    CAPTURE_TYPE_KEYS = ["screen", "window", "region"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._monitors: list = []
        self._setup_ui()
        self._setup_connections()
        self.refresh_monitors()
        logger.debug("SourceSelector initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the source selector layout."""
        group_box = QGroupBox("Source")
        group_layout = QVBoxLayout(group_box)
        group_layout.setContentsMargins(8, 16, 8, 8)
        group_layout.setSpacing(8)

        # ── Capture type ─────────────────────────────────────────────────
        type_layout = QHBoxLayout()
        type_label = QLabel("Capture:")
        type_label.setFixedWidth(60)
        self._capture_combo = QComboBox()
        self._capture_combo.addItems(self.CAPTURE_TYPES)
        type_layout.addWidget(type_label)
        type_layout.addWidget(self._capture_combo, 1)
        group_layout.addLayout(type_layout)

        # ── Monitor selection ────────────────────────────────────────────
        monitor_layout = QHBoxLayout()
        monitor_label = QLabel("Monitor:")
        monitor_label.setFixedWidth(60)
        self._monitor_combo = QComboBox()
        monitor_layout.addWidget(monitor_label)
        monitor_layout.addWidget(self._monitor_combo, 1)
        group_layout.addLayout(monitor_layout)

        # ── Thumbnail preview ───────────────────────────────────────────
        self._thumbnail_label = QLabel("No preview")
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setFixedHeight(120)
        self._thumbnail_label.setStyleSheet(
            "background-color: #11111b; "
            "border: 1px solid #2d2d44; "
            "border-radius: 4px; "
            "color: #555570; "
            "font-size: 12px;"
        )
        group_layout.addWidget(self._thumbnail_label)

        # ── Main layout ─────────────────────────────────────────────────
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(group_box)

    def _setup_connections(self) -> None:
        """Connect combo box signals to own signals."""
        self._capture_combo.currentIndexChanged.connect(self._on_capture_type_changed)
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)

    # ── Slot handlers ────────────────────────────────────────────────────────

    def _on_capture_type_changed(self, index: int) -> None:
        """Handle capture type combo box change."""
        if 0 <= index < len(self.CAPTURE_TYPE_KEYS):
            key = self.CAPTURE_TYPE_KEYS[index]
            logger.debug("Capture type changed to: %s", key)
            self.source_changed.emit(key)

    def _on_monitor_changed(self, index: int) -> None:
        """Handle monitor combo box change."""
        if index >= 0:
            logger.debug("Monitor selected: %d", index)
            self.monitor_selected.emit(index)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state) -> None:
        """Enable or disable source selection based on recording state.

        Source selection is disabled during recording to prevent
        mid-recording changes.

        Args:
            state: A :class:`RecordingState` enum value.
        """
        from ..app import RecordingState

        is_idle = state == RecordingState.IDLE
        self._capture_combo.setEnabled(is_idle)
        self._monitor_combo.setEnabled(is_idle)
        logger.debug("SourceSelector %s", "enabled" if is_idle else "disabled")

    def get_capture_type(self) -> str:
        """Return the selected capture type key.

        Returns:
            One of ``"screen"``, ``"window"``, or ``"region"``.
        """
        index = self._capture_combo.currentIndex()
        if 0 <= index < len(self.CAPTURE_TYPE_KEYS):
            return self.CAPTURE_TYPE_KEYS[index]
        return "screen"

    def get_monitor_index(self) -> int:
        """Return the 0-based index of the selected monitor.

        Returns:
            The monitor index, or 0 if none is selected.
        """
        return max(0, self._monitor_combo.currentIndex())

    def refresh_monitors(self) -> None:
        """Re-query available monitors and update the monitor combo box."""
        self._monitors = DisplayInfo.get_monitors()
        self._monitor_combo.blockSignals(True)
        self._monitor_combo.clear()

        for mon in self._monitors:
            label = f"{mon.name} ({mon.width}×{mon.height})"
            if mon.is_primary:
                label += " ★"
            self._monitor_combo.addItem(label)

        if self._monitors:
            self._monitor_combo.setCurrentIndex(0)

        self._monitor_combo.blockSignals(False)
        logger.info("Refreshed monitor list: %d monitor(s)", len(self._monitors))

    def update_thumbnail(self, image: QImage) -> None:
        """Update the thumbnail preview with a captured image.

        The image is scaled to fit the thumbnail label while maintaining
        aspect ratio.

        Args:
            image: The captured frame as a :class:`QImage`.
        """
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self._thumbnail_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumbnail_label.setPixmap(scaled)