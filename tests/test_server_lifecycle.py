import json
import socket
import urllib.request

import pytest

from arrow.server.security import TokenManager
from arrow.server.server import AgentServer, WebSocketBridge


def test_server_stop_releases_http_and_websocket_ports(tmp_path, monkeypatch):
    from arrow.server import server as module
    monkeypatch.setitem(module.app.config, 'TOKEN_MANAGER', TokenManager(str(tmp_path / 'token')))
    server = AgentServer(port=0, ws_port=0)
    try:
        server.start()
        with urllib.request.urlopen(server.base_url + '/status', timeout=3) as response:
            assert json.load(response)['status'] == 'healthy'
        http_port, ws_port = server.port, server.ws_bridge.port
    finally:
        server.stop()
    for port in (http_port, ws_port):
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0
    server.start()
    server.stop()


def test_bridge_reports_bind_failure_to_caller(tmp_path):
    with socket.socket() as blocker:
        blocker.bind(('127.0.0.1', 0))
        blocker.listen()
        bridge = WebSocketBridge(port=blocker.getsockname()[1], token_manager=TokenManager(str(tmp_path / 'token')))
        with pytest.raises(RuntimeError, match='start'):
            bridge.start()


@pytest.mark.parametrize('kwargs', [{'host': '0.0.0.0'}, {'ws_host': '0.0.0.0'}])
def test_local_server_rejects_non_loopback_bindings(kwargs):
    with pytest.raises(ValueError, match='localhost'):
        AgentServer(**kwargs)


def test_stop_serializes_with_in_progress_start(tmp_path, monkeypatch):
    import threading

    from arrow.server import server as module
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    class SlowBridge:
        port = 0

        def __init__(self, **kwargs):
            pass

        def start(self):
            entered.set()
            assert release.wait(3)

        def stop(self):
            pass

    monkeypatch.setattr(module, 'WebSocketBridge', SlowBridge)
    server = AgentServer(port=0, ws_port=0)
    starter = threading.Thread(target=server.start)
    stopper = threading.Thread(target=lambda: (server.stop(), stopped.set()))
    starter.start()
    assert entered.wait(1)
    stopper.start()
    try:
        assert not stopped.wait(0.05)
    finally:
        release.set()
        starter.join(2)
        stopper.join(2)
        server.stop()
    assert not server._running
    assert not server._thread.is_alive()
