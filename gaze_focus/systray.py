"""Systray icon showing gaze-focus status: loaded / enabled / disabled.

Lives in the main thread (same as the gaze loop) so all Qt calls are on one
thread — no cross-thread Qt marshalling. The main loop calls process_events()
each iteration; the pynput hotkey only flips the Controller flag, and the next
process_events()/refresh() picks it up. Reuses the overlay's QApplication if
one already exists, so --overlay and the tray coexist.
"""
import os

os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)  # cv2 poisons this on import
from PyQt5 import QtCore, QtGui, QtWidgets

from .sysbindings import find_conflicts

# (r, g, b) per status
STATUS_COLORS = {
    "enabled": (70, 200, 90),    # green
    "disabled": (130, 130, 130),  # gray
    "loaded": (70, 130, 220),     # blue
}
STATUS_LABEL = {
    "enabled": "enabled — gaze switches focus",
    "disabled": "disabled — gaze tracking paused",
    "loaded": "loaded — waiting for camera",
}


def _icon_pixmap(status):
    r, g, b = STATUS_COLORS.get(status, (130, 130, 130))
    pm = QtGui.QPixmap(22, 22)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(r, g, b))
    p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(2, 2, 18, 18)
    # a small "eye" so it reads as gaze tracking
    p.setBrush(QtGui.QColor(255, 255, 255))
    p.drawEllipse(8, 8, 6, 6)
    p.end()
    return QtGui.QIcon(pm)


# Qt key -> pynput <name> for keys that aren't a plain printable character
_NAMED_KEYS = {
    QtCore.Qt.Key_Space: "space",
    QtCore.Qt.Key_Tab: "tab",
    QtCore.Qt.Key_Backspace: "backspace",
    QtCore.Qt.Key_Return: "enter",
    QtCore.Qt.Key_Enter: "enter",
    QtCore.Qt.Key_Escape: "esc",
    QtCore.Qt.Key_Delete: "delete",
    QtCore.Qt.Key_Home: "home",
    QtCore.Qt.Key_End: "end",
    QtCore.Qt.Key_PageUp: "page_up",
    QtCore.Qt.Key_PageDown: "page_down",
    QtCore.Qt.Key_Left: "left",
    QtCore.Qt.Key_Right: "right",
    QtCore.Qt.Key_Up: "up",
    QtCore.Qt.Key_Down: "down",
    QtCore.Qt.Key_Insert: "insert",
    QtCore.Qt.Key_CapsLock: "caps_lock",
    QtCore.Qt.Key_NumLock: "num_lock",
    QtCore.Qt.Key_ScrollLock: "scroll_lock",
    QtCore.Qt.Key_Print: "print_screen",
    QtCore.Qt.Key_Pause: "pause",
    QtCore.Qt.Key_Menu: "menu",
}
# keys that are themselves modifiers: wait for a following "real" key instead
# of firing the hotkey on the modifier alone
_MODIFIER_KEYS = {
    QtCore.Qt.Key_Control, QtCore.Qt.Key_Alt, QtCore.Qt.Key_AltGr,
    QtCore.Qt.Key_Shift, QtCore.Qt.Key_Meta,
}


def _qt_main_key_name(key):
    """pynput <name> (or single lowercase char) for a Qt key code the user
    pressed, or None if unsupported."""
    if key in _NAMED_KEYS:
        return f"<{_NAMED_KEYS[key]}>"
    if QtCore.Qt.Key_F1 <= key <= QtCore.Qt.Key_F35:
        return f"<f{key - QtCore.Qt.Key_F1 + 1}>"
    if 0x20 <= key <= 0x7e:  # Qt maps A-Z/0-9/most punctuation to ASCII
        return chr(key).lower()
    return None


def _qt_modifier_names(qmods):
    mods = []
    if qmods & QtCore.Qt.ControlModifier:
        mods.append("<ctrl>")
    if qmods & QtCore.Qt.AltModifier:
        mods.append("<alt>")
    if qmods & QtCore.Qt.ShiftModifier:
        mods.append("<shift>")
    if qmods & QtCore.Qt.MetaModifier:
        mods.append("<cmd>")
    return mods


