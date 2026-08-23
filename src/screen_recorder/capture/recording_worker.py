"""Recording worker module — runs the capture+encode pipeline on a dedicated thread.

Moving screen capture and video/audio encoding off the main Qt thread prevents
event-loop starvation at high frame rates (e.g. 60 fps).  Without this, H.264
encoding + mss screen grabs can take longer than the timer interval, blocking
the event loop so that cross-thread audio signals are never delivered —
producing silent recordings at 60 fps.

The worker runs a plain Python thread (``threading.Thread``) with its own
capture loop.  Audio data is passed to the encoding thread via a thread-safe
``queue.Queue``.  Commands (stop, pause, resume) are sent via a command queue.
PyAV encode/mux calls all happen on this single encoding thread for thread
safety.  Status updates (preview frames, progress, errors) are emitted as Qt
signals — Qt automatically queues cross-thread signal deliveries.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..utils.logger import logger

# Internal sentinel commands sent via the command queue
_CMD_STOP = "STOP"
_CMD_PAUSE = "PAUSE"
_CMD_RESUME = "RESUME"


class RecordingWorker(QObject):
    """Runs the video capture + audio/video encoding loop on a dedicated thread.

    Usage (from main thread)::

        worker = RecordingWorker()
        worker.configure(capture_config, recording_config, fps)
        worker.start_recording()   # starts a daemon thread
        ...
        worker.stop_recording()    # signals thread to stop and waits

    Signals (emitted to main thread for UI updates):
        recording_started(str): Output path when recording begins.
        recording_stopped(str): Output path when recording ends.
        recording_error(str): Error message on failure.
        preview_frame(np.ndarray): Throttled video frame for UI preview.
        progress_updated(dict): Periodic progress stats.
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

        # Thread and synchronisation
        self._thread: threading.Thread | None = None
        self._cmd_queue: queue.Queue = queue.Queue()
        self._audio_queue: queue.Queue = queue.Queue(maxsize=200)  # ~4 seconds at 50fps chunks

        # State (written only by encoding thread; read from main thread safely via signals)
        self._is_running = False
        self._is_paused = False

    def configure(self, capture_config, recording_config, fps: int) -> None:
        """Store configuration (call from main thread before starting)."""
        self._capture_config = capture_config
        self._recording_config = recording_config
        self._fps = fps

    # ------------------------------------------------------------------
    # Public API (callable from main thread)
    # ------------------------------------------------------------------

    def start_recording(self) -> None:
        """Start the recording thread.

        Returns immediately; the thread runs in the background.
        Connect signals before calling this to avoid missing events.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("RecordingWorker already running")
            return
        self._is_running = False
        self._is_paused = False
        self._thread = threading.Thread(target=self._run, name="RecordingWorker", daemon=True)
        self._thread.start()

    def stop_recording(self) -> None:
        """Signal the recording thread to stop and wait for it to finish."""
        if self._thread is None or not self._thread.is_alive():
            return
        self._cmd_queue.put(_CMD_STOP)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            logger.warning("Recording thread did not stop within 10s")
        else:
            self._thread = None
        logger.info("RecordingWorker stopped")

    def pause(self) -> None:
        """Pause recording (thread keeps running but drops frames/audio)."""
        self._cmd_queue.put(_CMD_PAUSE)

    def resume(self, fps: int) -> None:
        """Resume recording after a pause, optionally updating fps."""
        self._fps = fps
        self._cmd_queue.put((_CMD_RESUME, fps))

    @pyqtSlot(np.ndarray)
    def write_audio_data(self, audio_data: np.ndarray) -> None:
        """Enqueue audio data for the encoding thread.

        Connected to ``AudioCapture.audio_data``.  This slot is called
        from PortAudio callback threads (via Qt queued connection if the
        signal crosses threads, or directly otherwise).  We put the data
        into a bounded queue to avoid unbounded memory growth if the
        encoding thread falls behind.
        """
        try:
            self._audio_queue.put_nowait(audio_data)
        except queue.Full:
            # Drop oldest chunk if queue is overflowing
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait(audio_data)
            except queue.Full:
                pass

    # ------------------------------------------------------------------
    # Encoding thread (runs in self._thread)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main recording loop — runs on the encoding thread."""
        from ..capture.screen_capture import ScreenCapture, CaptureType
        from ..encoding.output_writer import OutputWriter

        screen_capture = None
        output_writer = None
        frame_interval = 1.0 / self._fps
        preview_interval = 3  # emit preview every N frames
        frame_count = 0
        progress_interval = 0.5  # seconds between progress signals
        last_progress_time = 0.0

        try:
            # 1. Create screen capture ON THIS THREAD (mss must be used from the same thread)
            # No parent — these QObjects live only on this encoding thread.
            screen_capture = ScreenCapture()
            screen_capture.configure(self._capture_config)
            screen_capture.start()

            # 2. Determine capture dimensions from mss monitor info
            sct = screen_capture._sct
            if sct is not None:
                monitors = sct.monitors
                if self._capture_config.capture_type == CaptureType.REGION and self._capture_config.region is not None:
                    region = self._capture_config.region
                    dpr = 1.0
                    try:
                        from PyQt6.QtWidgets import QApplication
                        from PyQt6.QtCore import QPoint
                        app = QApplication.instance()
                        if app is not None:
                            centre = region.center()
                            scr = app.screenAt(QPoint(centre.x(), centre.y()))
                            if scr is not None:
                                dpr = scr.devicePixelRatio()
                    except Exception:
                        pass
                    actual_w = round(region.width() * dpr)
                    actual_h = round(region.height() * dpr)
                else:
                    idx = self._capture_config.monitor_index + 1
                    if 0 < idx < len(monitors):
                        mon = monitors[idx]
                        actual_w = mon["width"]
                        actual_h = mon["height"]
                    else:
                        actual_w, actual_h = 1920, 1080

                actual_w = actual_w if actual_w % 2 == 0 else actual_w - 1
                actual_h = actual_h if actual_h % 2 == 0 else actual_h - 1
                logger.info("RecordingWorker: capture dimensions %dx%d @ %dfps", actual_w, actual_h, self._fps)
                self._recording_config.video_config.width = actual_w
                self._recording_config.video_config.height = actual_h
            else:
                logger.warning("mss not initialised, using config dimensions")

            # 3. Create output writer ON THIS THREAD
            output_writer = OutputWriter()
            output_writer.configure(self._recording_config)

            # Connect writer signals (emitted from this thread → queued to main thread)
            output_writer.recording_started.connect(self.recording_started)
            output_writer.recording_error.connect(self.recording_error)
            output_writer.progress_updated.connect(self.progress_updated)

            output_writer.start()
            self._is_running = True
            self._is_paused = False

            logger.info(
                "RecordingWorker thread started: tid=%s @ %dfps",
                threading.get_ident(), self._fps,
            )

            # 4. Main capture loop
            next_frame_time = time.perf_counter()
            last_progress_time = time.perf_counter()

            while self._is_running:
                # Process pending commands (non-blocking)
                self._drain_commands()
                if not self._is_running:
                    break

                now = time.perf_counter()

                # Process queued audio data
                self._process_audio_queue(output_writer)

                if not self._is_paused:
                    # Capture and encode a video frame
                    frame = screen_capture.capture_frame()
                    if frame is not None:
                        output_writer.write_video_frame(frame, 0)
                        frame_count += 1

                        # Throttled preview
                        if frame_count % preview_interval == 0:
                            self.preview_frame.emit(frame)

                # Periodic progress updates
                if now - last_progress_time >= progress_interval:
                    last_progress_time = now
                    try:
                        duration = output_writer.get_recording_duration()
                        file_size = output_writer.get_file_size()
                        self.progress_updated.emit({
                            "duration": duration,
                            "file_size": file_size,
                            "frames": frame_count,
                            "fps": self._fps,
                        })
                    except Exception:
                        pass

                # Calculate sleep time to maintain target fps
                next_frame_time += frame_interval
                sleep_time = next_frame_time - time.perf_counter()
                if sleep_time > 0:
                    # Use short sleep with command-check responsiveness
                    cmd_timeout = min(sleep_time, 0.020)
                    try:
                        cmd = self._cmd_queue.get(timeout=cmd_timeout)
                        self._handle_command(cmd)
                    except queue.Empty:
                        pass
                    # Sleep remaining time
                    remaining = next_frame_time - time.perf_counter()
                    if remaining > 0:
                        time.sleep(min(remaining, 0.005))
                else:
                    # We're behind — skip sleep but yield briefly
                    if sleep_time < -frame_interval * 5:
                        # More than 5 frames behind, reset timing to avoid spiral
                        next_frame_time = time.perf_counter()
                    time.sleep(0.001)

            # Final drain of audio queue
            self._process_audio_queue(output_writer)

        except Exception as exc:
            logger.exception("RecordingWorker thread error")
            self.recording_error.emit(f"Recording error: {exc}")
        finally:
            self._is_running = False

            # Stop output writer (flush encoders)
            output_path = self._recording_config.output_path if self._recording_config else None
            if output_writer is not None:
                try:
                    output_writer.stop()
                except Exception:
                    logger.exception("Error stopping output writer")

            # Stop screen capture
            if screen_capture is not None:
                try:
                    screen_capture.stop()
                except Exception:
                    logger.exception("Error stopping screen capture")

            # Drain any remaining commands
            while not self._cmd_queue.empty():
                try:
                    self._cmd_queue.get_nowait()
                except queue.Empty:
                    break

            if output_path:
                self.recording_stopped.emit(output_path)
                logger.info("RecordingWorker thread finished → %s", output_path)

    def _drain_commands(self) -> None:
        """Process all pending commands without blocking."""
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_command(cmd)

    def _handle_command(self, cmd) -> None:
        """Handle a single command from the command queue."""
        if cmd == _CMD_STOP:
            self._is_running = False
        elif cmd == _CMD_PAUSE:
            if self._is_running and not self._is_paused:
                self._is_paused = True
                logger.debug("RecordingWorker paused")
        elif isinstance(cmd, tuple) and cmd[0] == _CMD_RESUME:
            if self._is_running and self._is_paused:
                self._is_paused = False
                self._fps = cmd[1]
                logger.debug("RecordingWorker resumed @ %dfps", self._fps)

    def _process_audio_queue(self, output_writer) -> None:
        """Drain all available audio chunks and write them to the output."""
        drained = 0
        while drained < 50:  # limit per tick to avoid blocking video capture
            try:
                audio_data = self._audio_queue.get_nowait()
            except queue.Empty:
                break
            if not self._is_paused and output_writer is not None:
                try:
                    output_writer.write_audio_data(audio_data, 0.0)
                except Exception:
                    logger.exception("Error writing audio data")
            drained += 1
