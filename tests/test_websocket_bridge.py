"""Tests for the WebSocket bridge bearer-token handshake."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile

import pytest
import websockets

os.environ.setdefault("ARROW_HOME", tempfile.mkdtemp(prefix="arrow_ws_"))

from arrow.server.security import TokenManager  # noqa: E402
from arrow.server.server import WebSocketBridge  # noqa: E402


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def bridge():
    token_path = os.path.join(tempfile.mkdtemp(prefix="arrow_ws_tok_"), "token")
    tm = TokenManager(path=token_path)
    b = WebSocketBridge(host="127.0.0.1", port=_free_port(), token_manager=tm, auth_timeout=1.5)
    b.start()
    return b, tm


def test_bridge_rejects_invalid_token(bridge):
    b, tm = bridge

    async def _run():
        async with websockets.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "auth", "token": "not-the-token"}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_error"

    asyncio.run(_run())
    assert b.connected is False


def test_bridge_rejects_non_string_token(bridge):
    b, tm = bridge

    async def _run():
        async with websockets.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "auth", "token": ["not", "a", "string"]}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_error"

    asyncio.run(_run())
    assert b.connected is False


def test_bridge_rejects_missing_auth_message(bridge):
    b, tm = bridge

    async def _run():
        async with websockets.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "inspect", "id": "1", "x": 0, "y": 0}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_error"

    asyncio.run(_run())
    assert b.connected is False


def test_bridge_closes_without_auth_timeout(bridge):
    b, tm = bridge

    async def _run():
        async with websockets.connect(f"ws://127.0.0.1:{b.port}") as ws:
            # Say nothing; the server must report auth_error, then close us.
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            assert msg["type"] == "auth_error"
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), timeout=8)

    asyncio.run(_run())
    assert b.connected is False


def test_bridge_valid_token_round_trip(bridge):
    """With the right token, auth_ok is sent and inspect round-trips."""
    b, tm = bridge
    token = tm.get_or_create()

    async def _run():
        async with websockets.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "auth", "token": token}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_ok"
            assert b.connected is True  # registered before auth_ok was sent

            # b.inspect blocks waiting for the matching id reply; run it aside.
            fut = asyncio.get_running_loop().run_in_executor(None, b.inspect, 10, 20)
            cmd = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert cmd["type"] == "inspect"
            assert cmd["x"] == 10 and cmd["y"] == 20
            await ws.send(json.dumps({"id": cmd["id"], "tag": "BUTTON", "text": "Submit"}))
            result = await asyncio.wait_for(fut, timeout=5)
            # The bridge strips the correlation id before resolving the caller.
            assert result == {"tag": "BUTTON", "text": "Submit"}

    asyncio.run(_run())
    # The client has disconnected by now, so the bridge must have deregistered it.
    assert b.connected is False


def test_bridge_inspect_before_auth_raises(bridge):
    b, tm = bridge
    with pytest.raises(ConnectionError):
        b.inspect(0, 0)
