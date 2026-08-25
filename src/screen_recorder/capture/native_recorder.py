"""Python ctypes wrapper for the native C++ recorder DLL.

This module provides a Python interface to the native C++ recording engine
(recorder.dll) which uses:
  - WASAPI loopback for system audio (direct COM, no PortAudio layer)
  - DXGI Desktop Duplication for screen capture (GPU)
  - FFmpeg subprocess for encoding/muxing

The C++ engine runs entirely in native threads — NO GIL interference.
This eliminates audio tick-tick spikes caused by Python's thread scheduling.

Usage:
    from screen_recorder.capture.native_recorder import NativeRecorder

    recorder = NativeRecorder()
    recorder.start("output.mp4", fps=30, monitor_idx=0)
    ...
    recorder.stop()
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger


def _find_dll() -> str:
    """Locate recorder.dll."""
    candidates = []

    if getattr(sys, "frozen", False):
        # PyInstaller EXE
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        candidates.append(base / "bin" / "recorder.dll")
        candidates.append(base / "recorder.dll")
    else:
        # Development — prefer Release, fall back to Debug
        project_root = Path(__file__).parent.parent.parent.parent
        candidates.append(project_root / "bin" / "Release" / "recorder.dll")
        candidates.append(project_root / "bin" / "Debug" / "recorder.dll")
        candidates.append(project_root / "bin" / "recorder.dll")

    for c in candidates:
        if c.exists():
            return str(c)

    raise FileNotFoundError(
        f"recorder.dll not found. Build it with: cd native && powershell -File build.ps1"
    )


# C function pointer types for callbacks
PREVIEW_CALLBACK = ctypes.CFUNCTYPE(
    None,                     # void return
    ctypes.c_char_p,          # const uint8_t* rgb_data
    ctypes.c_int,             # int width
    ctypes.c_int,             # int height
)

AUDIO_LEVEL_CALLBACK = ctypes.CFUNCTYPE(
    None,                     # void return
    ctypes.c_float,           # float left
    ctypes.c_float,           # float right
)


class NativeRecorder(QObject):
    """Python wrapper for the native C++ recorder DLL.

    Signals:
        recording_started(str): Output path when recording starts
        recording_stopped(str): Output path when recording stops
        recording_error(str): Error message on failure
        progress_updated(dict): Periodic progress
        preview_frame(np.ndarray): RGB frame for GUI preview (disabled by default)
        audio_level_updated(float, float): Left/right RMS levels (~20 Hz)
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    progress_updated = pyqtSignal(dict)
    preview_frame = pyqtSignal(np.ndarray)
    audio_level_updated = pyqtSignal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dll_path = _find_dll()
        self._dll = ctypes.CDLL(self._dll_path)

        # Set up function signatures
        self._dll.recorder_start.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self._dll.recorder_start.restype = ctypes.c_int

        self._dll.recorder_stop.argtypes = []
        self._dll.recorder_stop.restype = ctypes.c_int

        self._dll.recorder_is_recording.argtypes = []
        self._dll.recorder_is_recording.restype = ctypes.c_int

        self._dll.recorder_last_error.argtypes = []
        self._dll.recorder_last_error.restype = ctypes.c_char_p

        self._dll.recorder_get_width.argtypes = []
        self._dll.recorder_get_width.restype = ctypes.c_int

        self._dll.recorder_get_height.argtypes = []
        self._dll.recorder_get_height.restype = ctypes.c_int

        self._dll.recorder_get_sample_rate.argtypes = []
        self._dll.recorder_get_sample_rate.restype = ctypes.c_int

        self._dll.recorder_get_channels.argtypes = []
        self._dll.recorder_get_channels.restype = ctypes.c_int

        self._dll.recorder_set_preview_callback.argtypes = [PREVIEW_CALLBACK]
        self._dll.recorder_set_preview_callback.restype = None

        self._dll.recorder_set_audio_level_callback.argtypes = [AUDIO_LEVEL_CALLBACK]
        self._dll.recorder_set_audio_level_callback.restype = None

        self._dll.recorder_set_region.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self._dll.recorder_set_region.restype = None

        self._dll.recorder_set_audio_mode.argtypes = [ctypes.c_int, ctypes.c_int]
        self._dll.recorder_set_audio_mode.restype = None

        # Keep references to callbacks to prevent GC
        self._preview_cb_ref: Optional[PREVIEW_CALLBACK] = None
        self._audio_level_cb_ref: Optional[AUDIO_LEVEL_CALLBACK] = None
        self._is_recording = False
        self._output_path = ""
        self._start_time = 0.0
        self._fps = 30
        self._video_bitrate = 0
        self._capture_config = None
        self._recording_config = None

        # Disable preview callback (reduces CPU burden — recording is perfect)
        # Use a no-op callback instead of None — ctypes rejects None for CFUNCTYPE
        self._preview_noop = PREVIEW_CALLBACK(lambda *args: None)
        self._dll.recorder_set_preview_callback(self._preview_noop)

        # Set up audio level callback for GUI meter
        self._setup_audio_level_callback()

        logger.info("NativeRecorder initialized (DLL: %s)", Path(self._dll_path).name)

    def _setup_audio_level_callback(self) -> None:
        """Set up the audio level callback for GUI meter bars."""
        def on_audio_level(left: float, right: float) -> None:
            """Called from C++ audio thread (~20 Hz) with RMS levels."""
            try:
                self.audio_level_updated.emit(float(left), float(right))
            except Exception as e:
                logger.debug("Audio level callback error: %s", e)

        self._audio_level_cb_ref = AUDIO_LEVEL_CALLBACK(on_audio_level)
        self._dll.recorder_set_audio_level_callback(self._audio_level_cb_ref)

    def configure(self, capture_config, recording_config, fps: int) -> None:
        """Configure recording parameters (stored for compatibility)."""
        self._fps = fps
        self._capture_config = capture_config
        self._recording_config = recording_config

    def set_audio_mode(self, enable_microphone: bool, enable_system_audio: bool) -> None:
        """Set audio capture mode — call before start_recording()."""
        self._dll.recorder_set_audio_mode(
            ctypes.c_int(1 if enable_microphone else 0),
            ctypes.c_int(1 if enable_system_audio else 0),
        )
        logger.info("Native recorder audio mode: mic=%s sys=%s",
                    enable_microphone, enable_system_audio)

    def set_audio_capture(self, audio_capture) -> None:
        """No-op — native C++ engine handles audio internally via WASAPI."""
        pass

    def write_audio_data(self, audio_data: np.ndarray) -> None:
        """No-op — native C++ engine captures audio directly via WASAPI."""
        pass

    def start_recording(self) -> None:
        """Start native recording."""
        if self._is_recording:
            logger.warning("Native recorder already running")
            return

        # Generate output path
        import time
        from datetime import datetime
        output_dir = Path.home() / "Documents" / "Screen Recordings"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = str(output_dir / f"recording_{timestamp}.mp4")

        # Use configured output path if available
        if self._recording_config and self._recording_config.output_path:
            output_path = str(self._recording_config.output_path)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        fps = getattr(self, "_fps", 30)
        bitrate = getattr(self, "_video_bitrate", 0)

        # Determine monitor index and region from capture config
        monitor_idx = 0
        region = None
        capture_type = "screen"
        if self._capture_config is not None:
            monitor_idx = getattr(self._capture_config, "monitor_index", 0) or 0
            region = getattr(self._capture_config, "region", None)
            ct = getattr(self._capture_config, "capture_type", None)
            if ct is not None:
                capture_type = getattr(ct, "name", "screen").lower()

        # Set region on the C++ engine before starting (convert logical→physical px)
        if capture_type == "region" and region is not None:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QPoint
            dpr = 1.0
            screen = QApplication.screenAt(QPoint(region.x() + region.width() // 2,
                                                    region.y() + region.height() // 2))
            if screen is not None:
                dpr = screen.devicePixelRatio()
            else:
                primary = QApplication.primaryScreen()
                if primary is not None:
                    dpr = primary.devicePixelRatio()
            rx = round(region.x() * dpr)
            ry = round(region.y() * dpr)
            rw = round(region.width() * dpr)
            rh = round(region.height() * dpr)
            self._dll.recorder_set_region(rx, ry, rw, rh)
            logger.info("Native recorder: region (%d,%d %dx%d) dpr=%.2f", rx, ry, rw, rh, dpr)
        else:
            self._dll.recorder_set_region(0, 0, 0, 0)  # reset to fullscreen
            logger.info("Native recorder: fullscreen (monitor %d)", monitor_idx)

        logger.info("Starting native recorder → %s (%dfps, bitrate=%d)", output_path, fps, bitrate)

        ret = self._dll.recorder_start(
            output_path.encode("utf-8"),
            ctypes.c_int(fps),
            ctypes.c_int(monitor_idx),
            ctypes.c_int(bitrate),
        )

        if ret != 0:
            err = self._dll.recorder_last_error()
            err_msg = err.decode("utf-8") if err else f"Unknown error (code={ret})"
            logger.error("Native recorder start failed: %s", err_msg)
            self.recording_error.emit(f"Recording failed: {err_msg}")
            return

        self._is_recording = True
        self._output_path = output_path
        self._start_time = time.perf_counter()
        self.recording_started.emit(output_path)

        # Get actual capture dimensions
        w = self._dll.recorder_get_width()
        h = self._dll.recorder_get_height()
        sr = self._dll.recorder_get_sample_rate()
        ch = self._dll.recorder_get_channels()
        logger.info("Native recorder: %dx%d @ %dfps, audio %dHz %dch",
                    w, h, fps, sr, ch)

    def stop_recording(self) -> None:
        """Stop native recording and mux audio+video."""
        if not self._is_recording:
            return

        logger.info("Stopping native recorder...")
        ret = self._dll.recorder_stop()

        self._is_recording = False

        if ret != 0:
            err = self._dll.recorder_last_error()
            err_msg = err.decode("utf-8") if err else f"Unknown error (code={ret})"
            logger.error("Native recorder stop failed: %s", err_msg)
            self.recording_error.emit(f"Stop failed: {err_msg}")
            return

        import os
        if os.path.isfile(self._output_path) and os.path.getsize(self._output_path) > 0:
            logger.info("Recording saved → %s", self._output_path)
            self.recording_stopped.emit(self._output_path)
        else:
            self.recording_error.emit("Output file not created")

    def pause(self) -> None:
        """Pause not yet implemented for native recorder."""
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
        import time
        return time.perf_counter() - self._start_time

    def get_file_size(self) -> int:
        """Return current recording file size in bytes.

        During recording, the C++ engine writes to temp files
        (``<base>_tmp_video.mp4`` and ``<base>_tmp_audio.wav``) which are
        muxed into the final output on stop.  We sum these temp files to
        show a live size estimate while recording.
        """
        try:
            if os.path.isfile(self._output_path):
                return os.path.getsize(self._output_path)
            # Recording in progress — sum temp files
            base, _ = os.path.splitext(self._output_path)
            temp_video = base + "_tmp_video.mp4"
            temp_audio = base + "_tmp_audio.wav"
            total = 0
            if os.path.isfile(temp_video):
                total += os.path.getsize(temp_video)
            if os.path.isfile(temp_audio):
                total += os.path.getsize(temp_audio)
            return total
        except OSError:
            pass
        return 0
