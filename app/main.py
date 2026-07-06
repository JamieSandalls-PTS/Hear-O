"""Entry point: wires audio capture -> analyzer -> overlay, plus tray + hotkey."""

import sys

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .analyzer import Analyzer
from .audio_capture import AudioEngine
from .classifier import Classifier
from .config import Settings
from .hotkey import HotkeyManager
from .hud import HudOverlay
from .settings_window import SettingsWindow
from .subtitles import SubtitleEngine


class Bridge(QObject):
    """Marshals cross-thread events (hotkey, audio status) onto the GUI thread."""
    open_settings = Signal()
    status = Signal(str)
    class_status = Signal(str)
    sub_status = Signal(str)


def _make_icon():
    """A tiny generated icon (concentric rings) so we ship no image assets."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    for r, col in ((30, QColor("#2b7bff")), (20, QColor("#39e639")), (10, QColor("#ff2020"))):
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 90))
        p.drawEllipse(32 - r, 32 - r, r * 2, r * 2)
    p.end()
    return QIcon(pix)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hear-O")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive

    settings = Settings()
    analyzer = Analyzer(settings)
    bridge = Bridge()

    overlay = HudOverlay(settings)
    overlay.show()

    subtitles = SubtitleEngine(
        settings,
        on_text=overlay.set_subtitle,
        on_status=lambda msg: bridge.sub_status.emit(msg),
    )

    classifier = Classifier(
        settings,
        on_detections=overlay.set_detections,
        on_status=lambda msg: bridge.class_status.emit(msg),
        on_speech=subtitles.set_speech_active,
    )

    audio = AudioEngine(
        settings, analyzer,
        on_frame=overlay.set_frame,
        on_status=lambda msg: bridge.status.emit(msg),
        mono_consumers=[classifier, subtitles],
    )

    # Turn the HUD preview animation off whenever settings is hidden/closed.
    settings_win = SettingsWindow(settings, on_apply=overlay.apply_settings,
                                  audio_engine=audio,
                                  on_hide=lambda: overlay.set_preview(False),
                                  classifier=classifier)
    bridge.class_status.connect(settings_win.set_class_status)
    bridge.sub_status.connect(settings_win.set_sub_status)

    # -- settings window open also starts the HUD preview animation --
    def open_settings():
        overlay.set_preview(True)
        settings_win.show()
        settings_win.raise_()
        settings_win.activateWindow()

    bridge.open_settings.connect(open_settings)
    bridge.status.connect(settings_win.set_status)

    # -- global hotkey ------------------------------------------------------
    hotkeys = HotkeyManager()
    combo = settings.get("hotkey_settings", "ctrl+alt+o")
    hotkeys.register(combo, lambda: bridge.open_settings.emit())

    # -- system tray --------------------------------------------------------
    tray = QSystemTrayIcon(_make_icon())
    tray.setToolTip("Hear-O")
    menu = QMenu()

    act_settings = QAction("Settings")
    act_settings.triggered.connect(open_settings)
    menu.addAction(act_settings)

    act_toggle = QAction("Hide overlay")
    def toggle_overlay():
        if overlay.isVisible():
            overlay.hide()
            act_toggle.setText("Show overlay")
        else:
            overlay.show()
            act_toggle.setText("Hide overlay")
    act_toggle.triggered.connect(toggle_overlay)
    menu.addAction(act_toggle)

    menu.addSeparator()
    act_quit = QAction("Quit")
    def quit_app():
        hotkeys.unregister()
        classifier.stop()
        subtitles.stop()
        audio.stop()
        tray.hide()
        app.quit()
    act_quit.triggered.connect(quit_app)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: open_settings()
        if reason == QSystemTrayIcon.Trigger else None)
    tray.show()

    if not hotkeys.available():
        tray.showMessage(
            "Hear-O",
            "Global hotkey unavailable ('keyboard' not installed). "
            "Use the tray icon to open settings.",
            _make_icon(), 6000)
    else:
        tray.showMessage(
            "Hear-O running",
            f"Press {combo} or click the tray icon for settings.",
            _make_icon(), 5000)

    # -- render loop: push the latest audio frame to the overlay ~60fps -----
    render = QTimer()
    render.timeout.connect(overlay.update)
    render.start(16)

    audio.start()
    classifier.start()
    subtitles.start()

    exit_code = app.exec()
    hotkeys.unregister()
    classifier.stop()
    subtitles.stop()
    audio.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
