"""Audio mixing module for the Screen Recorder application.

Mixes multiple audio sources (microphone, system audio, etc.) with
per-channel volume control, muting, and normalisation to prevent clipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger


@dataclass
class MixerChannel:
    """A single channel in the audio mixer."""

    name: str
    volume: float = 1.0  # 0.0 to 2.0; 1.0 = normal level
    enabled: bool = True
    muted: bool = False


class AudioMixer(QObject):
    """Mix multiple audio sources with per-channel volume and mute control.

    Signals:
        mixed_audio(np.ndarray): The mixed audio output.
        channel_levels(dict): Per-channel RMS levels ``{name: float}``.
    """

    mixed_audio = pyqtSignal(np.ndarray)
    channel_levels = pyqtSignal(dict)

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        parent=None,
    ) -> None:
        """Initialise the mixer.

        Args:
            sample_rate: Target sample rate for the mixed output.
            channels: Number of audio channels in the mixed output.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._sample_rate = sample_rate
        self._channels = channels
        self._channels_map: dict[str, MixerChannel] = {}

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    def add_channel(self, name: str, volume: float = 1.0) -> MixerChannel:
        """Add a new mixer channel and return it.

        If a channel with *name* already exists, the existing channel is
        returned (volume is **not** updated).
        """
        if name in self._channels_map:
            logger.warning("Mixer channel '%s' already exists — returning existing", name)
            return self._channels_map[name]

        channel = MixerChannel(name=name, volume=volume)
        self._channels_map[name] = channel
        logger.debug("Added mixer channel '%s' (volume=%.2f)", name, volume)
        return channel

    def remove_channel(self, name: str) -> bool:
        """Remove a channel by name.  Returns ``True`` if the channel existed."""
        if name in self._channels_map:
            del self._channels_map[name]
            logger.debug("Removed mixer channel '%s'", name)
            return True
        logger.warning("Mixer channel '%s' not found — cannot remove", name)
        return False

    def set_volume(self, name: str, volume: float) -> None:
        """Set the volume of channel *name*, clamped to [0.0, 2.0]."""
        channel = self._channels_map.get(name)
        if channel is None:
            logger.warning("Mixer channel '%s' not found — cannot set volume", name)
            return
        channel.volume = max(0.0, min(2.0, volume))

    def set_muted(self, name: str, muted: bool) -> None:
        """Mute or unmute channel *name*."""
        channel = self._channels_map.get(name)
        if channel is None:
            logger.warning("Mixer channel '%s' not found — cannot set muted", name)
            return
        channel.muted = muted

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable channel *name*."""
        channel = self._channels_map.get(name)
        if channel is None:
            logger.warning("Mixer channel '%s' not found — cannot set enabled", name)
            return
        channel.enabled = enabled

    def get_channel(self, name: str) -> MixerChannel | None:
        """Return the :class:`MixerChannel` with the given *name*, or ``None``."""
        return self._channels_map.get(name)

    def get_channels(self) -> list[MixerChannel]:
        """Return all mixer channels."""
        return list(self._channels_map.values())

    def reset(self) -> None:
        """Remove all mixer channels."""
        self._channels_map.clear()
        logger.debug("Mixer reset — all channels removed")

    # ------------------------------------------------------------------
    # Mixing
    # ------------------------------------------------------------------

    def mix(self, audio_chunks: dict[str, np.ndarray]) -> np.ndarray:
        """Mix multiple audio chunks into a single output array.

        Each key in *audio_chunks* corresponds to a mixer channel name, and
        the value is a numpy array of audio samples (float32).

        Per-channel volume is applied before mixing.  Channels that are
        disabled or muted contribute silence.  Shorter chunks are padded
        with zeros to match the longest chunk.  The output is normalised
        by dividing by the number of active (enabled & unmuted) channels
        to prevent clipping.

        Returns:
            A float32 numpy array containing the mixed audio.
        """
        if not audio_chunks:
            return np.array([], dtype=np.float32)

        # Determine the maximum length among all chunks
        max_len = 0
        for chunk in audio_chunks.values():
            if chunk is not None and chunk.size > 0:
                max_len = max(max_len, len(chunk))

        if max_len == 0:
            return np.array([], dtype=np.float32)

        mixed = np.zeros(max_len, dtype=np.float64)
        active_count = 0
        levels: dict[str, float] = {}

        for name, chunk in audio_chunks.items():
            channel = self._channels_map.get(name)

            # If no mixer channel exists for this name, treat as enabled with
            # default volume.
            enabled = channel.enabled if channel else True
            muted = channel.muted if channel else False
            volume = channel.volume if channel else 1.0

            if not enabled or muted or chunk is None or chunk.size == 0:
                levels[name] = 0.0
                continue

            active_count += 1

            # Flatten to 1-D for mixing
            flat = chunk.flatten().astype(np.float64)

            # Pad shorter chunks with zeros
            if len(flat) < max_len:
                padded = np.zeros(max_len, dtype=np.float64)
                padded[: len(flat)] = flat
                flat = padded

            # Apply volume
            mixed += flat * volume

            # Calculate RMS level for this channel
            rms = float(np.sqrt(np.mean(flat**2)))
            levels[name] = min(1.0, rms)

        # Normalise to prevent clipping — divide by number of active channels
        if active_count > 0:
            mixed /= active_count

        # Clamp output to [-1.0, 1.0] as a safety net
        np.clip(mixed, -1.0, 1.0, out=mixed)

        self.channel_levels.emit(levels)

        result = mixed.astype(np.float32)
        self.mixed_audio.emit(result)
        return result