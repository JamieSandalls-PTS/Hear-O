"""Global hotkey via the `keyboard` library.

The hotkey callback fires on the library's own thread, so it must not touch Qt
directly. main.py routes it through a queued Qt signal to reach the GUI thread.
"""

try:
    import keyboard
except Exception:  # pragma: no cover
    keyboard = None


class HotkeyManager:
    def __init__(self):
        self._registered = None

    def available(self):
        return keyboard is not None

    def register(self, combo, callback):
        """(Re)bind `combo` (e.g. 'ctrl+alt+o') to callback. Returns True on success."""
        if keyboard is None:
            return False
        self.unregister()
        try:
            keyboard.add_hotkey(combo, callback)
            self._registered = combo
            return True
        except Exception:
            return False

    def unregister(self):
        if keyboard is None or self._registered is None:
            return
        try:
            keyboard.remove_hotkey(self._registered)
        except Exception:
            pass
        self._registered = None
