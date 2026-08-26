"""Help dialog — shows keyboard shortcuts and usage instructions.

Provides :class:`HelpDialog`, a modal dialog that documents the global
hotkeys, region-selection shortcuts, and a quick-start guide for the
PyShine Screen Recorder application.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__, __website__


class HelpDialog(QDialog):
    """Modal help dialog showing shortcuts and usage.

    The dialog is read-only and closes via the OK button or Escape key.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Help — {__app_name__}")
        self.setMinimumSize(440, 480)
        self._setup_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the help dialog content."""
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel(__app_name__)
        title.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #e8e8f0;"
        )
        root.addWidget(title)

        subtitle = QLabel(f"v{__version__}  •  Quick reference for shortcuts and usage")
        subtitle.setStyleSheet("font-size: 12px; color: #9090a8;")
        root.addWidget(subtitle)

        root.addWidget(self._make_divider())

        # ── Keyboard Shortcuts ─────────────────────────────────────────
        root.addWidget(self._section_label("KEYBOARD SHORTCUTS"))

        shortcuts = [
            ("F9", "Start / Stop recording (global — works even when app is in background)"),
            ("F10", "Pause / Resume recording (global)"),
            ("Enter", "Confirm region selection (when region overlay is active)"),
            ("Escape", "Cancel region selection (when region overlay is active)"),
        ]
        for key, desc in shortcuts:
            root.addWidget(self._shortcut_row(key, desc))

        root.addWidget(self._make_divider())

        # ── Quick Start ─────────────────────────────────────────────────
        root.addWidget(self._section_label("QUICK START"))

        steps = [
            "Choose the capture source (Full Screen / Window / Custom Region) and the target monitor.",
            "Toggle the microphone and system audio in Settings if needed. When the microphone is off, system audio is captured automatically.",
            "Press F9 (or click the green Start button) to begin recording. The red indicator blinks while recording is active.",
            "Press F10 (or the amber Pause button) to pause and resume. Recording can be paused/resumed any number of times.",
            "Press F9 again (or the red Stop button) to finish. The MP4 file is muxed and appears in the History panel.",
        ]
        for i, step in enumerate(steps, 1):
            root.addWidget(self._step_row(i, step))

        root.addWidget(self._make_divider())

        # ── Tips ───────────────────────────────────────────────────────
        root.addWidget(self._section_label("TIPS"))

        tips = [
            "Region selection: drag the 8 handles to resize, drag inside to move. The animated border is drawn outside the captured area so it never appears in the video.",
            "Quality is near-lossless (CRF 1, 1080p) using GPU capture (DXGI) and H.264 — universally playable.",
            "4K monitors are automatically downscaled to 1080p for performance; native resolution is preserved below 4K.",
            "Delete a recording from the History panel to also remove the .mp4 file from disk.",
        ]
        for tip in tips:
            root.addWidget(self._tip_row(tip))

        root.addStretch()

        root.addWidget(self._make_divider())

        # ── Website footer ──────────────────────────────────────────────
        footer = QLabel(f'<a href="https://{__website__}" style="color:#6366f1; text-decoration:none;">{__website__}</a>')
        footer.setStyleSheet("font-size: 12px; color: #6366f1;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setOpenExternalLinks(True)
        footer.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(footer)

        # ── OK button ──────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Got it")
        ok_btn.setProperty("class", "accent")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str) -> QLabel:
        """Uppercase tracked section header."""
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #6366f1; "
            "letter-spacing: 1.5px;"
        )
        return lbl

    @staticmethod
    def _make_divider() -> QFrame:
        """Subtle horizontal divider line."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #232330; max-height: 1px;")
        return line

    @staticmethod
    def _shortcut_row(key: str, desc: str) -> QWidget:
        """Row showing a keycap + description."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        keycap = QLabel(key)
        keycap.setStyleSheet(
            "background-color: #23232f; color: #e8e8f0; "
            "border: 1px solid #2e2e3d; border-radius: 5px; "
            "padding: 3px 10px; font-family: 'Consolas', monospace; "
            "font-size: 12px; font-weight: 600; min-width: 36px;"
        )
        keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        keycap.setFixedHeight(24)
        h.addWidget(keycap)

        label = QLabel(desc)
        label.setStyleSheet("color: #c0c0d0; font-size: 12px;")
        label.setWordWrap(True)
        h.addWidget(label, 1)
        return row

    @staticmethod
    def _step_row(num: int, text: str) -> QWidget:
        """Row showing a numbered step."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        badge = QLabel(str(num))
        badge.setStyleSheet(
            "background-color: #6366f1; color: #ffffff; "
            "border-radius: 11px; font-size: 11px; font-weight: 700;"
        )
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(22, 22)
        h.addWidget(badge)

        label = QLabel(text)
        label.setStyleSheet("color: #c0c0d0; font-size: 12px;")
        label.setWordWrap(True)
        h.addWidget(label, 1)
        return row

    @staticmethod
    def _tip_row(text: str) -> QWidget:
        """Row showing a tip with a bullet marker."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        marker = QLabel("•")
        marker.setStyleSheet("color: #6366f1; font-size: 16px; font-weight: 700;")
        marker.setFixedWidth(12)
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(marker)

        label = QLabel(text)
        label.setStyleSheet("color: #9090a8; font-size: 12px;")
        label.setWordWrap(True)
        h.addWidget(label, 1)
        return row
