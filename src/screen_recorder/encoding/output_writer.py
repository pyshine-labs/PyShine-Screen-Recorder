"""Output writer module — orchestrates video and audio encoding into a single file.

Provides :class:`OutputWriter` which coordinates :class:`VideoEncoder` and
:class:`AudioEncoder` to produce a combined output container, handling
timestamp/PTS mapping, pause/resume, and progress reporting.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger
from .audio_encoder import AudioEncoder, AudioEncoderConfig
from .video_encoder import VideoEncoder, VideoEncoderConfig, EncoderType


# ── Output format enum ─────────────────────────────────────────────────────────


class OutputFormat(Enum):
    """Supported output container formats."""

    MP4 = auto()
    MKV = auto()
    WEBM = auto()
    AVI = auto()


# ── Format extension mapping ───────────────────────────────────────────────────

_FORMAT_EXTENSIONS: dict[OutputFormat, str] = {
    OutputFormat.MP4: "mp4",
    OutputFormat.MKV: "mkv",
    OutputFormat.WEBM: "webm",
    OutputFormat.AVI: "avi",
}

_FORMAT_CONTAINER: dict[OutputFormat, str] = {
    OutputFormat.MP4: "mp4",
    OutputFormat.MKV: "matroska",
    OutputFormat.WEBM: "webm",
    OutputFormat.AVI: "avi",
}


# ── Recording configuration ───────────────────────────────────────────────────


@dataclass
class RecordingConfig:
    """Combined recording configuration for :class:`OutputWriter`.

    Attributes:
        output_path: Destination file path.  If empty, a timestamp-based
            path is generated automatically.
        format: Container format (MP4, MKV, WEBM, AVI).
        video_config: Video encoder configuration.
        audio_config: Audio encoder configuration.
        include_audio: Whether to include an audio stream.
    """

    output_path: str | Path = ""
    format: OutputFormat = OutputFormat.MP4
    video_config: VideoEncoderConfig = field(default_factory=VideoEncoderConfig)
    audio_config: AudioEncoderConfig = field(default_factory=AudioEncoderConfig)
    include_audio: bool = True


# ── Output writer class ───────────────────────────────────────────────────────


class OutputWriter(QObject):
    """Coordinate video and audio encoding into a single output file.

    This is the main orchestrator for the encoding pipeline.  It manages
    a single ``av`` output container with both video and (optionally) audio
    streams, handles PTS mapping, and provides pause/resume support.

    Signals:
        recording_started(str): Emitted with the output file path when
            recording begins.
        recording_stopped(str): Emitted with the output file path when
            recording ends.
        recording_error(str): Emitted with an error message on failure.
        progress_updated(dict): Emitted periodically with progress info
            (frames, duration, file size).
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    progress_updated = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:  # noqa: D107
        super().__init__(parent)
        self._config = RecordingConfig()
        self._container: av.container.OutputContainer | None = None
        self._video_stream: av.stream.Stream | None = None
        self._audio_stream: av.stream.Stream | None = None
        self._is_recording = False
        self._is_paused = False
        self._output_path: Path | None = None
        self._start_time: float | None = None
        self._pause_time: float | None = None
        self._total_paused_duration: float = 0.0
        self._video_frame_count: int = 0
        self._audio_frame_count: int = 0
        self._last_video_pts: int = -1
        self._last_audio_pts: int = -1
        self._audio_samples_written: int = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, config: RecordingConfig) -> None:
        """Set recording configuration.

        Must be called **before** :meth:`start`.  If a recording is in
        progress the configuration change is ignored and a warning is
        logged.
        """
        if self._is_recording:
            logger.warning("Cannot reconfigure while recording is in progress")
            return
        self._config = config
        logger.info("OutputWriter configured: %s", config)

    # ------------------------------------------------------------------
    # Recording lifecycle
    # ------------------------------------------------------------------

    def start(self, output_path: str | Path | None = None) -> None:
        """Start recording to the specified or generated output path.

        If *output_path* is ``None``, a timestamp-based path is generated
        using :meth:`_generate_output_path`.

        Args:
            output_path: Optional destination file path.  When ``None``,
                the path from the configuration is used, or a timestamp-
                based filename is generated.
        """
        if self._is_recording:
            logger.warning("Recording is already in progress")
            return

        # Resolve output path
        if output_path is not None:
            self._output_path = Path(output_path)
        elif self._config.output_path:
            self._output_path = Path(self._config.output_path)
        else:
            self._output_path = self._generate_output_path()

        # Ensure parent directory exists
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine container format string
        fmt_name = _FORMAT_CONTAINER.get(self._config.format, "mp4")

        # Resolve video codec name
        video_encoder = VideoEncoder(self)
        video_encoder.configure(self._config.video_config)
        codec_name = video_encoder.get_codec_name(self._config.video_config.encoder)

        try:
            self._container = av.open(str(self._output_path), mode="w", format=fmt_name)

            # ── Video stream ───────────────────────────────────────────
            # Ensure dimensions are even (required for yuv420p)
            width = self._config.video_config.width
            height = self._config.video_config.height
            if width % 2 != 0:
                width -= 1
            if height % 2 != 0:
                height -= 1

            self._video_stream = self._container.add_stream(codec_name, rate=self._config.video_config.fps)
            self._video_stream.width = width
            self._video_stream.height = height
            self._video_stream.pix_fmt = self._config.video_config.pixel_format
            # NOTE: Do NOT override stream.time_base — PyAV sets it automatically
            # from the `rate` parameter. Overriding creates a mismatch between
            # stream.time_base and codec_context.time_base, causing EINVAL (22)
            # on every mux() call.
            self._video_stream.bit_rate = self._config.video_config.bitrate * 1000

            # Codec-specific options — set on codec_context for proper propagation
            if codec_name == "libx264":
                self._video_stream.codec_context.options = {
                    "preset": self._config.video_config.quality_preset,
                    "threads": "4",
                }
            elif codec_name == "h264_nvenc":
                self._video_stream.codec_context.options = {
                    "preset": self._config.video_config.quality_preset,
                    "threads": "4",
                }
            elif codec_name == "h264_qsv":
                self._video_stream.codec_context.options = {
                    "preset": self._config.video_config.quality_preset,
                }
            elif codec_name == "h264_amf":
                self._video_stream.codec_context.options = {
                    "quality": self._config.video_config.quality_preset,
                }

            # ── Audio stream (optional) ─────────────────────────────────
            if self._config.include_audio:
                self._audio_stream = self._container.add_stream(
                    self._config.audio_config.codec,
                    rate=self._config.audio_config.sample_rate,
                )
                self._audio_stream.layout = self._config.audio_config.channel_layout
                self._audio_stream.bit_rate = self._config.audio_config.bitrate * 1000

            # Reset state
            self._video_frame_count = 0
            self._audio_frame_count = 0
            self._last_video_pts = -1
            self._last_audio_pts = -1
            self._audio_samples_written = 0
            self._total_paused_duration = 0.0
            self._is_recording = True
            self._is_paused = False
            self._start_time = time.time()

            self.recording_started.emit(str(self._output_path))
            logger.info(
                "Recording started: %s (video=%s, audio=%s)",
                self._output_path,
                codec_name,
                self._config.audio_config.codec if self._config.include_audio else "disabled",
            )
            # Diagnostic: log actual time_base values to catch mismatches
            logger.info(
                "Video stream configured: %dx%d @ %dfps, time_base=%s, codec_tb=%s",
                width, height, self._config.video_config.fps,
                self._video_stream.time_base,
                self._video_stream.codec_context.time_base,
            )
            if self._audio_stream is not None:
                logger.info(
                    "Audio stream configured: rate=%d, time_base=%s, codec_tb=%s",
                    self._config.audio_config.sample_rate,
                    self._audio_stream.time_base,
                    self._audio_stream.codec_context.time_base,
                )

        except Exception as exc:
            msg = f"Failed to start recording: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)
            # Clean up partial state
            if self._container is not None:
                try:
                    self._container.close()
                except Exception:
                    pass
            self._container = None
            self._video_stream = None
            self._audio_stream = None
            self._is_recording = False
            raise

    def stop(self) -> None:
        """Stop recording, flush encoders, and close the container."""
        if not self._is_recording:
            logger.warning("No recording in progress to stop")
            return

        self._is_recording = False
        self._is_paused = False

        # Flush video encoder
        if self._video_stream is not None and self._container is not None:
            try:
                for packet in self._video_stream.encode(None):
                    self._container.mux(packet)
            except Exception as exc:
                logger.exception("Error flushing video stream: %s", exc)

        # Flush audio encoder
        if self._audio_stream is not None and self._container is not None:
            try:
                for packet in self._audio_stream.encode(None):
                    self._container.mux(packet)
            except Exception as exc:
                logger.exception("Error flushing audio stream: %s", exc)

        # Close container
        if self._container is not None:
            try:
                self._container.close()
            except Exception as exc:
                logger.exception("Error closing output container: %s", exc)

        self._container = None
        self._video_stream = None
        self._audio_stream = None

        output_str = str(self._output_path) if self._output_path else ""
        self.recording_stopped.emit(output_str)
        logger.info(
            "Recording stopped: %s (%d video frames, %d audio frames)",
            output_str,
            self._video_frame_count,
            self._audio_frame_count,
        )

    def pause(self) -> None:
        """Pause recording — incoming frames will be discarded."""
        if not self._is_recording:
            return
        if self._is_paused:
            return
        self._is_paused = True
        self._pause_time = time.time()
        logger.debug("Recording paused")

    def resume(self) -> None:
        """Resume recording after a :meth:`pause`."""
        if not self._is_recording or not self._is_paused:
            return
        if self._pause_time is not None:
            self._total_paused_duration += time.time() - self._pause_time
            self._pause_time = None
        self._is_paused = False
        logger.debug("Recording resumed")

    # ------------------------------------------------------------------
    # Frame writing
    # ------------------------------------------------------------------

    def write_video_frame(self, frame: np.ndarray, timestamp: float) -> None:
        """Write a video frame to the output.

        Args:
            frame: RGB numpy array (H×W×3, uint8).
            timestamp: Presentation timestamp in seconds.
        """
        if not self._is_recording or self._is_paused:
            return
        if self._video_stream is None or self._container is None:
            return

        try:
            # Ensure frame dimensions match stream dimensions
            stream_h = self._video_stream.height
            stream_w = self._video_stream.width
            frame_h, frame_w = frame.shape[:2]

            if frame_h != stream_h or frame_w != stream_w:
                # Crop to match (take top-left portion)
                frame = frame[:stream_h, :stream_w]
                # Double-check after crop
                if frame.shape[0] != stream_h or frame.shape[1] != stream_w:
                    logger.warning(
                        "Frame dimensions %dx%d don't match stream %dx%d after crop, skipping frame",
                        frame.shape[1], frame.shape[0], stream_w, stream_h,
                    )
                    return

            video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")

            # Use the actual codec_context time_base (set by PyAV) for PTS
            tb = self._video_stream.codec_context.time_base
            if tb is None or tb == Fraction(0, 1):
                tb = Fraction(1, self._config.video_config.fps)
            elapsed = self._get_elapsed_time()
            video_pts = int(elapsed / float(tb))
            # Ensure strictly monotonically increasing PTS
            if video_pts <= self._last_video_pts:
                video_pts = self._last_video_pts + 1
            self._last_video_pts = video_pts
            video_frame.pts = video_pts
            video_frame.time_base = tb

            # Diagnostic: log first frame details
            if self._video_frame_count == 0:
                logger.info(
                    "First video frame: stream_tb=%s, codec_tb=%s, pts=%d, frame_tb=%s",
                    self._video_stream.time_base,
                    self._video_stream.codec_context.time_base,
                    video_pts,
                    video_frame.time_base,
                )

            for packet in self._video_stream.encode(video_frame):
                self._container.mux(packet)

            self._video_frame_count += 1

            # Emit progress every 30 frames
            if self._video_frame_count % 30 == 0:
                self._emit_progress()

        except Exception as exc:
            msg = f"Error writing video frame: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)

    def write_audio_data(self, audio_data: np.ndarray, timestamp: float = 0.0) -> None:
        """Write audio data to the output.

        Args:
            audio_data: Float32 numpy array in interleaved format
                ``(frames, channels)`` as provided by sounddevice.
                Internally transposed to planar ``(channels, frames)``
                for PyAV's ``format="fltp"`` which is the native format
                expected by the AAC encoder.
            timestamp: Presentation timestamp in seconds.  Defaults to
                0.0 as PTS is managed internally.
        """
        # Diagnostic logging (first frame + every 100th)
        if self._audio_frame_count == 0 or self._audio_frame_count % 100 == 0:
            rms = float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))
            logger.info(
                "write_audio_data: frame #%d, shape=%s, dtype=%s, RMS=%.4f, "
                "is_recording=%s, audio_stream=%s",
                self._audio_frame_count,
                audio_data.shape,
                audio_data.dtype,
                rms,
                self._is_recording,
                "None" if self._audio_stream is None else "present",
            )

        if not self._is_recording or self._is_paused:
            return
        if self._audio_stream is None or self._container is None:
            return

        try:
            # Validate channel count matches encoder layout (Bug #27 fix)
            actual_channels = audio_data.shape[1] if audio_data.ndim == 2 else 1
            expected_channels = 2 if self._config.audio_config.channel_layout == "stereo" else 1
            if actual_channels != expected_channels:
                logger.warning(
                    "Channel mismatch: data has %d channels but encoder expects '%s' (%d ch). "
                    "Padding/adjusting to match.",
                    actual_channels,
                    self._config.audio_config.channel_layout,
                    expected_channels,
                )
                if actual_channels < expected_channels:
                    # Pad mono to stereo by duplicating the channel
                    padding = np.tile(audio_data[:, 0:1], (1, expected_channels - actual_channels))
                    audio_data = np.concatenate([audio_data, padding], axis=1)
                elif actual_channels > expected_channels:
                    # Downmix to fewer channels by taking first N channels
                    audio_data = audio_data[:, :expected_channels]

            # sounddevice provides interleaved float32: (frames, channels).
            # PyAV's from_ndarray() for packed formats ("flt", "s16") expects
            # shape (1, total_samples), NOT (frames, channels) — passing the
            # wrong shape silently produces silent output (Bug #26).
            # The correct approach is to use planar format ("fltp") with the
            # data transposed to (channels, frames), which is what the AAC
            # encoder uses internally.  Using format="flt" with transposed
            # data caused the cartoon effect (Bug #24) because the packed
            # format interprets the transposed array as a single interleaved
            # buffer, scrambling channel ordering.
            planar_data = np.ascontiguousarray(audio_data.T)
            audio_frame = av.AudioFrame.from_ndarray(
                planar_data, format="fltp", layout=self._config.audio_config.channel_layout
            )
            audio_frame.sample_rate = self._config.audio_config.sample_rate

            # Audio PTS must use cumulative sample counting, NOT wall-clock time.
            # Wall-clock time creates gaps between audio chunks that the decoder
            # compresses, making audio play too fast.
            tb = self._audio_stream.codec_context.time_base
            if tb is None or tb == Fraction(0, 1):
                tb = Fraction(1, self._config.audio_config.sample_rate)
            # PTS = cumulative samples written, scaled to time_base
            # For audio, tb is typically 1/sample_rate, so pts = samples_written
            audio_pts = self._audio_samples_written
            # Ensure strictly monotonically increasing PTS
            if audio_pts <= self._last_audio_pts:
                audio_pts = self._last_audio_pts + 1
            self._last_audio_pts = audio_pts
            audio_frame.pts = audio_pts
            audio_frame.time_base = tb
            # Track cumulative samples for next frame's PTS.
            # audio_data.shape is (frames, channels) from sounddevice;
            # count frames (axis 0), not channels.
            self._audio_samples_written += audio_data.shape[0]

            for packet in self._audio_stream.encode(audio_frame):
                self._container.mux(packet)

            self._audio_frame_count += 1

        except Exception as exc:
            msg = f"Error writing audio data: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_recording(self) -> bool:
        """Return whether recording is currently active."""
        return self._is_recording

    def is_paused(self) -> bool:
        """Return whether recording is currently paused."""
        return self._is_paused

    def get_output_path(self) -> Path | None:
        """Return the current output file path, or ``None`` if not recording."""
        return self._output_path

    def get_recording_duration(self) -> float:
        """Return elapsed recording time in seconds (excluding paused time)."""
        return self._get_elapsed_time()

    def get_file_size(self) -> int:
        """Return the current output file size in bytes."""
        if self._output_path is None or not self._output_path.exists():
            return 0
        try:
            return os.path.getsize(self._output_path)
        except OSError:
            return 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_elapsed_time(self) -> float:
        """Get elapsed recording time in seconds (wall-clock, excluding paused time).

        Video PTS is derived from this wall-clock reference so frames are
        displayed at the correct real-time position.  Audio PTS uses
        cumulative sample counting instead (see ``write_audio_data``).
        """
        if self._start_time is None:
            return 0.0
        elapsed = time.time() - self._start_time - self._total_paused_duration
        if self._is_paused and self._pause_time is not None:
            elapsed -= time.time() - self._pause_time
        return max(0.0, elapsed)

    def _generate_output_path(self) -> Path:
        """Generate a timestamp-based output file path.

        Returns:
            A :class:`Path` with the pattern
            ``{output_dir}/recording_{timestamp}.{ext}``.
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = self._get_format_extension()
        filename = f"recording_{timestamp}.{ext}"

        # Use configured output directory, or default to Documents/Screen Recordings
        if self._config.output_path:
            output_dir = Path(self._config.output_path)
        else:
            output_dir = Path.home() / "Documents" / "Screen Recordings"

        return output_dir / filename

    def _get_format_extension(self) -> str:
        """Map :class:`OutputFormat` to a file extension string."""
        return _FORMAT_EXTENSIONS.get(self._config.format, "mp4")

    def _emit_progress(self) -> None:
        """Emit a progress update signal with current stats."""
        self.progress_updated.emit(
            {
                "video_frames": self._video_frame_count,
                "audio_frames": self._audio_frame_count,
                "duration": self.get_recording_duration(),
                "file_size": self.get_file_size(),
            }
        )