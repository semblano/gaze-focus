"""Global hotkey via pynput, running in a daemon thread.

pynput's GlobalHotKeys.start() blocks (it owns the X11 event loop for key
grabbing), so it runs in its own daemon thread. The callback fires on that
thread — keep it to flipping thread-safe state (the Controller), never touch
Qt from it.
"""
import threading


def start_hotkey(hotkey, callback):
    """Start a global hotkey listener. `hotkey` uses pynput syntax, e.g.
    '<ctrl>+<alt>+g'. Returns the listener (call .stop() to stop it)."""
    from pynput.keyboard import GlobalHotKeys
    listener = GlobalHotKeys({hotkey: callback})
    t = threading.Thread(target=listener.start, daemon=True, name="gaze-hotkey")
    t.start()
    return listener
