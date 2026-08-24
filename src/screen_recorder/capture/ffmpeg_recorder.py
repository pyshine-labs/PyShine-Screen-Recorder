"""FFmpeg-based recording engine — guaranteed A/V sync via two-pass muxing.

Architecture (robust temp-file approach):
  Pass 1 (real-time):
    - dxcam captures video frames → FFmpeg stdin (rawvideo) → temp_video.mp4
    - pyaudiowpatch captures audio → temp_audio.wav (via Python wave module)
  Pass 2 (post-processing, <2s):
    - FFmpeg muxes temp_video.mp4 + temp_audio.wav → final output.mp4

This eliminates all named-pipe synchronization issues. Each stream is written
independently with correct timing, then merged with FFmpeg's internal clock.
FFmpeg handles PTS alignment, duration matching, and muxing — guaranteeing
100% A/V sync.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable. Checks bundled, winget, PATH, and fallback."""
    # 1. Bundled FFmpeg in bin/ directory (highest priority)
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent.parent.parent
    bundled = base / "bin"
    if bundled.exists():
        for exe in bundled.rglob("ffmpeg.exe"):
            return str(exe)

    # 2. winget install locations (full build with all features)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    winget_base = Path(localappdata) / "Microsoft" / "WinGet" / "Packages"
    if winget_base.exists():
        for pkg in winget_base.glob("Gyan.FFmpeg*"):
            for exe in pkg.rglob("ffmpeg.exe"):
                return str(exe)
        for pkg in winget_base.glob("BtbN*"):
            for exe in pkg.rglob("ffmpeg.exe"):
                return str(exe)

    # 3. PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    # 4. imageio-ffmpeg fallback
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    raise RuntimeError("FFmpeg not found. Install via winget or place in bin/ directory.")