class _HotkeyCaptureDialog(QtWidgets.QDialog):
    """Records the next real key combination the user presses and turns it
    into pynput hotkey syntax — no need to know that syntax by hand. Warns
    (but doesn't block) if the combo already matches a desktop keybinding."""

    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("gaze-focus — change hotkey")
        self.setModal(True)
        self.combo = None
        self._label = QtWidgets.QLabel(
            f"Current hotkey: {current or '(none)'}\n\n"
            "Press the new key combination now…\n(Esc cancels)")
        buttons = QtWidgets.QDialogButtonBox()
        disable_btn = buttons.addButton("Disable Hotkey", QtWidgets.QDialogButtonBox.DestructiveRole)
        cancel_btn = buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        disable_btn.clicked.connect(self._disable)
        cancel_btn.clicked.connect(self.reject)
        # buttons must not hold keyboard focus, or Space/Enter activate them
        # instead of reaching our keyPressEvent (e.g. Shift+Space would just
        # "click" Disable Hotkey)
        disable_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        cancel_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(buttons)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus(QtCore.Qt.OtherFocusReason)

    def _disable(self):
        self.combo = "none"
        self.accept()

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        key = event.key()
        if key == QtCore.Qt.Key_Escape and event.modifiers() == QtCore.Qt.NoModifier:
            self.reject()
            return
        if key in _MODIFIER_KEYS:
            mods = "+".join(m.strip("<>") for m in _qt_modifier_names(event.modifiers()))
            self._label.setText(f"…{mods}" if mods else "…")
            return
        main = _qt_main_key_name(key)
        if main is None:
            self._label.setText("That key isn't supported — try another combination…")
            return
        combo = "+".join(_qt_modifier_names(event.modifiers()) + [main])
        conflicts = find_conflicts(combo)
        if conflicts:
            reply = QtWidgets.QMessageBox.question(
                self, "gaze-focus — possible conflict",
                f"{combo} already looks bound to:\n\n"
                + "\n".join(f" • {c}" for c in conflicts)
                + "\n\nUse it anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if reply != QtWidgets.QMessageBox.Yes:
                self._label.setText("Press the new key combination now…\n(Esc cancels)")
                return
        self.combo = combo
        self.accept()


class GazeTray:
    def __init__(self, controller, on_quit, on_toggle=None, hotkey=None,
                 on_hotkey_change=None):
        self.controller = controller
        self.on_quit = on_quit
        self._toggle = on_toggle or controller.toggle
        self._hotkey = hotkey
        self._on_hotkey_change = on_hotkey_change
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.tray = QtWidgets.QSystemTrayIcon()

        self.act_toggle = QtWidgets.QAction("Enabled", self.tray)
        self.act_toggle.setCheckable(True)
        self.act_toggle.setChecked(controller.enabled)
        self.act_toggle.triggered.connect(self._on_toggle)
        self.act_hotkey = QtWidgets.QAction("Change Hotkey…", self.tray)
        self.act_hotkey.triggered.connect(self._on_change_hotkey)
        self.act_hotkey.setEnabled(self._on_hotkey_change is not None)
        self.act_quit = QtWidgets.QAction("Quit", self.tray)
        self.act_quit.triggered.connect(self._on_quit)

        menu = QtWidgets.QMenu()
        menu.addAction(self.act_toggle)
        menu.addAction(self.act_hotkey)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)

        self._last = None
        self.refresh()
        self.tray.show()

    def _on_toggle(self):
        self._toggle()
        self.refresh()

    def _on_activated(self, reason):
        # single left-click toggles; right-click opens the menu (default)
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._toggle()
            self.refresh()

    def _on_change_hotkey(self):
        if self._on_hotkey_change is None:
            return
        dlg = _HotkeyCaptureDialog(self._hotkey)
        if dlg.exec_() != QtWidgets.QDialog.Accepted or not dlg.combo:
            return
        text = dlg.combo
        if text == (self._hotkey or ""):
            return
        try:
            self._on_hotkey_change(text)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                None, "gaze-focus", f"Could not set hotkey {text!r}:\n{exc}")
            return
        self._hotkey = text
        label = "disabled" if text == "none" else text
        self.tray.showMessage("gaze-focus", f"Hotkey {label}",
                              QtWidgets.QSystemTrayIcon.Information, 3000)

    def _on_quit(self):
        self.on_quit()

    def refresh(self):
        """Update icon/tooltip/menu to match the controller. Cheap: only
        touches Qt when the status actually changed."""
        st = self.controller.status()
        if st == self._last:
            return
        self._last = st
        self.tray.setIcon(_icon_pixmap(st))
        self.tray.setToolTip(f"gaze-focus: {STATUS_LABEL.get(st, st)}")
        self.act_toggle.setChecked(self.controller.enabled)
        self.act_toggle.setText("Enabled" if self.controller.enabled else "Disabled")

    def process_events(self):
        self.app.processEvents()

    def close(self):
        self.tray.hide()
        self.app.processEvents()
