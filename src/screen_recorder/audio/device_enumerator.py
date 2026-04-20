"""Audio device enumeration for the Screen Recorder application.

Provides discovery of input (microphone), output (speaker), and WASAPI
loopback devices using *sounddevice* and, optionally, *pyaudiowpatch*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger

# pyaudiowpatch is optional — it provides WASAPI loopback device enumeration
# on Windows.  If it is not installed we simply return an empty list from
# ``get_loopback_devices()``.
try:
    import pyaudiowpatch as pyaudio_wp  # type: ignore[import-untyped]

    _HAS_PYAUDIOWPATCH = True
except ImportError:
    pyaudio_wp = None  # type: ignore[assignment]
    _HAS_PYAUDIOWPATCH = False


@dataclass
class AudioDeviceInfo:
    """Lightweight descriptor for an audio device."""

    index: int
    name: str
    sample_rate: float
    max_input_channels: int
    max_output_channels: int
    is_loopback: bool = False
    host_api: str = ""


class AudioDeviceEnumerator(QObject):
    """Enumerate audio input, output, and loopback devices.

    The class wraps *sounddevice* device queries and, when available,
    *pyaudiowpatch* for WASAPI loopback device discovery on Windows.

    Signals:
        devices_changed: Emitted after :meth:`refresh_devices` re-queries
            the system for available devices.
    """

    devices_changed = pyqtSignal()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_input_devices(self) -> list[AudioDeviceInfo]:
        """Return all devices that have at least one input channel (microphones)."""
        devices = sd.query_devices()
        result: list[AudioDeviceInfo] = []
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                result.append(self._device_info_from_sd(idx, dev))
        return result

    def get_output_devices(self) -> list[AudioDeviceInfo]:
        """Return all devices that have at least one output channel (speakers)."""
        devices = sd.query_devices()
        result: list[AudioDeviceInfo] = []
        for idx, dev in enumerate(devices):
            if dev["max_output_channels"] > 0:
                result.append(self._device_info_from_sd(idx, dev))
        return result

    def get_loopback_devices(self) -> list[AudioDeviceInfo]:
        """Return WASAPI loopback devices for system audio capture.

        If *pyaudiowpatch* is not installed, an empty list is returned and a
        warning is logged.
        """
        if not _HAS_PYAUDIOWPATCH:
            logger.warning(
                "pyaudiowpatch is not installed — loopback device enumeration "
                "is unavailable. Install it with: pip install pyaudiowpatch"
            )
            return []

        loopback_devices: list[AudioDeviceInfo] = []
        try:
            pa = pyaudio_wp.PyAudio()
            try:
                for idx in range(pa.get_device_count()):
                    dev_info = pa.get_device_info_by_index(idx)
                    # pyaudiowpatch exposes loopback devices via the
                    # 'isLoopbackDevice' key on WASAPI hosts.
                    is_loopback = dev_info.get("isLoopbackDevice", False)
                    if is_loopback:
                        host_api_info = pa.get_host_api_info_by_index(
                            dev_info["hostApi"]
                        )
                        loopback_devices.append(
                            AudioDeviceInfo(
                                index=idx,
                                name=dev_info.get("name", ""),
                                sample_rate=dev_info.get(
                                    "defaultSampleRate", 48000.0
                                ),
                                max_input_channels=dev_info.get(
                                    "maxInputChannels", 0
                                ),
                                max_output_channels=dev_info.get(
                                    "maxOutputChannels", 0
                                ),
                                is_loopback=True,
                                host_api=host_api_info.get("name", ""),
                            )
                        )
            finally:
                pa.terminate()
        except Exception:
            logger.exception("Failed to enumerate loopback devices")
        return loopback_devices

    def get_default_input_device(self) -> AudioDeviceInfo | None:
        """Return the default input device, or ``None`` if not set."""
        try:
            default_idx = sd.default.device[0]
            if default_idx is None or default_idx < 0:
                return None
            dev = sd.query_devices(default_idx)
            return self._device_info_from_sd(default_idx, dev)
        except Exception:
            logger.exception("Failed to get default input device")
            return None

    def get_default_output_device(self) -> AudioDeviceInfo | None:
        """Return the default output device, or ``None`` if not set."""
        try:
            default_idx = sd.default.device[1]
            if default_idx is None or default_idx < 0:
                return None
            dev = sd.query_devices(default_idx)
            return self._device_info_from_sd(default_idx, dev)
        except Exception:
            logger.exception("Failed to get default output device")
            return None

    def find_device_by_name(self, name: str) -> AudioDeviceInfo | None:
        """Find the first device whose name contains *name* (case-insensitive).

        Searches across **all** devices (input, output, and loopback).
        """
        all_devices = sd.query_devices()
        name_lower = name.lower()
        for idx, dev in enumerate(all_devices):
            if name_lower in dev["name"].lower():
                return self._device_info_from_sd(idx, dev)
        return None

    def refresh_devices(self) -> None:
        """Re-query the system for devices and emit :attr:`devices_changed`."""
        logger.debug("Refreshing audio device list")
        self.devices_changed.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _device_info_from_sd(idx: int, dev: dict) -> AudioDeviceInfo:
        """Convert a *sounddevice* device dict to :class:`AudioDeviceInfo`."""
        host_api_name = ""
        try:
            host_api_info = sd.query_hostapis(dev["hostapi"])
            host_api_name = host_api_info.get("name", "")
        except Exception:
            pass

        return AudioDeviceInfo(
            index=idx,
            name=dev.get("name", ""),
            sample_rate=dev.get("default_samplerate", 48000.0),
            max_input_channels=dev.get("max_input_channels", 0),
            max_output_channels=dev.get("max_output_channels", 0),
            is_loopback=False,
            host_api=host_api_name,
        )