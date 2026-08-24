"""Video encoder module — hardware-accelerated encoding via PyAV.

Provides :class:`VideoEncoder` which encodes video frames using PyAV with
automatic hardware acceleration detection (NVENC, QuickSync, AMF) and a
libx264 software fallback.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger


# ── Encoder type enum ─────────────────────────────────────────────────────────


class EncoderType(Enum):
    """Available video encoder backends."""

    AUTO = auto()
    NVENC = auto()
    QSV = auto()
    AMF = auto()
    MF = auto()  # Windows Media Foundation (h264_mf)
    X264 = auto()


# ── Codec name mapping ─────────────────────────────────────────────────────────

_CODEC_MAP: dict[EncoderType, str] = {
    EncoderType.NVENC: "h264_nvenc",
    EncoderType.QSV: "h264_qsv",
    EncoderType.AMF: "h264_amf",
    EncoderType.MF: "h264_mf",
    EncoderType.X264: "libx264",
}

# Order in which hardware encoders are probed
# Note: h264_mf is excluded from auto-detection because it passes trivial tests
# but fails with real frames due to strict pixel format/requirements.
_HW_ENCODER_ORDER: list[EncoderType] = [EncoderType.NVENC, EncoderType.AMF, EncoderType.QSV]


# ── Video encoder configuration ────────────────────────────────────────────────


@dataclass
class VideoEncoderConfig:
    """Configuration for :class:`VideoEncoder`.

    Attributes:
        width: Output video width in pixels.
        height: Output video height in pixels.
        fps: Target frames per second.
        bitrate: Target bitrate in **kbps**.
        encoder: Preferred encoder backend.  ``AUTO`` triggers hardware
            detection at open time.
        codec: Codec identifier string (default ``"h264"``).
        quality_preset: Encoder quality/speed preset (e.g. ``"ultrafast"``,
            ``"fast"``, ``"medium"``, ``"slow"``).
        pixel_format: Output pixel format (e.g. ``"yuv420p"``).
    """

    width: int = 1920
    height: int = 1080
    fps: int = 30
    bitrate: int = 5000  # kbps
    encoder: EncoderType = EncoderType.AUTO
    codec: str = "h264"
    quality_preset: str = "medium"
    pixel_format: str = "yuv420p"


# ── Video encoder class ───────────────────────────────────────────────────────


class VideoEncoder(QObject):
    """Encode video frames using PyAV with hardware acceleration support.

    Signals:
        frame_encoded(int): Emitted with the frame number after successful
            encoding.
        encoding_error(str): Emitted with an error message on failure.
        encoding_finished(): Emitted when encoding is complete.
    """

    frame_encoded = pyqtSignal(int)
    encoding_error = pyqtSignal(str)
    encoding_finished = pyqtSignal()

    def __init__(self, parent=None) -> None:  # noqa: D107
        super().__init__(parent)
        self._config = VideoEncoderConfig()
        self._container: av.container.OutputContainer | None = None
        self._stream: av.stream.Stream | None = None
        self._is_open = False
        self._frames_encoded = 0
        self._start_time: float | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, config: VideoEncoderConfig) -> None:
        """Set encoder configuration.

        Must be called **before** :meth:`open`.  If the encoder is already
        open the configuration change is ignored and a warning is logged.
        """
        if self._is_open:
            logger.warning("Cannot reconfigure while encoder is open")
            return
        self._config = config
        logger.info("VideoEncoder configured: %s", config)

    # ------------------------------------------------------------------
    # Hardware detection
    # ------------------------------------------------------------------

    def _is_codec_available(self, codec_name: str) -> bool:
        """Check whether a codec can actually be used for encoding.

        Tries to instantiate the codec and encode a single dummy frame
        in an in-memory container.  Returns ``True`` on success.
        """
        try:
            test_codec = av.codec.Codec(codec_name, "w")
            import io
            # Use 'null' format which doesn't require seeking (works in-memory)
            test_container = av.open(io.BytesIO(), mode="w", format="null")
            try:
                test_stream = test_container.add_stream(test_codec, rate=30)
                test_stream.width = 64
                test_stream.height = 64
                test_stream.pix_fmt = "yuv420p"
                dummy = av.VideoFrame(64, 64, "rgb24")
                for packet in test_stream.encode(dummy):
                    test_container.mux(packet)
                for packet in test_stream.encode(None):
                    test_container.mux(packet)
                return True
            finally:
                test_container.close()
        except Exception:
            logger.debug("Codec %s is not available", codec_name)
            return False

    def get_codec_name(self, encoder_type: EncoderType) -> str:
        """Map an :class:`EncoderType` to its FFmpeg codec name string.

        For ``AUTO``, probes hardware encoders in order.  For explicit
        encoder types, verifies the codec is actually usable and falls
        back to libx264 if it is not (e.g. QSV saved in settings but
        not available in the current FFmpeg build).
        """
        if encoder_type == EncoderType.AUTO:
            for hw_type in _HW_ENCODER_ORDER:
                name = _CODEC_MAP[hw_type]
                if self._is_codec_available(name):
                    logger.info("Auto-selected hardware encoder: %s", name)
                    return name
            logger.info("No hardware encoder available — using libx264")
            return _CODEC_MAP[EncoderType.X264]

        # Explicit choice: verify it works, otherwise fall back
        name = _CODEC_MAP.get(encoder_type, "libx264")
        if self._is_codec_available(name):
            return name
        logger.warning("Configured encoder %s (%s) not available — falling back to libx264",
                       encoder_type.name, name)
        return _CODEC_MAP[EncoderType.X264]

    # ------------------------------------------------------------------
    # Open / Close
    # ------------------------------------------------------------------

    def open(self, output_path: str | Path) -> None:
        """Open an output container and add a video stream.

        Args:
            output_path: Destination file path for the encoded video.
        """
        if self._is_open:
            logger.warning("Encoder is already open")
            return

        output_path = Path(output_path)
        codec_name = self.get_codec_name(self._config.encoder)

        try:
            self._container = av.open(str(output_path), mode="w")
            self._stream = self._container.add_stream(codec_name, rate=self._config.fps)
            self._stream.width = self._config.width
            self._stream.height = self._config.height
            self._stream.pix_fmt = self._config.pixel_format
            self._stream.time_base = Fraction(1, self._config.fps)

            # Bitrate is specified in kbps in config; convert to bps
            self._stream.bit_rate = self._config.bitrate * 1000

            # Quality preset — option key varies by codec
            if codec_name == "libx264":
                self._stream.options = {"preset": self._config.quality_preset}
            elif codec_name in ("h264_nvenc",):
                self._stream.options = {"preset": self._config.quality_preset}
            elif codec_name == "h264_qsv":
                self._stream.options = {"preset": self._config.quality_preset}
            elif codec_name == "h264_amf":
                self._stream.options = {"quality": self._config.quality_preset}

            self._is_open = True
            self._frames_encoded = 0
            self._start_time = time.time()
            logger.info(
                "Video encoder opened: %s (%dx%d @ %dfps, %dkbps)",
                codec_name,
                self._config.width,
                self._config.height,
                self._config.fps,
                self._config.bitrate,
            )
        except Exception as exc:
            msg = f"Failed to open video encoder: {exc}"
            logger.error(msg)
            self.encoding_error.emit(msg)
            # Attempt fallback to libx264 if a hardware codec failed
            if self._config.encoder != EncoderType.X264:
                logger.info("Attempting fallback to libx264")
                self._config.encoder = EncoderType.X264
                self.open(output_path)
            else:
                raise

    def close(self) -> None:
        """Flush remaining frames and close the output container."""
        if not self._is_open:
            return
        self.flush()
        if self._container is not None:
            try:
                self._container.close()
            except Exception as exc:
                logger.exception("Error closing video container: %s", exc)
        self._is_open = False
        self._stream = None
        self._container = None
        self.encoding_finished.emit()
        logger.info("Video encoder closed — %d frames encoded", self._frames_encoded)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode_frame(self, frame_data: np.ndarray) -> None:
        """Encode a single video frame.

        Args:
            frame_data: RGB numpy array (H×W×3, uint8).
        """
        if not self._is_open or self._stream is None or self._container is None:
            logger.warning("Cannot encode — encoder is not open")
            return

        try:
            video_frame = av.VideoFrame.from_ndarray(frame_data, format="rgb24")
            for packet in self._stream.encode(video_frame):
                self._container.mux(packet)

            self._frames_encoded += 1
            self.frame_encoded.emit(self._frames_encoded)
        except Exception as exc:
            msg = f"Error encoding video frame: {exc}"
            logger.error(msg)
            self.encoding_error.emit(msg)

    def flush(self) -> None:
        """Flush the encoder by sending ``None`` frames to drain buffers."""
        if not self._is_open or self._stream is None or self._container is None:
            return

        try:
            for packet in self._stream.encode(None):
                self._container.mux(packet)
            logger.debug("Video encoder flushed")
        except Exception as exc:
            logger.exception("Error flushing video encoder: %s", exc)

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