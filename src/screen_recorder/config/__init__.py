"""Configuration module — settings management, hotkey registration, and recording history."""

from .settings_manager import SettingsManager, AppSettings, VideoSettings, AudioSettings, GeneralSettings
from .hotkey_manager import HotkeyManager
from .recording_history import RecordingHistory, RecordingEntry

__all__ = [
    "SettingsManager", "AppSettings", "VideoSettings", "AudioSettings", "GeneralSettings",
    "HotkeyManager", "RecordingHistory", "RecordingEntry",
]