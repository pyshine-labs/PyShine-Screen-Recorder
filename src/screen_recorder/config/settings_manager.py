"""Settings management with QSettings + JSON fallback persistence.

Provides :class:`SettingsManager` for loading, saving, and updating
application settings.  Settings are stored primarily in a JSON file
under the platform's app-config directory, with QSettings used as a
fallback when the JSON file does not exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QStandardPaths

from .. import __app_id__, __app_name__
from ..utils.logger import logger


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class VideoSettings:
    """Video encoding and capture settings."""

    encoder: str = "auto"  # Always auto-detect best available
    codec: str = "h264"
    bitrate: int = 0  # Not used (CRF mode for quality)
    frame_rate: int = 30  # 30fps for smooth real-time recording
    quality_preset: str = "ultrafast"  # Mandatory for real-time


@dataclass
class AudioSettings:
    """Audio capture and encoding settings."""

    sample_rate: int = 48000
    channels: int = 2
    microphone_enabled: bool = True
    system_audio_enabled: bool = False
    microphone_device: str | None = None
    system_audio_device: str | None = None


@dataclass
class GeneralSettings:
    """General application preferences."""

    output_directory: str = ""  # default: Documents/Screen Recordings
    default_filename_template: str = "recording_{timestamp}"
    minimize_to_tray: bool = True
    show_notifications: bool = True
    theme: str = "dark"


@dataclass
class AppSettings:
    """Aggregate container for all application settings."""

    video: VideoSettings = field(default_factory=VideoSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    general: GeneralSettings = field(default_factory=GeneralSettings)


# ── Settings manager ──────────────────────────────────────────────────────────


class SettingsManager:
    """Manage application settings with QSettings + JSON fallback.

    On construction the manager attempts to load settings from a JSON
    file located in the platform's app-config directory.  If the file
    does not exist, it falls back to QSettings.  The :meth:`save`
    method always persists to the JSON file and also syncs QSettings.
    """

    SETTINGS_VERSION = 3  # Increment when defaults change to force migration

    def __init__(self) -> None:
        self._qsettings = QSettings(__app_id__, __app_name__)
        self._app_settings = AppSettings()
        self._load_settings()
        self._apply_migrations()

    # ── Path helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_settings_path() -> Path:
        """Return the path to the JSON settings file.

        Uses ``QStandardPaths.AppConfigLocation`` / "screen_recorder" /
        "settings.json".
        """
        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        return Path(config_dir) / "screen_recorder" / "settings.json"

    def _apply_migrations(self) -> None:
        """Force optimal defaults for settings that affect recording quality.

        These values are no longer user-configurable in the GUI and MUST
        always be optimal for real-time screen recording. We force them
        on every load to prevent stale values from old versions.
        """
        saved_ver = self._qsettings.value("settings_version", 0, type=int)
        migrated = False

        # ── Always force these (non-negotiable for real-time recording) ──
        if self._app_settings.video.encoder != "auto":
            self._app_settings.video.encoder = "auto"
            migrated = True
        if self._app_settings.video.bitrate != 0:
            self._app_settings.video.bitrate = 0
            migrated = True
        if self._app_settings.video.quality_preset != "ultrafast":
            self._app_settings.video.quality_preset = "ultrafast"
            migrated = True
        if self._app_settings.video.frame_rate != 30:
            self._app_settings.video.frame_rate = 30
            migrated = True
        if self._app_settings.video.codec != "h264":
            self._app_settings.video.codec = "h264"
            migrated = True

        # Version 3: ensure system audio defaults to on when mic is off
        if saved_ver < 3:
            if not self._app_settings.audio.microphone_enabled and not self._app_settings.audio.system_audio_enabled:
                self._app_settings.audio.system_audio_enabled = True
                migrated = True
            if self._app_settings.audio.sample_rate != 48000:
                self._app_settings.audio.sample_rate = 48000
                migrated = True
            if self._app_settings.audio.channels != 2:
                self._app_settings.audio.channels = 2
                migrated = True
            self._qsettings.setValue("settings_version", self.SETTINGS_VERSION)
            migrated = True

        if migrated:
            self.save()
            logger.info("Settings migrated to v%d (optimal real-time defaults applied)", self.SETTINGS_VERSION)

    # ── Loading ───────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        """Load settings from JSON file, falling back to QSettings."""
        json_path = self._get_settings_path()

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                self._populate_from_dict(data)
                logger.info("Settings loaded from JSON: %s", json_path)
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to load JSON settings from %s: %s – falling back to QSettings",
                    json_path,
                    exc,
                )

        # Fallback: load from QSettings
        self._load_from_qsettings()
        logger.info("Settings loaded from QSettings (JSON file not found)")

    def _populate_from_dict(self, data: dict[str, Any]) -> None:
        """Populate ``self._app_settings`` from a nested dictionary."""
        if "video" in data and isinstance(data["video"], dict):
            self._app_settings.video = VideoSettings(**data["video"])
        if "audio" in data and isinstance(data["audio"], dict):
            self._app_settings.audio = AudioSettings(**data["audio"])
        if "general" in data and isinstance(data["general"], dict):
            self._app_settings.general = GeneralSettings(**data["general"])

    def _load_from_qsettings(self) -> None:
        """Populate ``self._app_settings`` from QSettings key/value pairs."""
        qs = self._qsettings

        # Video
        self._app_settings.video.encoder = qs.value("video/encoder", self._app_settings.video.encoder, type=str)
        self._app_settings.video.codec = qs.value("video/codec", self._app_settings.video.codec, type=str)
        self._app_settings.video.bitrate = qs.value("video/bitrate", self._app_settings.video.bitrate, type=int)
        self._app_settings.video.frame_rate = qs.value("video/frame_rate", self._app_settings.video.frame_rate, type=int)
        self._app_settings.video.quality_preset = qs.value("video/quality_preset", self._app_settings.video.quality_preset, type=str)

        # Audio
        self._app_settings.audio.sample_rate = qs.value("audio/sample_rate", self._app_settings.audio.sample_rate, type=int)
        self._app_settings.audio.channels = qs.value("audio/channels", self._app_settings.audio.channels, type=int)
        self._app_settings.audio.microphone_enabled = qs.value("audio/microphone_enabled", self._app_settings.audio.microphone_enabled, type=bool)
        self._app_settings.audio.system_audio_enabled = qs.value("audio/system_audio_enabled", self._app_settings.audio.system_audio_enabled, type=bool)
        self._app_settings.audio.microphone_device = qs.value("audio/microphone_device", self._app_settings.audio.microphone_device, type=str) or None
        self._app_settings.audio.system_audio_device = qs.value("audio/system_audio_device", self._app_settings.audio.system_audio_device, type=str) or None

        # General
        self._app_settings.general.output_directory = qs.value("general/output_directory", self._app_settings.general.output_directory, type=str)
        self._app_settings.general.default_filename_template = qs.value("general/default_filename_template", self._app_settings.general.default_filename_template, type=str)
        self._app_settings.general.minimize_to_tray = qs.value("general/minimize_to_tray", self._app_settings.general.minimize_to_tray, type=bool)
        self._app_settings.general.show_notifications = qs.value("general/show_notifications", self._app_settings.general.show_notifications, type=bool)
        self._app_settings.general.theme = qs.value("general/theme", self._app_settings.general.theme, type=str)

    # ── Saving ─────────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist current settings to the JSON file and sync QSettings."""
        json_path = self._get_settings_path()

        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(asdict(self._app_settings), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Settings saved to JSON: %s", json_path)
        except OSError as exc:
            logger.error("Failed to save settings to %s: %s", json_path, exc)

        # Also sync to QSettings as a secondary store
        self._sync_to_qsettings()
        self._qsettings.sync()

    def _sync_to_qsettings(self) -> None:
        """Write current settings into QSettings as key/value pairs."""
        qs = self._qsettings
        video = self._app_settings.video
        audio = self._app_settings.audio
        general = self._app_settings.general

        qs.setValue("video/encoder", video.encoder)
        qs.setValue("video/codec", video.codec)
        qs.setValue("video/bitrate", video.bitrate)
        qs.setValue("video/frame_rate", video.frame_rate)
        qs.setValue("video/quality_preset", video.quality_preset)

        qs.setValue("audio/sample_rate", audio.sample_rate)
        qs.setValue("audio/channels", audio.channels)
        qs.setValue("audio/microphone_enabled", audio.microphone_enabled)
        qs.setValue("audio/system_audio_enabled", audio.system_audio_enabled)
        qs.setValue("audio/microphone_device", audio.microphone_device or "")
        qs.setValue("audio/system_audio_device", audio.system_audio_device or "")

        qs.setValue("general/output_directory", general.output_directory)
        qs.setValue("general/default_filename_template", general.default_filename_template)
        qs.setValue("general/minimize_to_tray", general.minimize_to_tray)
        qs.setValue("general/show_notifications", general.show_notifications)
        qs.setValue("general/theme", general.theme)

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self) -> AppSettings:
        """Return the current application settings."""
        return self._app_settings

    def update(self, **kwargs: Any) -> None:
        """Update nested settings using dot-notation keys.

        Accepted examples::

            manager.update(video__bitrate=10000)
            manager.update(audio__microphone_enabled=False)
            manager.update(general__theme="light")

        The double-underscore (``__``) maps to the dot separator
        (``video.bitrate``) so that the API remains Pythonic while
        avoiding attribute-name issues with ``**kwargs``.

        Alternatively, you may pass a single ``key`` string with
        actual dot notation::

            manager.update(**{"video.bitrate": 10000})
        """
        for key, value in kwargs.items():
            # Support both "video__bitrate" and "video.bitrate" styles
            parts = key.replace("__", ".").split(".")
            if len(parts) != 2:
                logger.warning("Ignoring invalid settings key: %r (expected 'section.key')", key)
                continue

            section_name, attr_name = parts
            section = {
                "video": self._app_settings.video,
                "audio": self._app_settings.audio,
                "general": self._app_settings.general,
            }.get(section_name)

            if section is None:
                logger.warning("Ignoring unknown settings section: %r", section_name)
                continue

            if not hasattr(section, attr_name):
                logger.warning("Ignoring unknown attribute %r on section %r", attr_name, section_name)
                continue

            setattr(section, attr_name, value)
            logger.debug("Updated %s.%s = %s", section_name, attr_name, value)

        self.save()

    def reset(self) -> None:
        """Reset all settings to their default values and persist."""
        self._app_settings = AppSettings()
        self.save()
        logger.info("Settings reset to defaults")