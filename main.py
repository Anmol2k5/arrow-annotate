import sys
import signal

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from notch import DynamicNotch
from server import AgentServer
from highlight_overlay import SelectionOverlay


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bluely Agent")

    # -- Start Flask server in background daemon thread --
    server = AgentServer(host="127.0.0.1", port=5001)
    server.start()

    # -- Build and show the DynamicNotch overlay --
    notch = DynamicNotch(server=server)
    notch.show()

    # -- Setup Highlight Overlay --
    overlay = SelectionOverlay()

    def trigger_highlight():
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(overlay, "show_overlay", Qt.ConnectionType.QueuedConnection)

    notch.on_highlight_requested = trigger_highlight

    def on_selection(result):
        # Call the server endpoint to capture the region
        def _capture_task():
            import urllib.request
            import json as _json
            req = urllib.request.Request(
                f"{server.base_url}/highlight/capture",
                data=_json.dumps({"rect": result.to_dict()}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                # Tell the notch to refresh its screenshots view
                from PyQt6.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(notch._content_stack.widget(2), "_scan_existing", Qt.ConnectionType.QueuedConnection)
            except Exception as e:
                print(f"Highlight capture failed: {e}")

        import threading
        threading.Thread(target=_capture_task, daemon=True).start()

    overlay.selection_complete.connect(on_selection)

    # Optional global hotkey
    try:
        import keyboard
        keyboard.add_hotkey("ctrl+shift+space", trigger_highlight)
    except Exception as e:
        print(f"Warning: could not register global hotkey: {e}")

    # -- Poll server status every 5s to update notch --
    def poll_server():
        try:
            import urllib.request
            import json as _json
            url = f"{server.base_url}/status"
            resp = urllib.request.urlopen(url, timeout=2)
            data = _json.loads(resp.read().decode())
            notch.update_status(f"● {data.get('status', 'connected').title()}")
        except Exception:
            notch.update_status("○ Offline")

    poll_timer = QTimer()
    poll_timer.timeout.connect(poll_server)
    poll_timer.start(5000)
    poll_server()

    # -- Graceful shutdown on SIGINT --
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
