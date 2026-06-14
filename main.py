import sys
import os
import signal
import subprocess
import time
import urllib.request

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from notch import DynamicNotch
from server import AgentServer

AGENTATION_MCP_PORT = 4747


def find_agentation_mcp():
    """Locate agentation-mcp binary. Checks local node_modules, then npx."""
    local = os.path.join(os.path.dirname(__file__), "node_modules", ".bin", "agentation-mcp")
    if os.path.exists(local):
        return local
    local = os.path.join(os.path.dirname(__file__), "node_modules", "agentation-mcp", "dist", "cli.mjs")
    if os.path.exists(local):
        return local
    return "agentation-mcp"  # fall back to PATH / npx


def launch_agentation_mcp():
    """Start agentation-mcp server as a background process."""
    binary = find_agentation_mcp()
    try:
        proc = subprocess.Popen(
            [binary, "server", "--port", str(AGENTATION_MCP_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # Wait up to 5s for it to become healthy
        for _ in range(10):
            try:
                resp = urllib.request.urlopen(f"http://127.0.0.1:{AGENTATION_MCP_PORT}/health", timeout=1)
                if resp.status == 200:
                    print(f"[Agentation MCP] healthy on port {AGENTATION_MCP_PORT}")
                    return proc
            except Exception:
                time.sleep(0.5)
        print("[Agentation MCP] started but health check timed out")
        return proc
    except FileNotFoundError:
        print("[Agentation MCP] not found — install with: npm install -g agentation-mcp")
        return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bluely Agent")

    # -- Start Flask server in background daemon thread --
    server = AgentServer(host="127.0.0.1", port=5001)
    server.start()

    # -- Launch agentation-mcp server --
    agentation_proc = launch_agentation_mcp()

    # -- Build and show the DynamicNotch overlay --
    notch = DynamicNotch(server=server)
    notch.show()

    # -- Poll server status every 5s to update notch --
    def poll_server():
        try:
            url = f"{server.base_url}/status"
            resp = urllib.request.urlopen(url, timeout=2)
            import json as _json
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

    exit_code = app.exec()

    # -- Cleanup agentation-mcp --
    if agentation_proc:
        agentation_proc.terminate()
        agentation_proc.wait(timeout=3)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
