import sys
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication


class HotkeyBridge(QObject):
    triggered = pyqtSignal()


def test_hotkey_bridge_cross_thread_trigger():
    app = QApplication.instance() or QApplication(sys.argv)
    
    bridge = HotkeyBridge()
    called_on_main = False

    def on_hotkey():
        nonlocal called_on_main
        called_on_main = QThread.currentThread() == app.thread()
        app.quit()

    bridge.triggered.connect(on_hotkey)

    # Emit signal from background thread (simulating keyboard hook)
    def bg_thread():
        bridge.triggered.emit()

    t = threading.Thread(target=bg_thread, daemon=True)
    t.start()
    t.join()

    # Process events to allow Qt queued connection to execute on main thread
    app.exec()

    assert called_on_main is True
