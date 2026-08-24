"""High-performance screen capture using DXGI Desktop Duplication (GPU) with mss fallback.

Primary backend: **dxcam** — uses Windows DXGI Desktop Duplication API for
zero-copy GPU-direct screen capture, same technology used by OBS, Xbox Game Bar,
Discord, and ShadowPlay. Capable of 60+ fps at 4K with minimal CPU usage.

Fallback backend: **mss** — GDI-based capture used when dxcam is unavailable
(e.g. on Windows 7, or when no GPU is present).

Architecture:
- dxcam runs on its own background thread (handled internally by dxcam).
- We add a *grabber thread* that continuously drains frames from dxcam,
  processes (downscales) them, and stores the result in ``_last_frame``.
- :meth:`capture_frame` is therefore **non-blocking** — it immediately returns
  a copy of the latest cached frame without waiting for the next capture.
- This decouples capture rate from encode rate, preventing the encoder from
  stalling the pipeline.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from ..utils.logger import logger


class CaptureType(Enum):
    SCREEN = auto()
    WINDOW = auto()
    REGION = auto()


@dataclass
class CaptureConfig:
    capture_type: CaptureType = CaptureType.SCREEN
    monitor_index: int = 0
    region: Optional[QRect] = None
    fps: int = 30


class ScreenCapture(QObject):
    """High-performance screen capture with GPU acceleration.

    Uses dxcam (DXGI Desktop Duplication) for GPU-direct capture when available.
    Falls back to mss (GDI) if dxcam cannot be initialized.

    A dedicated grabber thread continuously pulls frames from dxcam so that
    :meth:`capture_frame` never blocks — it returns the most recent frame
    instantly, even if called faster than the capture rate.
    """

    frame_captured = pyqtSignal(np.ndarray)
    capture_error = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = CaptureConfig()
        self._backend: str = "none"

        self._camera = None
        self._sct = None

        self._capture_width: int = 0
        self._capture_height: int = 0

        # Target output size for immediate downscale (None = native capture size)
        self._target_width: Optional[int] = None
        self._target_height: Optional[int] = None
        self._resize_step: int = 0  # integer downscale step (0 = no downscale)

        # Latest frame cache + lock for thread-safe access from grabber thread
        self._last_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

        # Grabber thread for dxcam
        self._grabber_thread: Optional[threading.Thread] = None
        self._grabber_running = False

    # ── Coordinate conversion ────────────────────────────────────────────

    @staticmethod
    def _logical_to_physical_region(region: QRect) -> Tuple[int, int, int, int]:
        centre = region.center()
        screen = QApplication.screenAt(QPoint(centre.x(), centre.y()))
        if screen is not None:
            dpr = screen.devicePixelRatio()
        else:
            primary = QApplication.primaryScreen()
            dpr = primary.devicePixelRatio() if primary else 1.0

        left = round(region.x() * dpr)
        top = round(region.y() * dpr)
        width = round(region.width() * dpr)
        height = round(region.height() * dpr)
        return (left, top, left + width, top + height)

    # ── Configuration ────────────────────────────────────────────────────

    def configure(self, config: CaptureConfig) -> None:
        logger.info("Configuring screen capture: %s", config)
        self._config = config

    def set_target_size(self, width: int, height: int) -> None:
        """Set an immediate downscale target for captured frames.

        Frames will be resized to (width, height) directly from the capture
        buffer, avoiding large intermediate copies. Can be called BEFORE or
        AFTER :meth:`start`; if called after, the resize step is recalculated
        based on current capture dimensions.
        """
        if width > 0 and height > 0:
            self._target_width = width if width % 2 == 0 else width - 1
            self._target_height = height if height % 2 == 0 else height - 1
        else:
            self._target_width = None
            self._target_height = None

        # Calculate integer downscale step if capture dimensions are known
        self._resize_step = 0
        if self._target_width and self._target_height and self._capture_width > 0 and self._capture_height > 0:
            scale_x = self._capture_width / self._target_width
            scale_y = self._capture_height / self._target_height
            if abs(scale_x - scale_y) < 0.01 and abs(scale_x - round(scale_x)) < 0.01:
                self._resize_step = int(round(scale_x))
                if self._resize_step >= 2:
                    logger.info(
                        "Fast-downscale: native %dx%d → %dx%d (step=%d)",
                        self._capture_width, self._capture_height,
                        self._target_width, self._target_height, self._resize_step,
                    )

    # ── Monitor enumeration ──────────────────────────────────────────────

    def get_monitors(self) -> list[dict]:
        try:
            import mss
            with mss.mss() as sct:
                return list(sct.monitors)
        except Exception as exc:
            logger.error("Failed to enumerate monitors: %s", exc)
            return []

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._last_frame = None
        if self._try_start_dxcam():
            return
        logger.info("DXGI capture unavailable; falling back to GDI (mss)")
        self._try_start_mss()

    def stop(self) -> None:
        # Stop grabber thread first
        self._stop_grabber()

        if self._backend == "dxcam" and self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                logger.debug("dxcam stop() exception (harmless)", exc_info=True)
            self._camera = None
            logger.info("DXGI screen capture stopped")

        if self._backend == "mss" and self._sct is not None:
            sct = self._sct
            self._sct = None
            try:
                sct.close()
            except AttributeError:
                logger.debug("mss close() skipped (thread-local handles already released)")
            except Exception:
                logger.exception("Error closing mss instance")
            logger.info("GDI screen capture stopped")

        self._backend = "none"
        with self._frame_lock:
            self._last_frame = None

    def _try_start_dxcam(self) -> bool:
        try:
            import dxcam
        except ImportError:
            logger.info("dxcam not installed; skipping DXGI backend")
            return False

        try:
            # Run dxcam at 2× encoding fps so the grabber thread always has fresh frames
            # without overloading the system. Higher rates caused black-frame issues
            # on some configurations.
            dxcam_fps = max(60, min(self._config.fps * 2, 120))
            region = None
            output_idx = self._config.monitor_index

            if self._config.capture_type == CaptureType.REGION and self._config.region is not None:
                l, t, r, b = self._logical_to_physical_region(self._config.region)
                l = l if l % 2 == 0 else l - 1
                t = t if t % 2 == 0 else t - 1
                r = r if r % 2 == 0 else r - (r % 2)
                b = b if b % 2 == 0 else b - (b % 2)
                region = (l, t, r, b)
                self._capture_width = r - l
                self._capture_height = b - t
                output_idx = 0

            camera_kwargs = dict(output_idx=output_idx, output_color="RGB")
            if region is not None:
                camera_kwargs["region"] = region

            self._camera = dxcam.create(**camera_kwargs)
            self._camera.start(target_fps=dxcam_fps, video_mode=True)

            # Wait for a valid startup frame (up to 1.5s) — Event.wait() is interruptible
            test_frame = None
            deadline = time.perf_counter() + 1.5
            _poll_ev = threading.Event()
            while time.perf_counter() < deadline and test_frame is None:
                test_frame = self._camera.get_latest_frame()
                if test_frame is None:
                    _poll_ev.wait(timeout=0.020)

            if test_frame is None:
                logger.warning("dxcam started but no frame received; falling back to mss")
                if self._camera is not None:
                    try:
                        self._camera.stop()
                    except Exception:
                        pass
                    self._camera = None
                return False

            self._capture_height, self._capture_width = test_frame.shape[:2]

            # Calculate resize step if target size is already set
            if self._target_width and self._target_height:
                scale_x = self._capture_width / self._target_width
                scale_y = self._capture_height / self._target_height
                if abs(scale_x - scale_y) < 0.01 and abs(scale_x - round(scale_x)) < 0.01:
                    self._resize_step = int(round(scale_x))

            # Process and store initial frame
            processed = self._process_frame(test_frame)
            with self._frame_lock:
                self._last_frame = processed

            self._backend = "dxcam"

            # Start background grabber thread
            self._grabber_running = True
            self._grabber_thread = threading.Thread(
                target=self._dxcam_grabber_loop,
                name="DXCamGrabber",
                daemon=True,
            )
            self._grabber_thread.start()

            out_w = self._target_width or self._capture_width
            out_h = self._target_height or self._capture_height
            logger.info(
                "DXGI screen capture started: %dx%d @ %dfps (capture=%dfps, backend=dxcam, GPU-accelerated)",
                out_w, out_h, self._config.fps, dxcam_fps,
            )
            return True

        except Exception as exc:
            logger.warning("dxcam initialization failed: %s — falling back to mss", exc)
            if self._camera is not None:
                try:
                    self._camera.stop()
                except Exception:
                    pass
                self._camera = None
            return False

    def _dxcam_grabber_loop(self) -> None:
        """Background thread that continuously drains frames from dxcam.

        Calls get_latest_frame() as fast as dxcam produces frames, processes
        each frame, and updates ``_last_frame``. This ensures capture_frame()
        never blocks waiting for a new dxcam frame.
        """
        logger.debug("DXCam grabber thread started")
        _err_wait = threading.Event()
        try:
            while self._grabber_running and self._camera is not None:
                try:
                    raw = self._camera.get_latest_frame()
                    if raw is not None:
                        processed = self._process_frame(raw)
                        with self._frame_lock:
                            self._last_frame = processed
                except Exception as exc:
                    logger.debug("Grabber frame error: %s", exc)
                    _err_wait.wait(timeout=0.010)
        except Exception:
            logger.exception("DXCam grabber thread error")
        logger.debug("DXCam grabber thread stopped")

    def _stop_grabber(self) -> None:
        """Stop the dxcam grabber thread if running."""
        self._grabber_running = False
        if self._grabber_thread is not None:
            self._grabber_thread.join(timeout=2.0)
            self._grabber_thread = None

    def _try_start_mss(self) -> None:
        try:
            import mss
            self._sct = mss.mss()
            self._backend = "mss"
            monitors = self._sct.monitors
            idx = self._config.monitor_index + 1
            if 0 < idx < len(monitors):
                mon = monitors[idx]
                self._capture_width = mon["width"]
                self._capture_height = mon["height"]
            else:
                self._capture_width, self._capture_height = 1920, 1080
            self._capture_width = self._capture_width if self._capture_width % 2 == 0 else self._capture_width - 1
            self._capture_height = self._capture_height if self._capture_height % 2 == 0 else self._capture_height - 1
            logger.info(
                "GDI screen capture started: %dx%d (backend=mss)",
                self._capture_width, self._capture_height,
            )
        except Exception as exc:
            msg = f"Failed to initialize any screen capture backend: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            self._backend = "none"

    def _process_frame(self, raw_frame: np.ndarray) -> np.ndarray:
        """Convert a raw captured frame to an owned, properly-sized output frame.

        1. If a target size with integer downscale step is set, stride-slice and
           make contiguous (reads from capture buffer → smaller owned copy).
        2. Otherwise, make a plain owned copy of the raw frame.
        """
        if self._resize_step >= 2:
            tw = self._target_width
            th = self._target_height
            # Stride-slice view → contiguous copy at target size
            return np.ascontiguousarray(
                raw_frame[::self._resize_step, ::self._resize_step, :][:th, :tw]
            )
        # Native size: just make an owned copy
        return raw_frame.copy()

    # ── Frame capture ────────────────────────────────────────────────────

    def capture_frame(self) -> Optional[np.ndarray]:
        """Return the latest available frame as an RGB numpy array (H×W×3, uint8).

        This method is **non-blocking** — it immediately returns a copy of the
        most recently captured frame. If no frame has been captured yet, returns
        None. If a target size was set via :meth:`set_target_size`, the frame
        is already downscaled.
        """
        try:
            if self._backend == "dxcam":
                with self._frame_lock:
                    frame = self._last_frame
                if frame is not None:
                    return frame
                return None

            elif self._backend == "mss" and self._sct is not None:
                sct = self._sct
                if self._config.capture_type == CaptureType.REGION and self._config.region is not None:
                    l, t, r, b = self._logical_to_physical_region(self._config.region)
                    monitor = {"left": l, "top": t, "width": r - l, "height": b - t}
                else:
                    idx = self._config.monitor_index + 1
                    monitors = sct.monitors
                    if idx >= len(monitors):
                        with self._frame_lock:
                            return self._last_frame.copy() if self._last_frame is not None else None
                    monitor = monitors[idx]

                shot = sct.grab(monitor)
                frame = np.array(shot, dtype=np.uint8)[:, :, :3]
                frame = frame[:, :, ::-1].copy()
                if self._resize_step >= 2 and self._target_width and self._target_height:
                    frame = np.ascontiguousarray(
                        frame[::self._resize_step, ::self._resize_step, :]
                        [:self._target_height, :self._target_width]
                    )
                with self._frame_lock:
                    self._last_frame = frame
                return frame

            with self._frame_lock:
                return self._last_frame.copy() if self._last_frame is not None else None

        except Exception as exc:
            msg = f"Frame capture failed: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            with self._frame_lock:
                return self._last_frame.copy() if self._last_frame is not None else None

    @property
    def capture_size(self) -> Tuple[int, int]:
        if self._target_width and self._target_height:
            return (self._target_width, self._target_height)
        return (self._capture_width, self._capture_height)

    @property
    def backend_name(self) -> str:
        return self._backend

    # ── Thumbnail helper ─────────────────────────────────────────────────

    def get_monitor_thumbnail(
        self,
        monitor_index: int = 0,
        size: Tuple[int, int] = (320, 180),
    ) -> QImage:
        try:
            import mss
            with mss.mss() as sct:
                idx = monitor_index + 1
                monitors = sct.monitors
                if idx >= len(monitors):
                    return QImage()
                shot = sct.grab(monitors[idx])
                frame = np.array(shot, dtype=np.uint8)

            h, w = frame.shape[:2]
            qimg = QImage(
                frame.data, w, h, frame.strides[0],
                QImage.Format.Format_RGB32,
            ).copy()
            return qimg.scaled(
                size[0], size[1],
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        except Exception as exc:
            logger.error("Thumbnail capture failed: %s", exc)
            return QImage()
