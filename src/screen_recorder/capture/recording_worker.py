"""Recording worker module — event-driven capture+encode on a dedicated thread.

Robust A/V sync design (strict CFR):
- Uses ``threading.Event.wait()`` for all waiting (interruptible, no time.sleep, no busy-loops)
- Single flat loop — exactly one video frame encoded per iteration, no nested catch-up loops
- Frame pacer uses wall-clock (time.perf_counter()) to TARGET the right capture rate
- OUTPUT PTS is strict CFR: video PTS = frame_index (0,1,2,...), audio PTS = cumulative samples
- Wall-clock timestamps are used ONLY for initial audio/video alignment offset, NOT for
  continuous PTS calculation — this prevents drift when encoder temporarily lags
- The first video frame sets the shared epoch t0 → audio initial offset calculated from gap
- When encoder falls behind, Event.wait() returns immediately and frames are encoded
  back-to-back naturally (one per iteration), smoothly catching up without burst loops
- dxcam background grabber thread provides non-blocking frame capture (~5ms)
- Real-time encoder presets (ultrafast/zerolatency for x264, fastest for hardware)
- Automatic downscaling to 1080p for software encoder to maintain real-time performance
- Audio chunks are timestamped at enqueue time for initial alignment only
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..utils.logger import logger

_CMD_STOP = "STOP"
_CMD_PAUSE = "PAUSE"
_CMD_RESUME = "RESUME"

# ── Windows high-resolution timer ──────────────────────────────────────
_winmm = None
if sys.platform == "win32":
    try:
        _winmm = ctypes.WinDLL("winmm", use_last_error=True)
    except Exception:
        _winmm = None


def _set_high_res_timer() -> None:
    """Request 1ms timer resolution on Windows."""
    if _winmm is not None:
        try:
            _winmm.timeBeginPeriod(1)
        except Exception:
            pass


def _end_high_res_timer() -> None:
    """Release the 1ms timer request."""
    if _winmm is not None:
        try:
            _winmm.timeEndPeriod(1)
        except Exception:
            pass


def _precise_wait(deadline: float, stop_event: threading.Event) -> bool:
    """Wait until ``deadline`` (perf_counter) with ~0.5ms precision.

    Uses Event.wait() for the coarse wait (stopping 1.5ms early to avoid
    overshoot on Windows), then a tight spin loop for the final portion.
    Returns True if stop_event was signaled, False if deadline arrived.
    """
    SPIN_THRESHOLD_S = 0.0015
    while True:
        now = time.perf_counter()
        remaining = deadline - now
        if remaining <= 0:
            return stop_event.is_set()
        if stop_event.is_set():
            return True
        if remaining > SPIN_THRESHOLD_S:
            stop_event.wait(timeout=remaining - SPIN_THRESHOLD_S)


class RecordingWorker(QObject):
    """Event-driven recording worker on a dedicated thread.

    Signals (emitted to main thread for UI updates):
        recording_started(str), recording_stopped(str), recording_error(str),
        preview_frame(np.ndarray), progress_updated(dict)
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    preview_frame = pyqtSignal(np.ndarray)
    progress_updated = pyqtSignal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._capture_config = None
        self._recording_config = None
        self._fps: int = 30

        self._thread: threading.Thread | None = None
        self._cmd_queue: queue.Queue = queue.Queue()
        # Queue stores (timestamp, audio_data) tuples for precise A/V sync
        self._audio_queue: queue.Queue = queue.Queue(maxsize=400)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        self._is_running = False
        self._just_resumed = False

    def configure(self, capture_config, recording_config, fps: int) -> None:
        self._capture_config = capture_config
        self._recording_config = recording_config
        self._fps = fps

    # ------------------------------------------------------------------
    # Public API (main thread)
    # ------------------------------------------------------------------

    def start_recording(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("RecordingWorker already running")
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._run, name="RecordingWorker", daemon=True)
        self._thread.start()

    def stop_recording(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._cmd_queue.put(_CMD_STOP)
        self._stop_event.set()
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            logger.warning("Recording thread did not stop within 15s")
        else:
            self._thread = None
        logger.info("RecordingWorker stopped")

    def pause(self) -> None:
        self._cmd_queue.put(_CMD_PAUSE)

    def resume(self, fps: int) -> None:
        self._fps = fps
        self._cmd_queue.put((_CMD_RESUME, fps))

    @pyqtSlot(np.ndarray)
    def write_audio_data(self, audio_data: np.ndarray) -> None:
        """Enqueue audio data with timestamp from audio callback thread."""
        ts = time.perf_counter()
        try:
            self._audio_queue.put_nowait((ts, audio_data))
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait((ts, audio_data))
            except queue.Full:
                pass

    # ------------------------------------------------------------------
    # Encoding thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        from ..capture.screen_capture import ScreenCapture
        from ..encoding.output_writer import OutputWriter
        from ..encoding.video_encoder import VideoEncoder, VideoEncoderConfig

        screen_capture = None
        output_writer = None
        frame_count = 0
        last_progress_time = 0.0

        frame_interval = 1.0 / self._fps
        _SW_MAX_WIDTH = 1920

        try:
            _set_high_res_timer()

            # ── Initialize capture ─────────────────────────────────────
            screen_capture = ScreenCapture()
            screen_capture.configure(self._capture_config)
            screen_capture.start()

            native_w, native_h = screen_capture.capture_size
            native_w = native_w if native_w % 2 == 0 else native_w - 1
            native_h = native_h if native_h % 2 == 0 else native_h - 1

            # ── Detect encoder for downscale decision ──────────────────
            tmp_enc = VideoEncoder()
            tmp_enc.configure(VideoEncoderConfig(width=native_w, height=native_h, fps=self._fps))
            codec_name = tmp_enc.get_codec_name(self._recording_config.video_config.encoder)
            is_software = (codec_name == "libx264")

            if is_software and native_w > _SW_MAX_WIDTH:
                scale = _SW_MAX_WIDTH / native_w
                encode_w = _SW_MAX_WIDTH
                encode_h = int(native_h * scale)
                encode_h = encode_h if encode_h % 2 == 0 else encode_h - 1
                logger.info("Software encoder: pre-downscaling %dx%d → %dx%d",
                            native_w, native_h, encode_w, encode_h)
                screen_capture.set_target_size(encode_w, encode_h)
            else:
                encode_w, encode_h = native_w, native_h

            cap_w, cap_h = screen_capture.capture_size
            cap_w = cap_w if cap_w % 2 == 0 else cap_w - 1
            cap_h = cap_h if cap_h % 2 == 0 else cap_h - 1
            self._recording_config.video_config.width = cap_w
            self._recording_config.video_config.height = cap_h
            self._recording_config.video_config.fps = self._fps

            # ── Initialize output writer ──────────────────────────────
            output_writer = OutputWriter()
            output_writer.configure(self._recording_config)
            output_writer.recording_started.connect(self.recording_started)
            output_writer.recording_error.connect(self.recording_error)
            output_writer.progress_updated.connect(self.progress_updated)
            output_writer.start()

            self._is_running = True
            backend = screen_capture.backend_name
            logger.info("Recording thread: tid=%s, %dx%d @ %dfps, backend=%s, codec=%s",
                        threading.get_ident(), cap_w, cap_h, self._fps, backend, codec_name)

            # ── Event-driven frame pacer ──────────────────────────────
            # Design principles for perfect A/V sync (strict CFR):
            # 1. t0 = wall-clock time of the FIRST video frame capture (pacing reference).
            # 2. Audio queued before t0 is DISCARDED, guaranteeing sync start.
            # 3. OUTPUT video PTS = frame_index (strict 0,1,2,...) → perfect CFR.
            # 4. OUTPUT audio PTS = cumulative samples (strict linear advance).
            # 5. Wall-clock timestamps on audio chunks set initial offset ONLY.
            # 6. Target time for frame N = t0 + N * frame_interval (pacing target).
            # 7. If encoder falls behind, frames are encoded back-to-back to catch up,
            #    but PTS stays linear — no drift, no skipping in the output file.
            # 8. Catch-up safety: if >30 frames behind, snap t0 forward to realign pacer.
            # 9. Single flat loop — exactly one frame per iteration.
            # 10. Audio is drained IMMEDIATELY before frame capture, with timestamps
            #     used for initial alignment on the first chunk.

            t0: float | None = None
            _PAUSE_WAIT = 0.100
            CATCHUP_LIMIT_FRAMES = 30

            while not self._stop_event.is_set():
                self._drain_commands(output_writer)

                if self._pause_event.is_set():
                    self._drain_audio_discard()
                    self._stop_event.wait(timeout=_PAUSE_WAIT)
                    continue

                # ── First frame: capture immediately, set epoch t0 ──
                if t0 is None:
                    self._drain_audio_discard()
                    frame = screen_capture.capture_frame()
                    if frame is not None:
                        t0 = time.perf_counter()
                        last_progress_time = t0
                        # Pass t0 as capture timestamp → output_writer sets epoch, PTS=0
                        output_writer.write_video_frame(frame, pts_timestamp=t0)
                        frame_count = 1
                    continue

                # ── Resume from pause: realign timeline ─────────────
                if self._just_resumed:
                    now = time.perf_counter()
                    t0 = now - frame_count * frame_interval
                    last_progress_time = now
                    self._just_resumed = False

                # ── Calculate target time for this frame ────────────
                target_time = t0 + frame_count * frame_interval
                now = time.perf_counter()

                # ── Catch-up safety: if too far behind, snap forward
                if target_time < now - CATCHUP_LIMIT_FRAMES * frame_interval:
                    missed = int((now - target_time) / frame_interval) - CATCHUP_LIMIT_FRAMES
                    t0 += missed * frame_interval
                    target_time = t0 + frame_count * frame_interval
                    logger.warning("Pacer: %d frames behind, snapping t0 forward by %.3fs",
                                   missed + CATCHUP_LIMIT_FRAMES, missed * frame_interval)

                # ── Wait until target time (high-precision) ─────────
                if target_time > now:
                    stopped = _precise_wait(target_time, self._stop_event)
                    if stopped:
                        break
                    self._drain_commands(output_writer)
                    if self._stop_event.is_set():
                        break
                    if self._pause_event.is_set():
                        continue

                # ── Drain audio that accumulated before this frame ─
                self._drain_audio(output_writer, max_chunks=100)

                # ── Capture + encode exactly ONE frame ──────────────
                frame = screen_capture.capture_frame()
                if frame is not None:
                    capture_ts = time.perf_counter()
                    output_writer.write_video_frame(frame, pts_timestamp=capture_ts)
                    frame_count += 1

                # ── Progress (≈1 Hz) ────────────────────────────────
                now = time.perf_counter()
                if now - last_progress_time >= 1.0:
                    last_progress_time = now
                    try:
                        self.progress_updated.emit({
                            "duration": output_writer.get_recording_duration(),
                            "file_size": output_writer.get_file_size(),
                            "frames": frame_count,
                            "fps": round(frame_count / max(0.001, now - t0), 1),
                        })
                    except Exception:
                        pass

            # ── Final audio drain (flush everything, ignore stop) ──
            self._drain_audio(output_writer, max_chunks=500, ignore_stop=True)

        except Exception as exc:
            logger.exception("RecordingWorker thread error")
            self.recording_error.emit(f"Recording error: {exc}")
        finally:
            _end_high_res_timer()
            self._is_running = False
            output_path = self._recording_config.output_path if self._recording_config else None
            if output_writer is not None:
                try:
                    output_writer.stop()
                except Exception:
                    logger.exception("Error stopping output writer")
            if screen_capture is not None:
                try:
                    screen_capture.stop()
                except Exception:
                    logger.exception("Error stopping screen capture")
            while not self._cmd_queue.empty():
                try:
                    self._cmd_queue.get_nowait()
                except queue.Empty:
                    break
            if output_path:
                self.recording_stopped.emit(str(output_path))
                logger.info("RecordingWorker finished → %s", output_path)

    # ------------------------------------------------------------------
    # Command helpers (called from worker thread)
    # ------------------------------------------------------------------

    def _drain_commands(self, output_writer) -> None:
        """Non-blocking command drain — handles STOP immediately."""
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd == _CMD_STOP:
                self._stop_event.set()
            elif cmd == _CMD_PAUSE:
                self._pause_event.set()
                if output_writer is not None:
                    try:
                        output_writer.pause()
                    except Exception:
                        pass
            elif isinstance(cmd, tuple) and cmd[0] == _CMD_RESUME:
                self._pause_event.clear()
                self._fps = cmd[1]
                self._just_resumed = True
                if output_writer is not None:
                    try:
                        output_writer.resume()
                    except Exception:
                        pass

    def _drain_audio(self, output_writer, max_chunks: int = 50, ignore_stop: bool = False) -> None:
        """Drain up to max_chunks audio chunks and write them with timestamps."""
        drained = 0
        while drained < max_chunks and (ignore_stop or not self._stop_event.is_set()):
            try:
                ts, audio_data = self._audio_queue.get_nowait()
            except queue.Empty:
                break
            if output_writer is not None:
                try:
                    output_writer.write_audio_data(audio_data, pts_timestamp=ts)
                except Exception:
                    logger.exception("Error writing audio data")
            drained += 1

    def _drain_audio_discard(self) -> None:
        """Discard queued audio (during pause or before first frame)."""
        drained = 0
        while drained < 100:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
