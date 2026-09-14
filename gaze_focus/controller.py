"""Thread-safe shared state for the systray, hotkey and main loop.

The main gaze loop, the pynput hotkey thread and the Qt tray all touch the
same "is switching on?" flag, so every read/write goes through a lock.
"""
import threading


class Controller:
    def __init__(self, enabled=True):
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._frames = False  # latches True once the camera delivers data

    @property
    def enabled(self):
        with self._lock:
            return self._enabled

    def set_enabled(self, value):
        with self._lock:
            self._enabled = bool(value)

    def toggle(self):
        """Flip the enabled flag; returns the new value."""
        with self._lock:
            self._enabled = not self._enabled
            return self._enabled

    def mark_frames(self):
        """Call once the camera starts delivering frames (loaded -> enabled)."""
        with self._lock:
            self._frames = True

    def status(self):
        """One of 'disabled', 'enabled', 'loaded'.

        'loaded' = enabled but the camera hasn't delivered frames yet.
        ('not loaded' is the absence of the process itself — no icon.)
        """
        with self._lock:
            if not self._enabled:
                return "disabled"
            return "enabled" if self._frames else "loaded"
