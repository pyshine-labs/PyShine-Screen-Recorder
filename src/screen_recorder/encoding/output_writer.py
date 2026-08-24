"""Output writer module — orchestrates video and audio encoding into a single file.

Key design decisions for perfect A/V sync (strict CFR):
- Video PTS = frame_index (0, 1, 2, ...) with time_base = 1/fps → perfect CFR output
- Audio PTS = cumulative sample count with time_base = 1/sample_rate → sample-accurate
- Wall-clock (time.perf_counter()) is used ONLY for initial audio/video alignment offset
- After initial alignment, both streams advance strictly linearly — NO runtime drift correction
- Single shared epoch t0 (set when first video frame is written) for initial offset calculation
- Real-time encoder presets (ultrafast/zerolatency for x264, fastest for hardware)
- Automatic resolution downscaling for software (libx264) encoding at >1080p
- Uses threading.Event.wait() in the worker (no time.sleep, no busy loops)
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


class OutputFormat(Enum):
    MP4 = auto()
    MKV = auto()
    WEBM = auto()
    AVI = auto()


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

# Maximum width for software (libx264) encoding to guarantee real-time performance
_SW_MAX_WIDTH = 1920


@dataclass
class RecordingConfig:
    output_path: str | Path = ""
    format: OutputFormat = OutputFormat.MP4
    video_config: VideoEncoderConfig = field(default_factory=VideoEncoderConfig)
    audio_config: AudioEncoderConfig = field(default_factory=AudioEncoderConfig)
    include_audio: bool = True


class OutputWriter(QObject):
    """Coordinate video and audio encoding into a single output file.

    Signals:
        recording_started(str): Output path when recording begins.
        recording_stopped(str): Output path when recording ends.
        recording_error(str): Error message on failure.
        progress_updated(dict): Periodic progress info.
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    progress_updated = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config = RecordingConfig()
        self._container: av.container.OutputContainer | None = None
        self._video_stream: av.stream.Stream | None = None
        self._audio_stream: av.stream.Stream | None = None
        self._is_recording = False
        self._is_paused = False
        self._output_path: Path | None = None

        # PTS tracking using shared monotonic clock
        self._t0: float | None = None  # epoch (perf_counter of first video frame)
        self._video_frame_count: int = 0
        self._last_video_pts: int = -1
        self._audio_samples_written: int = 0
        self._audio_started: bool = False

        # Encoding dimensions (may differ from capture due to downscaling)
        self._encode_width: int = 0
        self._encode_height: int = 0
        self._is_software_encoder: bool = False

    def configure(self, config: RecordingConfig) -> None:
        if self._is_recording:
            logger.warning("Cannot reconfigure while recording is in progress")
            return
        self._config = config
        logger.info("OutputWriter configured: %s", config)

    def start(self, output_path: str | Path | None = None) -> None:
        if self._is_recording:
            logger.warning("Recording is already in progress")
            return

        if output_path is not None:
            self._output_path = Path(output_path)
        elif self._config.output_path:
            self._output_path = Path(self._config.output_path)
        else:
            self._output_path = self._generate_output_path()

        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        fmt_name = _FORMAT_CONTAINER.get(self._config.format, "mp4")

        video_encoder = VideoEncoder(self)
        video_encoder.configure(self._config.video_config)
        codec_name = video_encoder.get_codec_name(self._config.video_config.encoder)

        # Determine encoding dimensions — downscale for software encoder if needed
        cap_w = self._config.video_config.width
        cap_h = self._config.video_config.height
        if cap_w % 2 != 0:
            cap_w -= 1
        if cap_h % 2 != 0:
            cap_h -= 1

        self._is_software_encoder = (codec_name == "libx264")
        if self._is_software_encoder and cap_w > _SW_MAX_WIDTH:
            scale = _SW_MAX_WIDTH / cap_w
            self._encode_width = _SW_MAX_WIDTH
            self._encode_height = int(cap_h * scale)
            if self._encode_height % 2 != 0:
                self._encode_height -= 1
            logger.info(
                "Software encoder: downscaling from %dx%d to %dx%d for real-time performance",
                cap_w, cap_h, self._encode_width, self._encode_height,
            )
        else:
            self._encode_width = cap_w
            self._encode_height = cap_h

        try:
            self._container = av.open(str(self._output_path), mode="w", format=fmt_name)

            # ── Video stream ───────────────────────────────────────────
            width = self._encode_width
            height = self._encode_height
            fps = self._config.video_config.fps

            self._video_stream = self._container.add_stream(codec_name, rate=fps)
            self._video_stream.width = width
            self._video_stream.height = height
            self._video_stream.pix_fmt = self._config.video_config.pixel_format
            self._video_stream.time_base = Fraction(1, fps)

            # Real-time encoding options — fastest possible for live screen capture.
            if codec_name == "libx264":
                self._video_stream.options = {
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "crf": "23",
                    "threads": "0",
                    "x264-params": "force-cfr=1:scenecut=0:aq-mode=1:keyint=60",
                }
            elif codec_name == "h264_nvenc":
                self._video_stream.options = {
                    "preset": "p1",
                    "rc": "cbr",
                    "b:v": str(self._config.video_config.bitrate) + "k",
                    "tune": "ll",
                    "bf": "0",
                    "gop": str(fps * 2),
                }
            elif codec_name == "h264_qsv":
                self._video_stream.options = {
                    "preset": "veryfast",
                    "global_quality": "28",
                    "gop": str(fps * 2),
                }
            elif codec_name == "h264_amf":
                self._video_stream.options = {
                    "usage": "ultralowlatency",
                    "quality": "speed",
                    "rc": "cqp",
                    "qp_i": "28",
                    "qp_p": "30",
                    "bf": "0",
                    "gop": str(fps * 2),
                }

            # ── Audio stream (optional) ─────────────────────────────────
            if self._config.include_audio:
                self._audio_stream = self._container.add_stream(
                    self._config.audio_config.codec,
                    rate=self._config.audio_config.sample_rate,
                )
                self._audio_stream.layout = self._config.audio_config.channel_layout
                self._audio_stream.bit_rate = self._config.audio_config.bitrate * 1000

            self._t0 = None
            self._video_frame_count = 0
            self._audio_samples_written = 0
            self._last_video_pts = -1
            self._audio_started = False
            self._is_recording = True
            self._is_paused = False

            self.recording_started.emit(str(self._output_path))
            logger.info(
                "Recording started: %s (video=%s, audio=%s, %dx%d @ %dfps)",
                self._output_path, codec_name,
                self._config.audio_config.codec if self._config.include_audio else "disabled",
                width, height, fps,
            )

        except Exception as exc:
            msg = f"Failed to start recording: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)
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
        if not self._is_recording:
            logger.warning("No recording in progress to stop")
            return
        self._is_recording = False
        self._is_paused = False

        if self._video_stream is not None and self._container is not None:
            try:
                for packet in self._video_stream.encode(None):
                    self._container.mux(packet)
            except Exception:
                logger.exception("Error flushing video stream")

        if self._audio_stream is not None and self._container is not None:
            try:
                for packet in self._audio_stream.encode(None):
                    self._container.mux(packet)
            except Exception:
                logger.exception("Error flushing audio stream")

        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                logger.exception("Error closing output container")

        self._container = None
        self._video_stream = None
        self._audio_stream = None

        output_str = str(self._output_path) if self._output_path else ""
        self.recording_stopped.emit(output_str)
        if self._t0 is not None:
            duration = time.perf_counter() - self._t0
            logger.info(
                "Recording stopped: %s (%d video frames, %.1fs wall)",
                output_str, self._video_frame_count, duration,
            )
        else:
            logger.info("Recording stopped: %s (%d video frames)", output_str, self._video_frame_count)

    def pause(self) -> None:
        if not self._is_recording or self._is_paused:
            return
        self._is_paused = True
        logger.debug("Recording paused")

    def resume(self) -> None:
        if not self._is_recording or not self._is_paused:
            return
        self._is_paused = False
        logger.debug("Recording resumed")

    # ── Frame writing ────────────────────────────────────────────────────

    def write_video_frame(self, frame: np.ndarray, pts_timestamp: float | None = None) -> None:
        """Write a video frame with strict CFR PTS = frame_index.

        The first video frame sets the epoch t0 (wall-clock reference for audio
        alignment) and gets PTS=0. All subsequent frames use sequential PTS
        (1, 2, 3, ...) for perfect constant frame rate output. Wall-clock time
        is NOT used for video PTS calculation — that would cause drift when the
        encoder temporarily falls behind or catches up.

        Args:
            frame: RGB numpy array (H×W×3, uint8).
            pts_timestamp: time.perf_counter() value at frame capture. Used only
                to set t0 on the first frame for audio alignment.
        """
        if not self._is_recording or self._is_paused:
            return
        if self._video_stream is None or self._container is None:
            return

        try:
            fps = self._config.video_config.fps
            encode_h = self._encode_height
            encode_w = self._encode_width

            # Fast resize if needed
            frame_h, frame_w = frame.shape[:2]
            if frame_h != encode_h or frame_w != encode_w:
                frame = self._fast_resize(frame, encode_w, encode_h)

            video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")

            # Strict CFR: PTS = frame index (0, 1, 2, ...)
            pts = self._video_frame_count

            # Set epoch t0 on first frame (used only for audio alignment offset)
            if self._t0 is None and pts_timestamp is not None:
                self._t0 = pts_timestamp

            video_frame.pts = pts
            video_frame.time_base = Fraction(1, fps)
            self._last_video_pts = pts

            for packet in self._video_stream.encode(video_frame):
                self._container.mux(packet)

            self._video_frame_count += 1

            if self._video_frame_count % 60 == 0:
                self._emit_progress()

        except Exception as exc:
            msg = f"Error writing video frame: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)

    def write_audio_data(self, audio_data: np.ndarray, pts_timestamp: float | None = None) -> None:
        """Write audio data with strict cumulative-sample PTS.

        Audio PTS starts at an offset calculated from the wall-clock gap between
        the first audio chunk and the first video frame (t0), ensuring both
        streams begin at the same point on the timeline. After initial alignment,
        PTS advances strictly by num_samples per chunk — NO runtime drift
        correction, which would cause audible glitches and A/V desync.

        Args:
            audio_data: float32 numpy array (frames×channels).
            pts_timestamp: time.perf_counter() when the chunk was received. Used
                only for initial alignment offset on the first chunk.
        """
        if not self._is_recording or self._is_paused:
            return
        if self._audio_stream is None or self._container is None:
            return

        try:
            actual_channels = audio_data.shape[1] if audio_data.ndim == 2 else 1
            expected_channels = 2 if self._config.audio_config.channel_layout == "stereo" else 1
            if actual_channels != expected_channels:
                if actual_channels < expected_channels:
                    padding = np.tile(audio_data[:, 0:1], (1, expected_channels - actual_channels))
                    audio_data = np.concatenate([audio_data, padding], axis=1)
                elif actual_channels > expected_channels:
                    audio_data = audio_data[:, :expected_channels]

            planar_data = np.ascontiguousarray(audio_data.T)
            audio_frame = av.AudioFrame.from_ndarray(
                planar_data, format="fltp", layout=self._config.audio_config.channel_layout
            )
            audio_frame.sample_rate = self._config.audio_config.sample_rate

            sample_rate = self._config.audio_config.sample_rate
            num_samples = audio_data.shape[0]

            # Calculate initial audio offset on first chunk (align to video timeline)
            if not self._audio_started:
                self._audio_started = True
                if self._t0 is not None and pts_timestamp is not None:
                    # Video already started: calculate gap from t0 to this chunk's arrival
                    elapsed = pts_timestamp - self._t0
                    # Center-align: subtract half chunk duration so the midpoint of this
                    # buffer lands at the correct elapsed time
                    chunk_duration = num_samples / sample_rate
                    self._audio_samples_written = max(
                        0, int((elapsed - chunk_duration * 0.5) * sample_rate)
                    )
                    logger.info(
                        "Audio starting at t=%.3fs (video at frame %d, %d samples offset)",
                        elapsed, self._last_video_pts + 1, self._audio_samples_written,
                    )
                else:
                    self._audio_samples_written = 0

            # Strict cumulative PTS: always advance by num_samples, no corrections
            audio_frame.pts = self._audio_samples_written
            audio_frame.time_base = Fraction(1, sample_rate)
            self._audio_samples_written += num_samples

            for packet in self._audio_stream.encode(audio_frame):
                self._container.mux(packet)

        except Exception as exc:
            msg = f"Error writing audio data: {exc}"
            logger.error(msg)
            self.recording_error.emit(msg)

    # ── State queries ────────────────────────────────────────────────────

    def is_recording(self) -> bool:
        return self._is_recording

    def is_paused(self) -> bool:
        return self._is_paused

    def get_output_path(self) -> Path | None:
        return self._output_path

    def get_recording_duration(self) -> float:
        """Current recording duration in seconds based on elapsed wall-clock time."""
        if self._t0 is None:
            return 0.0
        return time.perf_counter() - self._t0

    def get_file_size(self) -> int:
        if self._output_path is None or not self._output_path.exists():
            return 0
        try:
            return os.path.getsize(self._output_path)
        except OSError:
            return 0

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _fast_resize(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """Fast image resize optimized for screen recording downscaling.

        Uses numpy stride slicing for exact integer downscales (instant, zero-quality-loss
        for 2× case like 4K→1080p). Falls back to area-averaging for general cases.
        """
        h, w = frame.shape[:2]
        if w == target_w and h == target_h:
            return frame

        # Exact integer downscale (most common: 4K→1080p is exactly 2×)
        scale_x = w / target_w
        scale_y = h / target_h
        if abs(scale_x - scale_y) < 0.01 and abs(scale_x - round(scale_x)) < 0.01:
            step = int(round(scale_x))
            if step >= 2:
                return np.ascontiguousarray(frame[::step, ::step, :][:target_h, :target_w])

        # General case: cv2 resize if available
        try:
            import cv2
            return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        except ImportError:
            pass

        # Fallback: nearest-neighbor using computed indices
        row_idx = np.linspace(0, h - 1, target_h).astype(np.intp)
        col_idx = np.linspace(0, w - 1, target_w).astype(np.intp)
        return np.ascontiguousarray(frame[row_idx[:, None], col_idx])

    def _generate_output_path(self) -> Path:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = _FORMAT_EXTENSIONS.get(self._config.format, "mp4")
        filename = f"recording_{timestamp}.{ext}"
        if self._config.output_path:
            output_dir = Path(self._config.output_path)
        else:
            output_dir = Path.home() / "Documents" / "Screen Recordings"
        return output_dir / filename

    def _emit_progress(self) -> None:
        self.progress_updated.emit({
            "video_frames": self._video_frame_count,
            "duration": self.get_recording_duration(),
            "file_size": self.get_file_size(),
        })
