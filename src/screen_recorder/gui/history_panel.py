"""Recording history panel for the Screen Recorder application.

Provides :class:`HistoryPanel` which displays past recordings as thumbnail
tiles in an icon-mode list widget and allows the user to open, delete, or
locate recording files.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QPointF, QUrl, Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF, QDesktopServices
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config.recording_history import RecordingEntry, RecordingHistory
from ..utils.logger import logger

# ── Thumbnail constants ────────────────────────────────────────────────────────

_THUMB_W = 96
_THUMB_H = 64
_GRID_W = 160
_GRID_H = 120
_PLACEHOLDER_BG = "#2d2d44"
_PLACEHOLDER_FG = "#8888aa"


class HistoryPanel(QWidget):
    """Panel displaying recording history with open, delete, and locate actions.

    Signals:
        open_recording(str): Emitted with the file path when the user opens a recording.
        delete_recording(str): Emitted with the recording ID when the user deletes a recording.
    """

    open_recording = pyqtSignal(str)
    delete_recording = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = RecordingHistory()
        self._placeholder: QPixmap | None = None
        self._setup_ui()
        self._setup_connections()
        logger.debug("HistoryPanel initialized")

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the history panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Group box ─────────────────────────────────────────────────────
        group = QGroupBox("Recording History")
        group_layout = QVBoxLayout(group)

        # ── List widget (icon mode) ────────────────────────────────────────
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(_THUMB_W, _THUMB_H))
        self._list.setGridSize(QSize(_GRID_W, _GRID_H))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        group_layout.addWidget(self._list)

        # ── Buttons ──────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()

        self._open_button = QPushButton("Open")
        self._open_button.setToolTip("Open the selected recording file")
        btn_layout.addWidget(self._open_button)

        self._delete_button = QPushButton("Delete")
        self._delete_button.setToolTip("Delete the selected recording from history")
        btn_layout.addWidget(self._delete_button)

        self._open_folder_button = QPushButton("Open Folder")
        self._open_folder_button.setToolTip("Open the folder containing the selected recording")
        btn_layout.addWidget(self._open_folder_button)

        btn_layout.addStretch()
        group_layout.addLayout(btn_layout)

        layout.addWidget(group)

    def _setup_connections(self) -> None:
        """Connect button clicks and list widget signals."""
        self._open_button.clicked.connect(self._on_open_clicked)
        self._delete_button.clicked.connect(self._on_delete_clicked)
        self._open_folder_button.clicked.connect(self._on_open_folder_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ── Placeholder thumbnail ─────────────────────────────────────────────────

    def _create_placeholder(self) -> QPixmap:
        """Create a placeholder thumbnail pixmap with a play triangle.

        Returns:
            A :class:`QPixmap` of size ``_THUMB_W × _THUMB_H`` filled with
            the dark placeholder background and a centred play triangle.
        """
        px = QPixmap(_THUMB_W, _THUMB_H)
        px.fill(QColor(_PLACEHOLDER_BG))

        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw a simple play triangle (▶) in the centre
        cx, cy = _THUMB_W // 2, _THUMB_H // 2
        tri_w, tri_h = 18, 22
        half_h = tri_h // 2

        triangle = QPolygonF([
            QPointF(cx - tri_w // 3, cy - half_h),
            QPointF(cx - tri_w // 3, cy + half_h),
            QPointF(cx + tri_w // 2, cy),
        ])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_PLACEHOLDER_FG))
        painter.drawPolygon(triangle)
        painter.end()

        return px

    def _get_placeholder(self) -> QPixmap:
        """Return the cached placeholder pixmap, creating it on first call."""
        if self._placeholder is None:
            self._placeholder = self._create_placeholder()
        return self._placeholder

    # ── Public API ───────────────────────────────────────────────────────────

    def refresh_history(self) -> None:
        """Load entries from RecordingHistory and populate the list widget.

        Only shows entries whose file_path still exists on disk — deleted
        files are automatically hidden from the list.
        """
        self._list.clear()
        self._history.reload()  # Re-read from disk to pick up entries added by other instances
        entries = self._history.get_entries()

        # Filter out entries whose files no longer exist
        live_entries = [e for e in entries if os.path.isfile(e.file_path)]
        removed_count = len(entries) - len(live_entries)
        if removed_count > 0:
            logger.info("Hiding %d deleted recordings from history list", removed_count)

        for entry in live_entries:
            item = QListWidgetItem()
            item.setText(entry.file_name)

            # ── Thumbnail ─────────────────────────────────────────────────
            thumb_path = entry.thumbnail_path
            if thumb_path and os.path.isfile(thumb_path):
                icon = QIcon(thumb_path)
            else:
                icon = QIcon(self._get_placeholder())
            item.setIcon(icon)

            # ── Tooltip ───────────────────────────────────────────────────
            duration_str = self._format_duration(entry.duration)
            size_str = self._format_file_size(entry.file_size)
            tooltip_lines = [
                f"<b>{entry.file_name}</b>",
                f"Duration: {duration_str}",
                f"Size: {size_str}",
                f"Date: {entry.created_at}",
                f"Path: {entry.file_path}",
            ]
            item.setToolTip("<br>".join(tooltip_lines))

            # ── Store entry data ──────────────────────────────────────────
            item.setData(Qt.ItemDataRole.UserRole, entry)

            self._list.addItem(item)

        logger.debug("History panel refreshed — %d entries (%d hidden)", len(live_entries), removed_count)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _current_entry(self) -> RecordingEntry | None:
        """Return the :class:`RecordingEntry` for the currently selected item."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ── Private slots ────────────────────────────────────────────────────────

    def _on_open_clicked(self) -> None:
        """Open the selected recording file with the system default player."""
        entry = self._current_entry()
        if entry is None:
            logger.debug("No recording selected for open action")
            return

        file_path = entry.file_path
        if not os.path.isfile(file_path):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The recording file could not be found:\n{file_path}",
            )
            logger.warning("Recording file not found: %s", file_path)
            return

        self.open_recording.emit(file_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
        logger.info("Opening recording: %s", file_path)

    def _on_delete_clicked(self) -> None:
        """Delete the selected recording from history and disk."""
        entry = self._current_entry()
        if entry is None:
            logger.debug("No recording selected for delete action")
            return

        result = QMessageBox.question(
            self,
            "Delete Recording",
            f"Are you sure you want to permanently delete this recording?\n\n{entry.file_name}\n\nThe file will be removed from disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if result == QMessageBox.StandardButton.Yes:
            # Delete the actual file from disk
            try:
                file_path = Path(entry.file_path)
                if file_path.is_file():
                    file_path.unlink()
                    logger.info("Deleted file from disk: %s", file_path)
                else:
                    logger.info("File not found on disk (already deleted): %s", file_path)
            except OSError as exc:
                logger.warning("Failed to delete file from disk: %s — %s", entry.file_path, exc)
                QMessageBox.warning(
                    self,
                    "Delete Failed",
                    f"Could not delete the file from disk:\n{entry.file_path}\n\n{exc}",
                )
                return

            # Remove from history
            self._history.remove_entry(entry.id)
            self.delete_recording.emit(entry.id)
            self.refresh_history()
            logger.info("Deleted recording: %s (%s)", entry.file_name, entry.id)

    def _on_open_folder_clicked(self) -> None:
        """Open the folder containing the selected recording."""
        entry = self._current_entry()
        if entry is None:
            logger.debug("No recording selected for open-folder action")
            return

        folder = str(Path(entry.file_path).parent)
        if not os.path.isdir(folder):
            QMessageBox.warning(
                self,
                "Folder Not Found",
                f"The folder could not be found:\n{folder}",
            )
            logger.warning("Recording folder not found: %s", folder)
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        logger.info("Opened folder: %s", folder)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on a list item — open the recording folder in Explorer."""
        entry: RecordingEntry | None = item.data(Qt.ItemDataRole.UserRole)
        if entry is not None:
            folder = str(Path(entry.file_path).parent)
            if os.path.isdir(folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ── Formatting helpers ────────────────────────────────────────────────────

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds as ``HH:MM:SS``.

        Args:
            seconds: The duration in seconds.

        Returns:
            A formatted string like ``01:23:45``.
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """Format a file size in bytes as a human-readable string.

        Args:
            size_bytes: The file size in bytes.

        Returns:
            A string like ``12.3 MB`` or ``1.2 GB``.
        """
        if size_bytes >= 1_073_741_824:  # 1 GB
            return f"{size_bytes / 1_073_741_824:.1f} GB"
        elif size_bytes >= 1_048_576:  # 1 MB
            return f"{size_bytes / 1_048_576:.1f} MB"
        elif size_bytes >= 1_024:  # 1 KB
            return f"{size_bytes / 1_024:.1f} KB"
        else:
            return f"{size_bytes} B"