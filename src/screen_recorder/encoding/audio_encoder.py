"""Audio encoder module — AAC encoding via PyAV.

Provides :class:`AudioEncoder` which encodes audio data using PyAV,
typically producing AAC audio for MP4/MKV containers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger


# ── Audio encoder configuration ────────────────────────────────────────────────


@dataclass
class AudioEncoderConfig:
    """Configuration for :class:`AudioEncoder`.

    Attributes:
        sample_rate: Audio sample rate in Hz.
        channels: Number of audio channels (1 = mono, 2 = stereo).
        codec: FFmpeg codec name (e.g. ``"aac"``, ``"libmp3lame"``).
        bitrate: Target bitrate in **kbps**.
        channel_layout: Channel layout string (e.g. ``"stereo"``, ``"mono"``).
    """

    sample_rate: int = 48000
    channels: int = 2
    codec: str = "aac"
    bitrate: int = 192  # kbps
    channel_layout: str = "stereo"

    @classmethod
    def channel_layout_for(cls, channels: int) -> str:
        """Return the channel layout string for the given channel count."""
        layouts = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}
        return layouts.get(channels, f"{channels}ch")


# ── Audio encoder class ───────────────────────────────────────────────────────


class AudioEncoder(QObject):
    """Encode audio data using PyAV.

    Signals:
        audio_encoded(int): Emitted with the cumulative number of audio
            frames encoded.
        encoding_error(str): Emitted with an error message on failure.
        encoding_finished(): Emitted when encoding is complete.
    """

    audio_encoded = pyqtSignal(int)
    encoding_error = pyqtSignal(str)
    encoding_finished = pyqtSignal()

    def __init__(self, parent=None) -> None:  # noqa: D107
        super().__init__(parent)
        self._config = AudioEncoderConfig()
        self._container: av.container.OutputContainer | None = None
        self._stream: av.stream.Stream | None = None
        self._is_open = False
        self._frames_encoded = 0
        self._start_time: float | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, config: AudioEncoderConfig) -> None:
        """Set encoder configuration.

        Must be called **before** :meth:`open`.  If the encoder is already
        open the configuration change is ignored and a warning is logged.
        """
        if self._is_open:
            logger.warning("Cannot reconfigure while encoder is open")
            return
        self._config = config
        logger.info("AudioEncoder configured: %s", config)

    # ------------------------------------------------------------------
    # Open / Close
    # ------------------------------------------------------------------

    def open(self, output_path: str | Path) -> None:
        """Open an output container and add an audio stream.

        Args:
            output_path: Destination file path for the encoded audio.
        """
        if self._is_open:
            logger.warning("Audio encoder is already open")
            return

        output_path = Path(output_path)

        try:
            self._container = av.open(str(output_path), mode="w")
            self._stream = self._container.add_stream(self._config.codec, rate=self._config.sample_rate)
            self._stream.layout = self._config.channel_layout
            self._stream.bit_rate = self._config.bitrate * 1000  # kbps → bps

            self._is_open = True
            self._frames_encoded = 0
            self._start_time = time.time()
            logger.info(
                "Audio encoder opened: %s (%dHz, %dch, %dkbps)",
                self._config.codec,
                self._config.sample_rate,
                self._config.channels,
                self._config.bitrate,
            )
        except Exception as exc:
            msg = f"Failed to open audio encoder: {exc}"
            logger.error(msg)
            self.encoding_error.emit(msg)
            raise

    def close(self) -> None:
        """Flush remaining audio data and close the output container."""
        if not self._is_open:
            return
        self.flush()
        if self._container is not None:
            try:
                self._container.close()
            except Exception as exc:
                logger.exception("Error closing audio container: %s", exc)
        self._is_open = False
        self._stream = None
        self._container = None
        self.encoding_finished.emit()
        logger.info("Audio encoder closed — %d frames encoded", self._frames_encoded)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode_audio(self, audio_data: np.ndarray) -> None:
        """Encode a chunk of audio data.

        Args:
            audio_data: Float32 numpy array with shape ``(frames, channels)``
                (interleaved, as from sounddevice) or ``(samples,)`` for mono.
                Internally transposed to planar ``(channels, frames)`` for
                PyAV's ``format="fltp"``.
        """
        if not self._is_open or self._stream is None or self._container is None:
            logger.warning("Cannot encode — audio encoder is not open")
            return

        try:
            # Convert to planar format (channels, frames) for PyAV's "fltp"
            # which is the native format for AAC encoding.  Packed format
            # "flt" expects shape (1, total_samples), not (channels, samples).
            planar_data = np.ascontiguousarray(audio_data.T) if audio_data.ndim > 1 else audio_data
            audio_frame = av.AudioFrame.from_ndarray(
                planar_data, format="fltp", layout=self._config.channel_layout
            )
            audio_frame.sample_rate = self._config.sample_rate

            for packet in self._stream.encode(audio_frame):
                self._container.mux(packet)

            self._frames_encoded += 1
            self.audio_encoded.emit(self._frames_encoded)
        except Exception as exc:
            msg = f"Error encoding audio frame: {exc}"
            logger.error(msg)
            self.encoding_error.emit(msg)

    def flush(self) -> None:
        """Flush the audio encoder by sending ``None`` frames to drain buffers."""
        if not self._is_open or self._stream is None or self._container is None:
            return

        try:
            for packet in self._stream.encode(None):
                self._container.mux(packet)
            logger.debug("Audio encoder flushed")
        except Exception as exc:
            logger.exception("Error flushing audio encoder: %s", exc)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return whether the encoder is currently open."""
        return self._is_open

    def get_stats(self) -> dict:
        """Return encoding statistics.

        Returns:
            A dict with keys ``frames_encoded``, ``start_time``,
            ``elapsed``, and ``fps``.
        """
        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.time() - self._start_time

        return {
            "frames_encoded": self._frames_encoded,
            "start_time": self._start_time,
            "elapsed": elapsed,
            "fps": self._frames_encoded / elapsed if elapsed > 0 else 0.0,
        }