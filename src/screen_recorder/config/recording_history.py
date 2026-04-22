"""Recording history tracking for the Screen Recorder application.

Provides :class:`RecordingHistory` which persists a list of
:class:`RecordingEntry` items to a JSON file under the platform's
app-data directory.  Entries are stored newest-first and automatically
trimmed to a configurable maximum count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4
from datetime import datetime

from PyQt6.QtCore import QStandardPaths

from ..utils.logger import logger


# ── Data class ────────────────────────────────────────────────────────────────


@dataclass
class RecordingEntry:
    """A single recording history entry."""

    id: str  # UUID
    file_path: str
    file_name: str
    created_at: str  # ISO format datetime
    duration: float  # seconds
    file_size: int  # bytes
    width: int
    height: int
    frame_rate: int
    thumbnail_path: str | None = None

    def to_dict(self) -> dict:
        """Serialise the entry to a plain dictionary.

        Returns:
            A JSON-compatible dictionary representation of the entry.
        """
        return {
            "id": self.id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "created_at": self.created_at,
            "duration": self.duration,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "thumbnail_path": self.thumbnail_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RecordingEntry:
        """Deserialise an entry from a dictionary.

        Args:
            data: A dictionary produced by :meth:`to_dict` or loaded from
                the history JSON file.

        Returns:
            A :class:`RecordingEntry` instance.
        """
        return cls(
            id=data.get("id", str(uuid4())),
            file_path=data.get("file_path", ""),
            file_name=data.get("file_name", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            duration=data.get("duration", 0.0),
            file_size=data.get("file_size", 0),
            width=data.get("width", 0),
            height=data.get("height", 0),
            frame_rate=data.get("frame_rate", 0),
            thumbnail_path=data.get("thumbnail_path"),
        )


# ── History manager ───────────────────────────────────────────────────────────

_HISTORY_VERSION = 1


class RecordingHistory:
    """Track and persist recording history entries.

    Entries are stored newest-first.  When the number of entries exceeds
    ``max_entries``, the oldest entries are automatically removed.

    Args:
        max_entries: Maximum number of history entries to keep.  Defaults to 100.
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._max_entries = max_entries
        self._entries: list[RecordingEntry] = []
        self._load_history()

    # ── Path helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_history_path() -> Path:
        """Return the path to the history JSON file.

        Uses ``QStandardPaths.AppDataLocation`` / "screen_recorder" /
        "history.json".
        """
        data_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        return Path(data_dir) / "screen_recorder" / "history.json"

    # ── Loading ────────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Load history from the JSON file on disk.

        If the file does not exist or is corrupt, the history starts empty.
        """
        history_path = self._get_history_path()

        if not history_path.exists():
            logger.info("No history file found at %s — starting fresh", history_path)
            return

        try:
            raw = history_path.read_text(encoding="utf-8")
            data = json.loads(raw)

            # Expect a structure like {"version": 1, "entries": [...]}
            entries_data = data.get("entries", []) if isinstance(data, dict) else data

            self._entries = [RecordingEntry.from_dict(e) for e in entries_data]
            logger.info("Loaded %d history entries from %s", len(self._entries), history_path)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Failed to load history from %s: %s", history_path, exc)
            self._entries = []

    # ── Saving ─────────────────────────────────────────────────────────────

    def _save_history(self) -> None:
        """Persist the current history entries to the JSON file."""
        history_path = self._get_history_path()

        payload = {
            "version": _HISTORY_VERSION,
            "entries": [e.to_dict() for e in self._entries],
        }

        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("History saved (%d entries) to %s", len(self._entries), history_path)
        except OSError as exc:
            logger.error("Failed to save history to %s: %s", history_path, exc)

    # ── Public API ──────────────────────────────────────────────────────────

    def add_entry(self, entry: RecordingEntry) -> None:
        """Add a new entry to the history.

        The entry is prepended (newest first).  If the total number of
        entries exceeds ``max_entries``, the oldest entries are trimmed.

        Args:
            entry: The :class:`RecordingEntry` to add.
        """
        self._entries.insert(0, entry)

        # Trim excess entries
        if len(self._entries) > self._max_entries:
            removed = self._entries[self._max_entries :]
            self._entries = self._entries[: self._max_entries]
            logger.debug("Trimmed %d old history entries", len(removed))

        self._save_history()
        logger.info("Added history entry: %s (%s)", entry.file_name, entry.id)

    def remove_entry(self, entry_id: str) -> bool:
        """Remove an entry by its ID.

        Args:
            entry_id: The UUID of the entry to remove.

        Returns:
            ``True`` if an entry was found and removed, ``False`` otherwise.
        """
        original_len = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]

        if len(self._entries) < original_len:
            self._save_history()
            logger.info("Removed history entry: %s", entry_id)
            return True

        logger.warning("History entry not found: %s", entry_id)
        return False

    def get_entries(self, limit: int | None = None) -> list[RecordingEntry]:
        """Return history entries, optionally limited.

        Args:
            limit: Maximum number of entries to return.  If ``None``,
                all entries are returned.

        Returns:
            A list of :class:`RecordingEntry` items (newest first).
        """
        if limit is None:
            return list(self._entries)
        return self._entries[:limit]

    def get_entry(self, entry_id: str) -> RecordingEntry | None:
        """Return a single entry by its ID.

        Args:
            entry_id: The UUID of the desired entry.

        Returns:
            The matching :class:`RecordingEntry`, or ``None`` if not found.
        """
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def reload(self) -> None:
        """Reload history entries from disk, discarding the in-memory cache."""
        self._entries.clear()
        self._load_history()

    def clear(self) -> None:
        """Remove all history entries and persist the empty list."""
        self._entries = []
        self._save_history()
        logger.info("History cleared")