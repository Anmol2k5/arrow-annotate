import sys
import signal

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from notch import DynamicNotch
from server import AgentServer


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bluely Agent")

    # -- Start Flask server in background daemon thread --
    server = AgentServer(host="127.0.0.1", port=5001)
    server.start()

    # -- Build and show the DynamicNotch overlay --
    notch = DynamicNotch(server=server)
    notch.show()

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
