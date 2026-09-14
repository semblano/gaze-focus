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
        current = self._hotkey or ""
        text, ok = QtWidgets.QInputDialog.getText(
            None, "gaze-focus — change hotkey",
            "Enable/disable hotkey (pynput syntax, e.g. <ctrl>+<alt>+g;\n"
            "'none' disables the hotkey entirely):",
            QtWidgets.QLineEdit.Normal, current)
        if not ok:
            return
        text = text.strip()
        if not text or text == current:
            return
        try:
            self._on_hotkey_change(text)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                None, "gaze-focus", f"Could not set hotkey {text!r}:\n{exc}")
            return
        self._hotkey = text
        self.tray.showMessage("gaze-focus", f"Hotkey set to {text}",
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