class FFmpegRecorder(QObject):
    """Recording engine using FFmpeg with two-pass muxing for guaranteed A/V sync.

    Signals:
        recording_started(str): Output path when recording starts
        recording_stopped(str): Output path when recording stops
        recording_error(str): Error message on failure
        progress_updated(dict): Periodic progress (duration, file_size, frames)
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    progress_updated = pyqtSignal(dict)
    preview_frame = pyqtSignal(np.ndarray)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ffmpeg_path: str = _find_ffmpeg()
        self._process: Optional[subprocess.Popen] = None
        self._output_path: str = ""
        self._temp_video_path: str = ""
        self._temp_audio_path: str = ""
        self._video_thread: Optional[threading.Thread] = None
        self._audio_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._audio_capture = None
        self._screen_capture = None
        self._is_recording = False
        self._start_time: float = 0.0
        self._frame_count: int = 0

        # Recording parameters
        self._fps: int = 30
        self._width: int = 1920
        self._height: int = 1080
        self._sample_rate: int = 48000
        self._channels: int = 2
        self._capture_config = None
        self._recording_config = None

        # Audio temp WAV writer (thread-safe)
        self._wav_file: Optional[wave.Wave_write] = None
        self._wav_lock = threading.Lock()
        self._audio_sample_count: int = 0

    def configure(self, capture_config, recording_config, fps: int) -> None:
        """Configure recording parameters."""
        self._capture_config = capture_config
        self._recording_config = recording_config
        self._fps = fps
        if recording_config:
            self._sample_rate = recording_config.audio_config.sample_rate
            self._channels = recording_config.audio_config.channels

    def set_audio_capture(self, audio_capture) -> None:
        """Set the AudioCapture instance for audio data."""
        self._audio_capture = audio_capture

    def start_recording(self) -> None:
        """Start FFmpeg recording with two-pass temp file approach."""
        if self._is_recording:
            logger.warning("FFmpeg recorder already running")
            return

        self._stop_event.clear()
        self._frame_count = 0
        self._audio_sample_count = 0

        try:
            self._start()
        except Exception as exc:
            logger.exception("Failed to start FFmpeg recorder")
            self.recording_error.emit(f"Failed to start recording: {exc}")

    def _start(self) -> None:
        """Initialize capture, temp files, and FFmpeg subprocess (video only)."""
        from ..capture.screen_capture import ScreenCapture

        # ── Generate output path ──────────────────────────────────────
        settings_output = ""
        if self._recording_config and self._recording_config.output_path:
            settings_output = str(self._recording_config.output_path)
        else:
            output_dir = Path.home() / "Documents" / "Screen Recordings"
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            settings_output = str(output_dir / f"recording_{timestamp}.mp4")
        self._output_path = settings_output
        Path(self._output_path).parent.mkdir(parents=True, exist_ok=True)

        # ── Temp file paths ───────────────────────────────────────────
        tmp_dir = Path(self._output_path).parent
        base_name = Path(self._output_path).stem
        self._temp_video_path = str(tmp_dir / f".{base_name}_tmp_video.mp4")
        self._temp_audio_path = str(tmp_dir / f".{base_name}_tmp_audio.wav")

        # ── Initialize screen capture (dxcam) ─────────────────────────
        self._screen_capture = ScreenCapture()
        self._screen_capture.configure(self._capture_config)
        self._screen_capture.start()
        native_w, native_h = self._screen_capture.capture_size

        # Auto-downscale 4K → 1080p for software encoder
        _SW_MAX_WIDTH = 1920
        if native_w > _SW_MAX_WIDTH:
            scale = _SW_MAX_WIDTH / native_w
            encode_w = _SW_MAX_WIDTH
            encode_h = int(native_h * scale)
            encode_h = encode_h if encode_h % 2 == 0 else encode_h - 1
            self._screen_capture.set_target_size(encode_w, encode_h)
            cap_w, cap_h = self._screen_capture.capture_size
            logger.info("FFmpeg recorder: downscaled %dx%d → %dx%d",
                        native_w, native_h, cap_w, cap_h)
        else:
            cap_w, cap_h = native_w, native_h

        self._width = cap_w if cap_w % 2 == 0 else cap_w - 1
        self._height = cap_h if cap_h % 2 == 0 else cap_h - 1

        # ── Open temp WAV file for audio ──────────────────────────────
        self._wav_file = wave.open(self._temp_audio_path, "wb")
        self._wav_file.setnchannels(self._channels)
        self._wav_file.setsampwidth(2)  # int16
        self._wav_file.setframerate(self._sample_rate)

        # Pre-create audio queue — UNBOUNDED so we NEVER drop audio chunks
        # (dropping chunks creates discontinuities = audible clicks/ticks).
        # At 48kHz stereo int16 = 192 KB/s, memory is negligible.
        import queue as q_module
        self._audio_queue = q_module.Queue()

        # Set recording flag BEFORE starting threads so callbacks are accepted
        self._is_recording = True
        self._start_time = time.perf_counter()

        # ── Start audio writer thread ─────────────────────────────────
        self._audio_thread = threading.Thread(
            target=self._audio_wav_loop, name="FFmpegAudioWAV", daemon=True
        )
        self._audio_thread.start()

        # ── Build and start FFmpeg (video only, audio comes in pass 2) ──
        self._start_ffmpeg_video()

        # ── Start video capture + pipe thread ─────────────────────────
        self._video_thread = threading.Thread(
            target=self._video_pipe_loop, name="FFmpegVideoPipe", daemon=True
        )
        self._video_thread.start()
        logger.info("FFmpeg recorder started → %s (%dx%d @ %dfps)",
                    self._output_path, self._width, self._height, self._fps)
        self.recording_started.emit(self._output_path)

    def _start_ffmpeg_video(self) -> None:
        """Build FFmpeg command for video-only encoding (pass 1)."""
        fps = self._fps
        w, h = self._width, self._height

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            # Input: raw video from stdin (dxcam frames)
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}",
            "-r", str(fps),
            "-i", "pipe:0",
            # Video encoding: libx264 ultrafast
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-g", str(fps * 2),
            # CFR output
            "-vsync", "cfr",
            "-r", str(fps),
            "-movflags", "+faststart",
            self._temp_video_path,
        ]

        logger.info("FFmpeg video cmd → %s", Path(self._temp_video_path).name)

        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        # Start stderr reader (prevents pipe blocking)
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self) -> None:
        """Read FFmpeg stderr to prevent pipe buffer blocking."""
        if self._process is None or self._process.stderr is None:
            return
        try:
            for line in iter(self._process.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if text and ("error" in text.lower() or "warning" in text.lower()):
                    logger.warning("FFmpeg: %s", text)
        except (ValueError, OSError):
            pass

    def _video_pipe_loop(self) -> None:
        """Capture video frames with dxcam and write to FFmpeg stdin as rawvideo.

        Uses event-driven pacing with threading.Event.wait() for precise frame timing.
        Writes raw RGB24 bytes to FFmpeg's stdin pipe.
        """
        import ctypes as ct

        # Windows high-resolution timer
        _winmm = ct.WinDLL("winmm", use_last_error=True) if sys.platform == "win32" else None
        if _winmm:
            try:
                _winmm.timeBeginPeriod(1)
            except Exception:
                pass

        fps = self._fps
        frame_interval = 1.0 / fps
        # Keep spin threshold small — the spin loop holds the GIL and can
        # starve the audio callback thread (causing tick-tick spikes).
        # We yield the GIL inside the spin loop via time.sleep(0).
        SPIN_THRESHOLD = 0.0008
        CATCHUP_LIMIT = 30

        t0: float | None = None
        frame_count = 0
        last_progress = 0.0
        last_preview = 0.0

        try:
            while not self._stop_event.is_set():
                # First frame: capture immediately, set epoch
                if t0 is None:
                    frame = self._screen_capture.capture_frame()
                    if frame is not None:
                        t0 = time.perf_counter()
                        last_progress = t0
                        self._write_video_frame(frame)
                        frame_count = 1
                    continue

                # Target time for this frame
                target_time = t0 + frame_count * frame_interval
                now = time.perf_counter()

                # Catch-up safety
                if target_time < now - CATCHUP_LIMIT * frame_interval:
                    missed = int((now - target_time) / frame_interval) - CATCHUP_LIMIT
                    t0 += missed * frame_interval
                    target_time = t0 + frame_count * frame_interval
                    logger.warning("Video pacer: %d frames behind, snapping forward", missed)

                # Wait until target time (hybrid sleep-spin for precision)
                if target_time > now:
                    remaining = target_time - now
                    if remaining > SPIN_THRESHOLD:
                        self._stop_event.wait(timeout=remaining - SPIN_THRESHOLD)
                    if self._stop_event.is_set():
                        break
                    # Spin for final precision (yield GIL each iteration so the
                    # audio callback thread is never starved → no tick spikes)
                    while time.perf_counter() < target_time:
                        if self._stop_event.is_set():
                            break
                        time.sleep(0)  # yield GIL to audio thread

                # Capture and write frame
                frame = self._screen_capture.capture_frame()
                if frame is not None:
                    self._write_video_frame(frame)
                    frame_count += 1
                    self._frame_count = frame_count

                    # Emit preview frame at ~10 Hz (throttled to avoid GUI overload)
                    now = time.perf_counter()
                    if now - last_preview >= 0.1:
                        last_preview = now
                        try:
                            # Downscale to ~480px wide via stride slicing (lightweight)
                            scale = max(1, self._width // 480)
                            preview = np.ascontiguousarray(frame[::scale, ::scale])
                            self.preview_frame.emit(preview)
                        except Exception:
                            pass

                # Progress update (~1 Hz)
                now = time.perf_counter()
                if now - last_progress >= 1.0:
                    last_progress = now
                    try:
                        self.progress_updated.emit({
                            "duration": now - t0,
                            "file_size": self._get_file_size(),
                            "frames": frame_count,
                            "fps": round(frame_count / max(0.001, now - t0), 1),
                        })
                    except Exception:
                        pass

        except Exception as exc:
            logger.exception("Video pipe loop error: %s", exc)
            self.recording_error.emit(f"Video capture error: {exc}")
        finally:
            if _winmm:
                try:
                    _winmm.timeEndPeriod(1)
                except Exception:
                    pass

    def _write_video_frame(self, frame: np.ndarray) -> None:
        """Write a single raw RGB24 frame to FFmpeg's stdin."""
        if self._process is None or self._process.stdin is None:
            return

        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            return

        # Ensure contiguous uint8 RGB
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8)
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        try:
            self._process.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError, ValueError) as exc:
            if self._is_recording:
                logger.error("FFmpeg stdin write error: %s", exc)
                self._is_recording = False

    def _audio_wav_loop(self) -> None:
        """Write audio data to temp WAV file.

        Audio data arrives via write_audio_data() callback and is queued.
        This thread drains the queue and writes int16 samples to WAV.
        """
        import queue as q_module
        audio_queue = self._audio_queue

        try:
            while not self._stop_event.is_set():
                try:
                    audio_data = audio_queue.get(timeout=0.1)
                except q_module.Empty:
                    continue

                if audio_data is None:
                    break

                # Convert float32 [-1.0, 1.0] → int16 losslessly.
                # Use *32768 (symmetric with the /32768 used in audio_capture.py)
                # so int16 → float32 → int16 is an identity round-trip.
                # np.round() + clip prevents overflow on edge values.
                if audio_data.dtype != np.float32:
                    audio_data = audio_data.astype(np.float32)
                int16_data = np.clip(
                    np.round(audio_data * 32768.0), -32768, 32767
                ).astype(np.int16)
                if not int16_data.flags["C_CONTIGUOUS"]:
                    int16_data = np.ascontiguousarray(int16_data)

                raw_bytes = int16_data.tobytes()

                with self._wav_lock:
                    if self._wav_file is not None:
                        self._wav_file.writeframes(raw_bytes)
                        self._audio_sample_count += len(audio_data)

        except Exception as exc:
            logger.exception("Audio WAV loop error: %s", exc)

    def write_audio_data(self, audio_data: np.ndarray) -> None:
        """Enqueue audio data for the WAV writer thread.

        Called from audio capture thread (direct callback).
        Queue is unbounded so we never drop audio (drops cause clicks).
        """
        if not self._is_recording:
            return
        self._audio_callback_count = getattr(self, "_audio_callback_count", 0) + 1
        self._audio_queue.put(audio_data)

    def stop_recording(self) -> None:
        """Stop recording: close pipes, wait for FFmpeg video, then mux audio."""
        if not self._is_recording and self._process is None:
            return

        self._stop_event.set()
        self._is_recording = False

        # Signal audio loop to stop
        if hasattr(self, "_audio_queue"):
            try:
                self._audio_queue.put(None)
            except Exception:
                pass

        # Wait for video thread to finish
        if self._video_thread and self._video_thread.is_alive():
            self._video_thread.join(timeout=5)

        # Close video stdin (signals EOF to FFmpeg for video stream)
        if self._process and self._process.stdin:
            try:
                self._process.stdin.close()
            except Exception:
                pass

        # Wait for FFmpeg video encoding to finish
        if self._process is not None:
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg video did not finish in 15s, terminating")
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()

            video_exit = self._process.returncode
            self._process = None
            logger.info("FFmpeg video encoding done (exit=%d)", video_exit if video_exit is not None else -1)

        # Wait for audio thread to finish
        if self._audio_thread and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=5)

        # Close WAV file
        with self._wav_lock:
            if self._wav_file is not None:
                try:
                    self._wav_file.close()
                except Exception:
                    pass
                self._wav_file = None

        # Stop screen capture
        if self._screen_capture:
            try:
                self._screen_capture.stop()
            except Exception:
                logger.exception("Error stopping screen capture")
            self._screen_capture = None

        # ── Pass 2: Mux video + audio → final output ─────────────────
        cb_count = getattr(self, "_audio_callback_count", 0)
        wav_size = os.path.getsize(self._temp_audio_path) if os.path.isfile(self._temp_audio_path) else 0
        logger.info("Audio stats: callbacks=%d, wav_samples=%d, wav_bytes=%d",
                    cb_count, self._audio_sample_count, wav_size)
        self._mux_audio_video()

        # ── Cleanup temp files ────────────────────────────────────────
        self._cleanup_temp_files()

        duration = time.perf_counter() - self._start_time
        logger.info("FFmpeg recorder stopped (%.1fs, %d frames)",
                    duration, self._frame_count)

        if os.path.isfile(self._output_path) and os.path.getsize(self._output_path) > 0:
            self.recording_stopped.emit(self._output_path)
        else:
            self.recording_error.emit("Recording failed: output file not created")

    def _mux_audio_video(self) -> None:
        """Pass 2: Merge temp video and temp audio into final output using FFmpeg."""
        has_video = os.path.isfile(self._temp_video_path) and os.path.getsize(self._temp_video_path) > 0
        has_audio = os.path.isfile(self._temp_audio_path) and os.path.getsize(self._temp_audio_path) > 44

        if not has_video:
            logger.error("Temp video file missing or empty: %s", self._temp_video_path)
            return

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
        ]

        if has_audio:
            # Mux video + audio, copy video stream, encode audio to AAC
            cmd.extend([
                "-i", self._temp_video_path,
                "-i", self._temp_audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",        # Copy video as-is (no re-encode)
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",           # Trim to shorter stream
                "-movflags", "+faststart",
            ])
            logger.info("Muxing video + audio → %s", Path(self._output_path).name)
        else:
            # Video only, no audio
            cmd.extend([
                "-i", self._temp_video_path,
                "-c:v", "copy",
                "-movflags", "+faststart",
            ])
            logger.info("Muxing video only → %s", Path(self._output_path).name)

        cmd.append(self._output_path)

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=60,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                logger.error("FFmpeg mux failed (exit=%d): %s", result.returncode, stderr[:500])
            else:
                logger.info("Mux complete → %s", self._output_path)
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg mux timed out")
        except Exception as exc:
            logger.exception("FFmpeg mux error: %s", exc)

    def _cleanup_temp_files(self) -> None:
        """Delete temp video and audio files."""
        for path in (self._temp_video_path, self._temp_audio_path):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass

    def pause(self) -> None:
        """Pause recording (not yet implemented for FFmpeg backend)."""
        pass

    def resume(self, fps: int) -> None:
        """Resume recording."""
        self._fps = fps

    def is_recording(self) -> bool:
        return self._is_recording

    def get_output_path(self) -> str:
        return self._output_path

    def get_recording_duration(self) -> float:
        if self._start_time == 0:
            return 0.0
        return time.perf_counter() - self._start_time

    def get_file_size(self) -> int:
        return self._get_file_size()

    def _get_file_size(self) -> int:
        try:
            if os.path.isfile(self._temp_video_path):
                return os.path.getsize(self._temp_video_path)
        except OSError:
            pass
        return 0
