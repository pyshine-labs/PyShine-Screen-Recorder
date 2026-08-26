"""Main application window — orchestrates all GUI panels.

Provides :class:`MainWindow`, the primary :class:`QMainWindow` that hosts
the source selector, recorder controls, audio meter, history, and status bar
in a compact, professional toolbar-style layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..app import RecordingState
from ..utils.logger import logger
from .. import __app_name__, __version__, __website__
from .audio_meter import AudioLevelMeter
from .help_dialog import HelpDialog
from .history_panel import HistoryPanel
from .recorder_controls import RecorderControls
from .source_selector import SourceSelector
from .status_bar import StatusBar


class MainWindow(QMainWindow):
    """Primary application window for the Screen Recorder.

    Signals:
        start_recording_requested: Emitted when the user requests to start recording.
        stop_recording_requested: Emitted when the user requests to stop recording.
        pause_recording_requested: Emitted when the user requests to pause recording.
        resume_recording_requested: Emitted when the user requests to resume recording.
        show_settings_requested: Emitted when the user requests the settings dialog.
        region_select_requested: Emitted when the user requests region selection.
    """

    start_recording_requested = pyqtSignal()
    stop_recording_requested = pyqtSignal()
    pause_recording_requested = pyqtSignal()
    resume_recording_requested = pyqtSignal()
    show_settings_requested = pyqtSignal()
    region_select_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._quitting = False

        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(480, 360)

        # ── Application icon (title bar + taskbar) ────────────────────
        icon_path = self._resolve_icon_path("pyshine_logo.png")
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
            # Cache the path for the in-UI logo label
            self._logo_path = icon_path
        else:
            self._logo_path = None

        # ── Child widgets ────────────────────────────────────────────────
        self._source_selector = SourceSelector()
        self._controls = RecorderControls()
        self._audio_meter = AudioLevelMeter()
        self._history_panel = HistoryPanel()
        self._status_bar = StatusBar()

        self._setup_ui()
        self._connect_signals()

        logger.info("MainWindow created")

    @staticmethod
    def _resolve_icon_path(name: str) -> Path | None:
        """Resolve an icon path for both dev and frozen (EXE) modes."""
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
            candidates.append(base / "resources" / "icons" / name)
            candidates.append(base / "icons" / name)
            candidates.append(base / name)
        else:
            root = Path(__file__).parent.parent.parent.parent
            candidates.append(root / "resources" / "icons" / name)
        for c in candidates:
            if c.is_file():
                return c
        return None

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build a compact, smart-looking rectangle layout.

        ┌───────────────────────────────────────┐
        │ [logo] Screen Recorder                │  ← brand bar
        ├───────────────────────────────────────┤
        │ CAPTURE [▼]    MONITOR [▼]            │  ← source row
        │ [▶][■][⏸][⬚][⚙]   ▓▓▓▓▓▓▓▓ L/R      │  ← controls + audio
        ├───────────────────────────────────────┤
        │ History                               │
        ├───────────────────────────────────────┤
        │ ● Ready   DURATION 00:00   FPS 30     │  ← status bar
        └───────────────────────────────────────┘
        """
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── Brand bar: logo + title only ───────────────────────────────
        brand = QWidget()
        brand.setObjectName("brandBar")
        brand.setStyleSheet(
            "#brandBar { "
            "  background-color: #1a1a24; "
            "  border: 1px solid #232330; "
            "  border-radius: 8px; "
            "}"
        )
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(12, 6, 12, 6)
        brand_layout.setSpacing(10)

        if getattr(self, "_logo_path", None) is not None:
            logo_label = QLabel()
            pix = QPixmap(str(self._logo_path))
            if not pix.isNull():
                logo_label.setPixmap(
                    pix.scaledToHeight(22, Qt.TransformationMode.SmoothTransformation)
                )
            logo_label.setFixedSize(26, 26)
            logo_label.setToolTip(f"{__app_name__} v{__version__}")
            brand_layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

            title = QLabel(f"{__app_name__}")
            title.setStyleSheet(
                "font-size: 13px; font-weight: 700; color: #e8e8f0;"
            )
            brand_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)

            # Version pill
            version = QLabel(f"v{__version__}")
            version.setStyleSheet(
                "font-size: 10px; font-weight: 600; color: #9090a8; "
                "background-color: #23232f; border: 1px solid #2e2e3d; "
                "border-radius: 8px; padding: 2px 8px;"
            )
            version.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand_layout.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)

        brand_layout.addStretch()

        # ── Website link (right-aligned, before Help) ──────────────────
        website = QLabel(__website__)
        website.setStyleSheet(
            "font-size: 11px; color: #6a6a82; font-weight: 500;"
        )
        website.setToolTip("Visit www.pyshine.com")
        website.setCursor(Qt.CursorShape.PointingHandCursor)
        website.mousePressEvent = lambda e: self._open_website()
        brand_layout.addWidget(website, 0, Qt.AlignmentFlag.AlignVCenter)

        # ── Help button (top-right of brand bar) ───────────────────────
        self._help_button = QPushButton("?")
        self._help_button.setToolTip("Help — Shortcuts & Usage (F1)")
        self._help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._help_button.setFixedSize(26, 26)
        self._help_button.setStyleSheet(
            "QPushButton { "
            "  background-color: #23232f; color: #9090a8; "
            "  border: 1px solid #2e2e3d; border-radius: 13px; "
            "  font-size: 14px; font-weight: 700; padding: 0px; "
            "} "
            "QPushButton:hover { "
            "  background-color: #6366f1; color: #ffffff; "
            "  border-color: #6366f1; "
            "} "
            "QPushButton:pressed { "
            "  background-color: #5457e5; "
            "}"
        )
        brand_layout.addWidget(self._help_button)

        main_layout.addWidget(brand)

        # ── Control panel: source row above controls+audio ─────────────
        panel = QWidget()
        panel.setObjectName("controlPanel")
        panel.setStyleSheet(
            "#controlPanel { "
            "  background-color: #1a1a24; "
            "  border: 1px solid #232330; "
            "  border-radius: 8px; "
            "}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(10)

        # Row 1 — source selector (Capture | Monitor side-by-side)
        panel_layout.addWidget(self._source_selector, 0)

        # Subtle horizontal divider
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #232330;")
        panel_layout.addWidget(divider)

        # Row 2 — buttons on left, horizontal audio meter on right
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(12)
        controls_row.addWidget(self._controls, 0)
        controls_row.addStretch()
        controls_row.addWidget(self._audio_meter, 1)
        panel_layout.addLayout(controls_row)

        main_layout.addWidget(panel)

        # ── History panel fills remaining space ──────────────────────────
        main_layout.addWidget(self._history_panel, 1)

        # ── Status bar at the bottom ────────────────────────────────────
        main_layout.addWidget(self._status_bar)

        # ── Populate history panel with saved recordings ────────────────
        self._history_panel.refresh_history()

    @staticmethod
    def _make_vline() -> QWidget:
        """Create a subtle vertical separator line."""
        line = QWidget()
        line.setFixedWidth(1)
        line.setFixedHeight(36)
        line.setStyleSheet("background-color: #2e2e3d;")
        return line

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Connect child widget signals to own signals."""
        # RecorderControls → MainWindow signals
        self._controls.start_requested.connect(self.start_recording_requested.emit)
        self._controls.stop_requested.connect(self.stop_recording_requested.emit)
        self._controls.pause_requested.connect(self.pause_recording_requested.emit)
        self._controls.resume_requested.connect(self.resume_recording_requested.emit)
        self._controls.settings_requested.connect(self.show_settings_requested.emit)
        self._controls.region_select_requested.connect(self.region_select_requested.emit)

        # Help button + F1 shortcut → help dialog
        self._help_button.clicked.connect(self._show_help)
        QShortcut(QKeySequence.StandardKey.HelpContents, self, activated=self._show_help)

        logger.debug("MainWindow signals connected")

    def _show_help(self) -> None:
        """Open the Help dialog showing shortcuts and usage."""
        dialog = HelpDialog(self)
        dialog.exec()

    def _open_website(self) -> None:
        """Open the PyShine website in the default browser."""
        import webbrowser
        webbrowser.open(f"https://{__website__}")
        logger.info("Opened website: %s", __website__)

    @property
    def help_button(self) -> QPushButton:
        """Expose the help button for testing/inspection."""
        return self._help_button

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recording_state(self, state: RecordingState) -> None:
        """Propagate recording state to all child widgets."""
        self._source_selector.set_recording_state(state)
        self._controls.set_recording_state(state)
        self._audio_meter.set_recording_state(state)
        self._status_bar.set_recording_state(state)
        logger.info("MainWindow recording state set: %s", state.name)

    def get_source_selector(self) -> SourceSelector:
        return self._source_selector

    def get_controls(self) -> RecorderControls:
        return self._controls

    def get_status_bar(self) -> StatusBar:
        return self._status_bar

    def get_audio_meter(self) -> AudioLevelMeter:
        return self._audio_meter

    def get_history_panel(self) -> HistoryPanel:
        return self._history_panel

    # ── Window events ────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 – Qt naming convention
        """Minimize to tray instead of closing, unless the app is quitting."""
        if self._quitting:
            event.accept()
            return

        self.hide()
        event.ignore()
        logger.info("MainWindow hidden to system tray")
