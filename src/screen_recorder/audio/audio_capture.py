"""Audio capture module for the Screen Recorder application.

Captures audio from microphone and/or system audio (WASAPI loopback)
using *sounddevice* for microphone input and *pyaudiowpatch* for loopback
capture on Windows.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger

# pyaudiowpatch is optional — provides WASAPI loopback capture on Windows.
try:
    import pyaudiowpatch as pyaudio_wp  # type: ignore[import-untyped]

    _HAS_PYAUDIOWPATCH = True
except ImportError:
    pyaudio_wp = None  # type: ignore[assignment]
    _HAS_PYAUDIOWPATCH = False


@dataclass
class AudioCaptureConfig:
    """Configuration for :class:`AudioCapture`."""

    sample_rate: int = 48000
    channels: int = 2
    dtype: str = "float32"
    buffer_size: int = 1024
    microphone_device: int | None = None  # device index; None = default
    system_audio_device: int | None = None  # device index for loopback
    enable_microphone: bool = True
    enable_system_audio: bool = False


class AudioCapture(QObject):
    """Capture audio from microphone and/or system audio loopback.

    Signals:
        audio_data(np.ndarray): Raw audio data chunk (float32).
        level_updated(float, float): Left and right channel RMS levels (0.0–1.0).
        capture_error(str): Error message.
        capture_started(): Emitted when capture begins.
        capture_stopped(): Emitted when capture ends.
    """

    audio_data = pyqtSignal(np.ndarray)
    level_updated = pyqtSignal(float, float)
    capture_error = pyqtSignal(str)
    capture_started = pyqtSignal()
    capture_stopped = pyqtSignal()

    def __init__(self, parent=None) -> None:  # noqa: D107
        super().__init__(parent)
        self._config = AudioCaptureConfig()
        self._mic_stream: sd.InputStream | None = None
        self._loopback_stream: object | None = None  # pyaudiowpatch stream
        self._pa_instance: object | None = None  # pyaudiowpatch.PyAudio
        self._is_capturing = False
        self._is_paused = False
        self._actual_sample_rate: int = 0
        self._loopback_channels: int = self._config.channels
        self._lock = threading.Lock()
        # Direct audio data callback for low-latency delivery to recorder.
        # Called from the audio capture thread immediately when data arrives.
        # Signature: callback(audio_data: np.ndarray) -> None
        self._data_callback: object | None = None

    def set_data_callback(self, callback) -> None:
        """Set a direct callback for audio data (bypasses Qt signal queue).

        This is called from the audio capture thread immediately when audio
        data is available, with no Qt event loop latency. Use this for
        recording pipelines; the ``audio_data`` Qt signal remains for UI.
        """
        self._data_callback = callback

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, config: AudioCaptureConfig) -> None:
        """Set capture configuration.

        Must be called **before** :meth:`start`.  If a capture is already
        running the configuration change is ignored and a warning is logged.
        """
        with self._lock:
            if self._is_capturing:
                logger.warning("Cannot reconfigure while capture is active")
                return
            self._config = config

    # ------------------------------------------------------------------
    # Start / Stop / Pause / Resume
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start audio capture stream(s).

        Creates a *sounddevice* ``InputStream`` for the microphone (if
        enabled) and a *pyaudiowpatch* WASAPI loopback stream for system
        audio (if enabled and available).
        """
        with self._lock:
            if self._is_capturing:
                logger.warning("Capture is already running")
                return

            self._is_paused = False

            # ── Microphone stream ──────────────────────────────────────
            if self._config.enable_microphone:
                self._start_mic_stream()

            # ── System audio (loopback) stream ────────────────────────
            if self._config.enable_system_audio:
                self._start_loopback_stream()

            if self._mic_stream is not None or self._loopback_stream is not None:
                self._is_capturing = True
                self.capture_started.emit()
                logger.info("Audio capture started")
            else:
                logger.warning("No audio streams were started")

    def stop(self) -> None:
        """Stop all audio streams and release resources."""
        with self._lock:
            self._is_capturing = False
            self._is_paused = False

        # Stop microphone stream (outside lock — sounddevice handles its own
        # internal synchronisation).
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                logger.exception("Error stopping microphone stream")
            self._mic_stream = None

        # Stop loopback stream
        if self._loopback_stream is not None:
            try:
                self._loopback_stream.stop_stream()
                self._loopback_stream.close()
            except Exception:
                logger.exception("Error stopping loopback stream")
            self._loopback_stream = None

        if self._pa_instance is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                logger.exception("Error terminating PyAudio instance")
            self._pa_instance = None

        self.capture_stopped.emit()
        logger.info("Audio capture stopped")

    def pause(self) -> None:
        """Pause audio capture — streams remain open but data is discarded."""
        with self._lock:
            if not self._is_capturing:
                return
            self._is_paused = True
        logger.debug("Audio capture paused")

    def resume(self) -> None:
        """Resume audio capture after a :meth:`pause`."""
        with self._lock:
            if not self._is_capturing:
                return
            self._is_paused = False
        logger.debug("Audio capture resumed")

    def is_capturing(self) -> bool:
        """Return whether capture is currently active."""
        return self._is_capturing

    def get_actual_sample_rate(self) -> int:
        """Return the actual sample rate of the running capture stream."""
        return self._actual_sample_rate if self._actual_sample_rate > 0 else self._config.sample_rate

    def get_actual_channels(self) -> int:
        """Return the actual channel count of the running audio stream.

        Checks the microphone stream first, then the loopback stream.
        This may differ from the configured channel count when the device
        doesn't support the requested number of channels.
        """
        if self._mic_stream is not None:
            return self._mic_stream.channels
        if self._loopback_stream is not None:
            return self._loopback_channels
        return self._config.channels

    # ------------------------------------------------------------------
    # Audio callback
    # ------------------------------------------------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Process incoming audio data from *sounddevice*.

        Calculates per-channel RMS levels and emits :attr:`audio_data` and
        :attr:`level_updated` signals.
        """
        if status:
            logger.warning("Audio callback status: %s", status)

        with self._lock:
            if self._is_paused:
                return

        # Calculate levels
        left_rms = self._calculate_rms(indata[:, 0]) if indata.shape[1] > 0 else 0.0
        right_rms = (
            self._calculate_rms(indata[:, 1]) if indata.shape[1] > 1 else left_rms
        )

        self.level_updated.emit(float(left_rms), float(right_rms))
        data_copy = indata.copy()
        self.audio_data.emit(data_copy)
        # Direct callback for low-latency recording path (no Qt queue)
        cb = self._data_callback
        if cb is not None:
            try:
                cb(data_copy)
            except Exception:
                logger.exception("Error in direct audio data callback")

    def _loopback_callback(
        self,
        in_data: object,
        frame_count: int,
        time_info: object,
        status: object,
    ) -> object:
        """Process incoming audio data from *pyaudiowpatch* loopback stream.

        The loopback stream delivers int16 PCM; we convert it to float32
        in the range [-1.0, 1.0] to stay consistent with the microphone
        path and the downstream encoder.
        """
        with self._lock:
            if self._is_paused:
                return (None, pyaudio_wp.paContinue) if _HAS_PYAUDIOWPATCH else None

        try:
            # WASAPI loopback delivers paInt16 samples
            audio_int16 = np.frombuffer(in_data, dtype=np.int16)
            channels = self._loopback_channels
            # Always reshape to 2D (frames, channels) for consistency with sounddevice
            audio_int16 = audio_int16.reshape(-1, channels)
            # Convert int16 [-32768, 32767] → float32 [-1.0, 1.0]
            audio_array = audio_int16.astype(np.float32) / 32768.0

            left_rms = (
                self._calculate_rms(audio_array[:, 0])
                if audio_array.size > 0
                else 0.0
            )
            right_rms = (
                self._calculate_rms(audio_array[:, 1])
                if channels > 1 and audio_array.shape[0] > 0
                else left_rms
            )

            self.level_updated.emit(float(left_rms), float(right_rms))
            data_copy = audio_array.copy()
            self.audio_data.emit(data_copy)
            # Direct callback for low-latency recording path (no Qt queue)
            cb = self._data_callback
            if cb is not None:
                try:
                    cb(data_copy)
                except Exception:
                    logger.exception("Error in direct audio data callback")
        except Exception:
            logger.exception("Error in loopback audio callback")

        if _HAS_PYAUDIOWPATCH:
            return (None, pyaudio_wp.paContinue)
        return None

    # ------------------------------------------------------------------
    # RMS calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_rms(data: np.ndarray) -> float:
        """Calculate the RMS level of *data* and normalise to 0.0–1.0.

        The input is assumed to be float32 audio in the range [-1.0, 1.0].
        """
        if data.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, rms))

    # ------------------------------------------------------------------
    # Private stream helpers
    # ------------------------------------------------------------------

    def _start_mic_stream(self) -> None:
        """Create and start a *sounddevice* ``InputStream`` for the microphone."""
        try:
            device = self._config.microphone_device  # None → default
            # Query device capabilities and clamp channels to device maximum
            if device is None:
                device_info = sd.query_devices(kind='input')
            else:
                device_info = sd.query_devices(device)
            max_channels = device_info.get('max_input_channels', 2)
            channels = min(self._config.channels, max_channels)
            if channels < 1:
                channels = 1  # At least 1 channel required

            self._mic_stream = sd.InputStream(
                device=device,
                channels=channels,
                samplerate=self._config.sample_rate,
                dtype=self._config.dtype,
                blocksize=self._config.buffer_size,
                callback=self._audio_callback,
            )
            self._mic_stream.start()
            self._actual_sample_rate = self._config.sample_rate
            logger.info(
                "Microphone stream started (device=%s, rate=%d, channels=%d)",
                device,
                self._config.sample_rate,
                channels,
            )
        except Exception:
            logger.exception("Failed to start microphone stream")
            self.capture_error.emit("Failed to start microphone stream")
            self._mic_stream = None

    def _start_loopback_stream(self) -> None:
        """Create and start a WASAPI loopback stream via *pyaudiowpatch*."""
        if not _HAS_PYAUDIOWPATCH:
            logger.warning(
                "pyaudiowpatch is not installed — system audio loopback "
                "capture is unavailable. Install it with: pip install pyaudiowpatch"
            )
            self.capture_error.emit(
                "System audio capture requires pyaudiowpatch (not installed)"
            )
            return

        try:
            self._pa_instance = pyaudio_wp.PyAudio()

            # Determine the loopback device index
            loopback_idx = self._config.system_audio_device

            if loopback_idx is None:
                # Robust device discovery following the pyaudiowpatch
                # official example: find the default WASAPI output device
                # then locate its loopback counterpart by name matching.
                loopback_dev_info = self._find_default_loopback_device()
                if loopback_dev_info is None:
                    logger.error(
                        "Could not find a WASAPI loopback device for system audio"
                    )
                    self.capture_error.emit(
                        "No WASAPI loopback device found for system audio"
                    )
                    self._pa_instance.terminate()
                    self._pa_instance = None
                    return
                loopback_idx = loopback_dev_info["index"]
                loopback_dev = loopback_dev_info
                logger.info(
                    "Using default WASAPI loopback device: %s (index %d)",
                    loopback_dev.get("name", ""),
                    loopback_idx,
                )
            else:
                loopback_dev = self._pa_instance.get_device_info_by_index(loopback_idx)

            loopback_channels = min(
                loopback_dev.get("maxInputChannels", 2), self._config.channels
            )
            self._loopback_channels = loopback_channels
            loopback_rate = int(loopback_dev.get("defaultSampleRate", self._config.sample_rate))

            # WASAPI loopback devices deliver paInt16 PCM reliably;
            # paFloat32 is not consistently supported across devices.
            # We convert to float32 in the callback.
            loopback_frames_per_buffer = min(self._config.buffer_size, 512)

            self._loopback_stream = self._pa_instance.open(
                input_device_index=loopback_idx,
                format=pyaudio_wp.paInt16,
                channels=loopback_channels,
                rate=loopback_rate,
                frames_per_buffer=loopback_frames_per_buffer,
                input=True,
                stream_callback=self._loopback_callback,
                start=False,
            )
            self._loopback_stream.start_stream()
            self._actual_sample_rate = loopback_rate
            logger.info(
                "Loopback stream started (device=%s, index=%d, channels=%d, rate=%d, format=int16)",
                loopback_dev.get("name", ""),
                loopback_idx,
                loopback_channels,
                loopback_rate,
            )
        except Exception:
            logger.exception("Failed to start loopback stream")
            self.capture_error.emit("Failed to start system audio loopback stream")
            # Clean up partial resources
            if self._loopback_stream is not None:
                try:
                    self._loopback_stream.stop_stream()
                    self._loopback_stream.close()
                except Exception:
                    pass
                self._loopback_stream = None
            if self._pa_instance is not None:
                try:
                    self._pa_instance.terminate()
                except Exception:
                    pass
                self._pa_instance = None

    def _find_default_loopback_device(self) -> dict | None:
        """Find the WASAPI loopback device corresponding to the default speakers.

        Uses the pyaudiowpatch-recommended approach: get the WASAPI host API,
        look up the default output device, then scan loopback devices for one
        whose name contains the default speaker name.  Falls back to
        ``get_default_wasapi_loopback()`` if name matching fails.

        Returns:
            A device info dict, or ``None`` if no suitable device is found.
        """
        if self._pa_instance is None or not _HAS_PYAUDIOWPATCH:
            return None

        # Strategy 1: get_default_wasapi_loopback() (simplest, works in most cases)
        try:
            dev = self._pa_instance.get_default_wasapi_loopback()
            if dev is not None:
                return dev
        except Exception:
            logger.debug("get_default_wasapi_loopback() failed, trying name-matching")

        # Strategy 2: match default WASAPI speakers to loopback by name
        try:
            wasapi_info = self._pa_instance.get_host_api_info_by_type(pyaudio_wp.paWASAPI)
            default_speakers = self._pa_instance.get_device_info_by_index(
                wasapi_info["defaultOutputDevice"]
            )
            if not default_speakers.get("isLoopbackDevice", False):
                for loopback in self._pa_instance.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        return loopback
        except Exception:
            logger.debug("Name-matching loopback discovery failed")

        # Strategy 3: return the first available loopback device
        try:
            for loopback in self._pa_instance.get_loopback_device_info_generator():
                return loopback
        except Exception:
            pass

        return None