"""Logging utility module for the Screen Recorder application.

Provides a pre-configured module-level logger and a ``setup_logger``
helper for creating additional named loggers with consistent
formatting and optional file output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logger(
    name: str = "screen_recorder",
    level: int = logging.DEBUG,
    log_file: Optional[str | Path] = None,
) -> logging.Logger:
    """Create and configure a logger with console and optional file output.

    Args:
        name: The logger name. Child loggers will inherit this name as a
            prefix (e.g. ``screen_recorder.capture``).
        level: The logging level. Defaults to ``logging.DEBUG``.
        log_file: Optional path to a file where log messages will also
            be written. If ``None``, only console output is configured.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    logger_instance = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls
    if logger_instance.handlers:
        return logger_instance

    logger_instance.setLevel(level)
    formatter = logging.Formatter(DEFAULT_FORMAT)

    # ── Console handler ─────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger_instance.addHandler(console_handler)

    # ── File handler (optional) ─────────────────────────────────────────
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger_instance.addHandler(file_handler)

    return logger_instance


# Module-level convenience logger — used throughout the application.
logger = setup_logger("screen_recorder")