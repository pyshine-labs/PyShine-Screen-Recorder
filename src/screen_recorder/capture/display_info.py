"""Display information module — enumerates monitors and display geometry.

Provides :class:`MonitorInfo` for describing individual physical monitors
and :class:`DisplayInfo` with static helpers to query the display
topology via *mss*.
"""

from __future__ import annotations

from dataclasses import dataclass

import mss
from PyQt6.QtCore import QRect

from ..utils.logger import logger


# ── Monitor info dataclass ───────────────────────────────────────────────────


@dataclass
class MonitorInfo:
    """Describes a single physical monitor.

    Attributes:
        index: 0-based index of the monitor within the display topology.
        name: A human-readable label (e.g. ``"Monitor 1"``).
        x: Left edge of the monitor in virtual-screen coordinates.
        y: Top edge of the monitor in virtual-screen coordinates.
        width: Horizontal resolution in pixels.
        height: Vertical resolution in pixels.
        is_primary: Whether this is the primary display.
        scale_factor: DPI scale factor (defaults to 1.0).
    """

    index: int
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool
    scale_factor: float = 1.0


# ── Display info helper class ────────────────────────────────────────────────


class DisplayInfo:
    """Static helpers for querying display/monitor information.

    All methods are static — no instance or :class:`QObject` is needed.
    """

    @staticmethod
    def get_monitors() -> list[MonitorInfo]:
        """Enumerate all physical monitors using *mss*.

        The first entry in ``mss.monitors`` represents the virtual screen
        (the bounding rectangle of all monitors combined) and is **not**
        included in the returned list.  Only subsequent entries describing
        individual physical monitors are returned.

        Returns:
            A list of :class:`MonitorInfo` instances, one per physical
            monitor.  Returns an empty list on error.
        """
        try:
            with mss.mss() as sct:
                all_monitors = sct.monitors
                result: list[MonitorInfo] = []

                # mss.monitors[0] is the virtual screen; [1:] are physical monitors
                for i, mon in enumerate(all_monitors[1:]):
                    # Determine if this is the primary monitor.
                    # The primary monitor typically has its top-left at (0, 0).
                    is_primary = mon.get("left", 0) == 0 and mon.get("top", 0) == 0

                    info = MonitorInfo(
                        index=i,
                        name=f"Monitor {i + 1}",
                        x=mon.get("left", 0),
                        y=mon.get("top", 0),
                        width=mon.get("width", 0),
                        height=mon.get("height", 0),
                        is_primary=is_primary,
                    )
                    result.append(info)
                    logger.debug("Detected monitor %d: %s", i, info)

                logger.info("Enumerated %d physical monitor(s)", len(result))
                return result

        except Exception as exc:
            logger.error("Failed to enumerate monitors: %s", exc)
            return []

    @staticmethod
    def get_primary_monitor() -> MonitorInfo | None:
        """Return information about the primary monitor.

        Returns:
            A :class:`MonitorInfo` for the primary display, or ``None``
            if no monitors are detected or on error.
        """
        monitors = DisplayInfo.get_monitors()
        for mon in monitors:
            if mon.is_primary:
                return mon

        # Fallback: return the first monitor if none is marked primary
        if monitors:
            logger.warning("No primary monitor detected; defaulting to first")
            return monitors[0]

        return None

    @staticmethod
    def get_virtual_screen() -> dict:
        """Return the virtual screen bounds (all monitors combined).

        This is the bounding rectangle that encompasses every physical
        monitor, as reported by ``mss.monitors[0]``.

        Returns:
            A dict with keys ``left``, ``top``, ``width``, ``height``
            describing the virtual screen.  Returns an empty dict on
            error.
        """
        try:
            with mss.mss() as sct:
                virtual = sct.monitors[0]
                logger.debug(
                    "Virtual screen: left=%d, top=%d, %dx%d",
                    virtual.get("left", 0),
                    virtual.get("top", 0),
                    virtual.get("width", 0),
                    virtual.get("height", 0),
                )
                return dict(virtual)

        except Exception as exc:
            logger.error("Failed to get virtual screen bounds: %s", exc)
            return {}

    @staticmethod
    def get_monitor_rect(index: int) -> QRect:
        """Return a :class:`QRect` for the monitor at the given index.

        Args:
            index: 0-based index of the physical monitor.

        Returns:
            A :class:`QRect` describing the monitor's position and size
            in virtual-screen coordinates.  Returns a null rect on
            error or if the index is out of range.
        """
        try:
            with mss.mss() as sct:
                all_monitors = sct.monitors
                # +1 to skip the virtual-screen entry at [0]
                phys_index = index + 1
                if phys_index >= len(all_monitors):
                    logger.error("Monitor index %d out of range", index)
                    return QRect()

                mon = all_monitors[phys_index]
                rect = QRect(
                    mon.get("left", 0),
                    mon.get("top", 0),
                    mon.get("width", 0),
                    mon.get("height", 0),
                )
                logger.debug("Monitor %d rect: %s", index, rect)
                return rect

        except Exception as exc:
            logger.error("Failed to get monitor rect for index %d: %s", index, exc)
            return QRect()