"""GUI module — main window, controls, and widgets for the screen recorder."""

from .main_window import MainWindow
from .recorder_controls import RecorderControls
from .source_selector import SourceSelector
from .audio_meter import AudioLevelMeter
from .status_bar import StatusBar
from .settings_panel import SettingsDialog
from .history_panel import HistoryPanel
from .preview_widget import PreviewWidget
from .system_tray import TrayIconManager

__all__ = [
    "MainWindow",
    "RecorderControls",
    "SourceSelector",
    "AudioLevelMeter",
    "StatusBar",
    "SettingsDialog",
    "HistoryPanel",
    "PreviewWidget",
    "TrayIconManager",
]