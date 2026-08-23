"""Screen capture module — captures screen frames using the mss library.

Provides the :class:`ScreenCapture` class which wraps *mss* to grab
individual frames or specific regions of the display, converting the
raw BGRA output to RGB numpy arrays suitable for further processing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import mss
import mss.base
import numpy as np
from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from ..utils.logger import logger


# ── Capture type enum ────────────────────────────────────────────────────────


class CaptureType(Enum):
    """Type of screen capture to perform."""

    SCREEN = auto()
    WINDOW = auto()
    REGION = auto()


# ── Capture configuration ────────────────────────────────────────────────────


@dataclass
class CaptureConfig:
    """Configuration for screen capture sessions.

    Attributes:
        capture_type: The kind of capture (full screen, window, region).
        monitor_index: Which physical monitor to capture (0-based).
        region: Optional rectangular region for region-based capture.
        fps: Target frames per second for continuous capture.
    """

    capture_type: CaptureType = CaptureType.SCREEN
    monitor_index: int = 0
    region: QRect | None = None
    fps: int = 30


# ── Screen capture class ─────────────────────────────────────────────────────


class ScreenCapture(QObject):
    """Captures screen frames using the *mss* library.

    The mss instance is created once in :meth:`start` and reused for
    every frame to avoid the expensive per-frame initialisation that
    occurs when using ``with mss.mss() as sct:`` on every call.  At 60 fps
    this overhead was blocking the Qt event loop long enough to starve
    audio signals, causing silent recordings.

    Signals:
        frame_captured: Emitted with an RGB numpy array when a frame is
            successfully captured.
        capture_error: Emitted with an error message string when a capture
            operation fails.
    """

    frame_captured = pyqtSignal(np.ndarray)
    capture_error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = CaptureConfig()
        self._sct: mss.base.MSSBase | None = None

    # ── DPI-aware coordinate conversion ───────────────────────────────────

    @staticmethod
    def _logical_to_physical_region(region: QRect) -> dict:
        """Convert a QRect in logical (scaled) pixels to physical pixels for mss."""
        centre = region.center()
        screen = QApplication.screenAt(QPoint(centre.x(), centre.y()))

        if screen is not None:
            dpr = screen.devicePixelRatio()
        else:
            primary = QApplication.primaryScreen()
            dpr = primary.devicePixelRatio() if primary else 1.0

        monitor = {
            "left": round(region.x() * dpr),
            "top": round(region.y() * dpr),
            "width": round(region.width() * dpr),
            "height": round(region.height() * dpr),
        }

        logger.debug(
            "Logical region: x=%d, y=%d, w=%d, h=%d",
            region.x(), region.y(), region.width(), region.height(),
        )
        logger.debug(
            "Physical region (dpr=%.2f): left=%d, top=%d, width=%d, height=%d",
            dpr, monitor["left"], monitor["top"], monitor["width"], monitor["height"],
        )

        return monitor

    # ── Configuration ─────────────────────────────────────────────────────

    def configure(self, config: CaptureConfig) -> None:
        """Set the capture configuration."""
        logger.info("Configuring screen capture: %s", config)
        self._config = config

    # ── Monitor enumeration ──────────────────────────────────────────────

    def get_monitors(self) -> list[dict]:
        """Return a list of monitor information dictionaries from *mss*."""
        try:
            # Use the persistent instance if available; otherwise create a temporary one
            if self._sct is not None:
                monitors = self._sct.monitors
            else:
                with mss.mss() as sct:
                    monitors = sct.monitors
            logger.debug("Detected %d monitor entries", len(monitors))
            return list(monitors)
        except Exception as exc:
            msg = f"Failed to enumerate monitors: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            return []

    # ── Frame capture ────────────────────────────────────────────────────

    def capture_frame(self) -> np.ndarray | None:
        """Capture a single frame from the configured source.

        Uses the persistent mss instance (created in :meth:`start`) for
        low-latency captures at high frame rates.

        Returns:
            The frame as an RGB numpy array (H×W×3, uint8), or ``None``
            on failure.
        """
        try:
            # Lazy-initialise sct if capture_frame is called before start()
            if self._sct is None:
                logger.warning("capture_frame() called before start(); creating mss instance")
                self._sct = mss.mss()

            sct = self._sct

            if self._config.capture_type == CaptureType.REGION and self._config.region is not None:
                region = self._config.region
                monitor = self._logical_to_physical_region(region)
            else:
                idx = self._config.monitor_index + 1
                monitors = sct.monitors
                if idx >= len(monitors):
                    msg = f"Monitor index {self._config.monitor_index} out of range"
                    logger.error(msg)
                    self.capture_error.emit(msg)
                    return None
                monitor = monitors[idx]

            shot = sct.grab(monitor)
            # mss returns BGRA; convert to RGB: drop alpha, reverse BGR→RGB
            frame = np.array(shot, dtype=np.uint8)[:, :, :3]
            frame = frame[:, :, ::-1].copy()

            self.frame_captured.emit(frame)
            return frame

        except Exception as exc:
            msg = f"Frame capture failed: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            return None

    def capture_region(self, region: QRect) -> np.ndarray | None:
        """Capture a specific screen region."""
        try:
            if self._sct is None:
                self._sct = mss.mss()
            sct = self._sct
            monitor = self._logical_to_physical_region(region)
            shot = sct.grab(monitor)
            frame = np.array(shot, dtype=np.uint8)[:, :, :3]
            frame = frame[:, :, ::-1].copy()

            self.frame_captured.emit(frame)
            return frame

        except Exception as exc:
            msg = f"Region capture failed: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            return None

    # ── Thumbnail helper ─────────────────────────────────────────────────

    def get_monitor_thumbnail(
        self,
        monitor_index: int = 0,
        size: tuple[int, int] = (320, 180),
    ) -> QImage:
        """Capture a monitor and return a scaled thumbnail :class:`QImage`."""
        try:
            if self._sct is not None:
                sct = self._sct
                idx = monitor_index + 1
                monitors = sct.monitors
                if idx >= len(monitors):
                    logger.error("Monitor index %d out of range", monitor_index)
                    return QImage()
                shot = sct.grab(monitors[idx])
                frame = np.array(shot, dtype=np.uint8)
            else:
                with mss.mss() as sct:
                    idx = monitor_index + 1
                    monitors = sct.monitors
                    if idx >= len(monitors):
                        logger.error("Monitor index %d out of range", monitor_index)
                        return QImage()
                    shot = sct.grab(monitors[idx])
                    frame = np.array(shot, dtype=np.uint8)

            h, w = frame.shape[:2]
            qimg = QImage(
                frame.data,
                w,
                h,
                frame.strides[0],
                QImage.Format.Format_RGB32,
            ).copy()

            return qimg.scaled(
                size[0],
                size[1],
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        except Exception as exc:
            logger.error("Thumbnail capture failed: %s", exc)
            return QImage()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Initialise the persistent mss instance for low-overhead frame capture.

        Must be called before starting continuous recording.  Creating the
        mss instance once (instead of per-frame) is critical for achieving
        high frame rates (e.g. 60 fps) without blocking the Qt event loop.
        """
        try:
            if self._sct is None:
                self._sct = mss.mss()
            count = len(self._sct.monitors) - 1  # exclude virtual screen
            logger.info("Screen capture started — %d monitor(s) detected", count)
        except Exception as exc:
            msg = f"Failed to initialize screen capture: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            self._sct = None

    def stop(self) -> None:
        """Release the persistent mss instance."""
        if self._sct is not None:
            sct = self._sct
            self._sct = None
            try:
                sct.close()
            except AttributeError:
                # mss on Windows uses thread-local storage; if close() is
                # called after the creating thread has begun tearing down,
                # the _handles attribute may not exist. This is harmless.
                logger.debug("mss close() skipped (thread-local handles already released)")
            except Exception:
                logger.exception("Error closing mss instance")
        logger.info("Screen capture stopped")
