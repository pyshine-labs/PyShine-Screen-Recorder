"""Screen capture module — captures screen frames using the mss library.

Provides the :class:`ScreenCapture` class which wraps *mss* to grab
individual frames or specific regions of the display, converting the
raw BGRA output to RGB numpy arrays suitable for further processing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import mss
import numpy as np
from PyQt6.QtCore import QObject, QPoint, QRect, pyqtSignal
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
        """Convert a QRect in logical (scaled) pixels to physical pixels for mss.

        On High-DPI displays the region selector reports coordinates in logical
        pixels, but *mss* operates on physical pixels.  This method scales the
        region by the device pixel ratio of the screen that contains the
        region's centre so the captured area matches the user's selection.

        Args:
            region: A :class:`QRect` in logical/screen coordinates.

        Returns:
            A dict with keys ``left``, ``top``, ``width``, ``height`` in
            physical pixel coordinates suitable for *mss*.
        """
        # Determine which screen the region centre falls on
        centre = region.center()
        screen = QApplication.screenAt(QPoint(centre.x(), centre.y()))

        if screen is not None:
            dpr = screen.devicePixelRatio()
        else:
            # Fallback: try the primary screen
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
        """Set the capture configuration.

        Args:
            config: A :class:`CaptureConfig` instance describing the
                desired capture behaviour.
        """
        logger.info("Configuring screen capture: %s", config)
        self._config = config

    # ── Monitor enumeration ──────────────────────────────────────────────

    def get_monitors(self) -> list[dict]:
        """Return a list of monitor information dictionaries from *mss*.

        The first entry is the virtual screen encompassing all monitors;
        subsequent entries describe individual physical monitors.

        Returns:
            A list of dicts with keys ``left``, ``top``, ``width``,
            ``height`` for each detected monitor.
        """
        try:
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

        The frame is returned as an RGB numpy array (H×W×3, uint8).
        Returns ``None`` if the capture fails.
        """
        try:
            with mss.mss() as sct:
                if self._config.capture_type == CaptureType.REGION and self._config.region is not None:
                    region = self._config.region
                    monitor = self._logical_to_physical_region(region)
                else:
                    # monitor_index + 1 because mss.monitors[0] is the virtual screen
                    idx = self._config.monitor_index + 1
                    monitors = sct.monitors
                    if idx >= len(monitors):
                        msg = f"Monitor index {self._config.monitor_index} out of range"
                        logger.error(msg)
                        self.capture_error.emit(msg)
                        return None
                    monitor = monitors[idx]

                shot = sct.grab(monitor)
                # mss returns BGRA; convert to RGB by dropping the alpha channel
                frame = np.array(shot, dtype=np.uint8)[:, :, :3]
                # Convert BGR to RGB
                frame = frame[:, :, ::-1].copy()

                self.frame_captured.emit(frame)
                return frame

        except Exception as exc:
            msg = f"Frame capture failed: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)
            return None

    def capture_region(self, region: QRect) -> np.ndarray | None:
        """Capture a specific screen region.

        Args:
            region: The rectangular region to capture, in screen
                coordinates.

        Returns:
            An RGB numpy array (H×W×3, uint8), or ``None`` on error.
        """
        try:
            with mss.mss() as sct:
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
        """Capture a monitor and return a scaled thumbnail :class:`QImage`.

        Args:
            monitor_index: 0-based index of the physical monitor.
            size: Target ``(width, height)`` for the thumbnail.

        Returns:
            A scaled :class:`QImage` in RGB32 format. If capture fails,
            returns a null image.
        """
        try:
            with mss.mss() as sct:
                idx = monitor_index + 1
                monitors = sct.monitors
                if idx >= len(monitors):
                    logger.error("Monitor index %d out of range", monitor_index)
                    return QImage()

                shot = sct.grab(monitors[idx])
                frame = np.array(shot, dtype=np.uint8)

                # Convert BGRA to QImage (Format_RGB32 expects 0xAARRGGBB)
                h, w = frame.shape[:2]
                qimg = QImage(
                    frame.data,
                    w,
                    h,
                    frame.strides[0],
                    QImage.Format.Format_RGB32,
                ).copy()  # deep copy so data stays valid

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
        """Initialize and validate the mss connection.

        This should be called before starting continuous capture to
        ensure that *mss* can access the display.
        """
        try:
            with mss.mss() as sct:
                count = len(sct.monitors) - 1  # exclude virtual screen
                logger.info("Screen capture started — %d monitor(s) detected", count)
        except Exception as exc:
            msg = f"Failed to initialize screen capture: {exc}"
            logger.error(msg)
            self.capture_error.emit(msg)

    def stop(self) -> None:
        """Clean up mss resources.

        Since we use the ``mss.mss()`` context manager for each capture,
        this is primarily a placeholder for any future persistent
        resource management.
        """
        logger.info("Screen capture stopped")