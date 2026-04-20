"""Global hotkey management for the Screen Recorder application.

Provides :class:`HotkeyManager` which registers system-wide keyboard
shortcuts (e.g. F9 to start/stop, F10 to pause/resume) using
``pynput.keyboard.GlobalHotKeys``.  If *pynput* is not available the
manager degrades gracefully — hotkeys simply won't fire.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import logger

# pynput is optional — the application must still start without it.
try:
    from pynput.keyboard import GlobalHotKeys
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


class HotkeyManager(QObject):
    """Manage global hotkeys for the screen recorder.

    Signals:
        start_triggered: Emitted when the start/stop toggle hotkey is pressed.
        stop_triggered:  Emitted when the stop hotkey is pressed.
        pause_triggered: Emitted when the pause/resume hotkey is pressed.

    The default bindings are:

    * ``<F9>``  → start / stop toggle
    * ``<F10>`` → pause / resume toggle
    """

    start_triggered = pyqtSignal()
    stop_triggered = pyqtSignal()
    pause_triggered = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # Default hotkey mappings: pynput key-spec → action name
        self._hotkeys: dict[str, str] = {
            "<f9>": "start_stop",
            "<f10>": "pause_resume",
        }

        self._listener: GlobalHotKeys | None = None

        if not _PYNPUT_AVAILABLE:
            logger.warning(
                "pynput is not installed — global hotkeys will be unavailable. "
                "Install it with: pip install pynput"
            )

    # ── Public API ──────────────────────────────────────────────────────────

    def register_hotkeys(self) -> None:
        """Start listening for global hotkey events.

        Creates a ``pynput.keyboard.GlobalHotKeys`` listener that maps
        each registered key combination to the corresponding handler.
        Calling this method while already listening is a no-op.
        """
        if not _PYNPUT_AVAILABLE:
            logger.warning("Cannot register hotkeys — pynput is not available")
            return

        if self._listener is not None:
            logger.debug("Hotkeys already registered — skipping")
            return

        # Build the pynput callback mapping
        callbacks: dict[str, callable] = {}
        for key_spec, action in self._hotkeys.items():
            handler = self._resolve_handler(action)
            if handler is not None:
                callbacks[key_spec] = handler

        if not callbacks:
            logger.warning("No hotkey bindings to register")
            return

        try:
            self._listener = GlobalHotKeys(callbacks)
            self._listener.start()
            logger.info("Global hotkeys registered: %s", self._hotkeys)
        except Exception as exc:
            logger.error("Failed to register global hotkeys: %s", exc)
            self._listener = None

    def unregister_all(self) -> None:
        """Stop listening for global hotkeys and clean up.

        Safe to call even if hotkeys were never registered.
        """
        if self._listener is not None:
            try:
                self._listener.stop()
                logger.info("Global hotkeys unregistered")
            except Exception as exc:
                logger.warning("Error while stopping hotkey listener: %s", exc)
            finally:
                self._listener = None

    def update_hotkey(self, action: str, key: str) -> None:
        """Change the key binding for a given action.

        Args:
            action: One of ``"start_stop"`` or ``"pause_resume"``.
            key: A pynput key specification (e.g. ``"<f9>"``, ``"<ctrl>+<alt>+r"``).

        If hotkeys are currently registered, they will be unregistered
        and re-registered with the updated mapping.
        """
        # Remove the old binding for this action (reverse lookup)
        old_key = None
        for k, v in self._hotkeys.items():
            if v == action:
                old_key = k
                break

        if old_key is not None:
            del self._hotkeys[old_key]

        self._hotkeys[key] = action
        logger.info("Hotkey updated: %s → %s (was %s)", key, action, old_key)

        # Re-register if currently listening
        if self._listener is not None:
            self.unregister_all()
            self.register_hotkeys()

    def get_hotkeys(self) -> dict[str, str]:
        """Return a copy of the current hotkey mappings.

        Returns:
            Dictionary mapping pynput key specifications to action names.
        """
        return dict(self._hotkeys)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _resolve_handler(self, action: str) -> callable | None:
        """Map an action name to the corresponding signal-emitting handler.

        Args:
            action: The action name (e.g. ``"start_stop"``).

        Returns:
            A callable that emits the appropriate signal, or ``None`` if
            the action is unknown.
        """
        handlers: dict[str, callable] = {
            "start_stop": self._on_start_stop,
            "pause_resume": self._on_pause_resume,
        }
        handler = handlers.get(action)
        if handler is None:
            logger.warning("Unknown hotkey action: %r", action)
        return handler

    def _on_start_stop(self) -> None:
        """Handle the start/stop toggle hotkey."""
        logger.debug("Start/stop hotkey triggered")
        self.start_triggered.emit()

    def _on_pause_resume(self) -> None:
        """Handle the pause/resume toggle hotkey."""
        logger.debug("Pause/resume hotkey triggered")
        self.pause_triggered.emit()