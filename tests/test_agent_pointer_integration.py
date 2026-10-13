"""Agent pointer integration: bridge threading, MCP tool, HTTP surface.

The MCP server and the desktop app are separate processes, so a preview has to
cross a process boundary and then a thread boundary before it touches Qt.
These tests pin both hops, including the failure paths.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time

os.environ["ARROW_HOME"] = tempfile.mkdtemp(prefix="arrow_ptr_")

import pytest

from arrow.server import server as srv
from arrow.server.agent_actions import AgentActions
from arrow.server.security import Capability, CapabilityManager, TokenManager

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class Recorder:
    """Stands in for the GUI thread hook."""

    def __init__(self):
        self.previews = []
        self.approvals = []
        self.hidden = 0

    def preview(self, x, y, highlight, label):
        self.previews.append((x, y, highlight, label))

    def approval(self, request):
        self.approvals.append(request)

    def hide(self):
        self.hidden += 1


@pytest.fixture
def hooks():
    rec = Recorder()
    performed = []

    class Hooks:
        preview = staticmethod(rec.preview)
        hide = staticmethod(rec.hide)
        approval = staticmethod(rec.approval)

    Hooks.actions = AgentActions(
        executor=lambda r: performed.append(r.action_type) or {"ok": True},
        current_window=lambda: "Example App",
    )
    Hooks.performed = performed
    Hooks.rec = rec
    return Hooks


@pytest.fixture
def client(hooks, monkeypatch):
    token_path = os.path.join(tempfile.mkdtemp(prefix="arrow_tok_"), "token")
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(path=token_path))
    caps = CapabilityManager()
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", caps)
    monkeypatch.setitem(srv.app.config, "AGENT_HOOKS", hooks)
    srv.app.config["CAPABILITIES"].enable(Capability.CONTROL_NATIVE)
    return srv.app.test_client()


def _token():
    return srv.app.config["TOKEN_MANAGER"].get_or_create()


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


@pytest.fixture
def no_auth_client(monkeypatch):
    monkeypatch.setitem(
        srv.app.config, "TOKEN_MANAGER",
        TokenManager(path=os.path.join(tempfile.mkdtemp(), "token")),
    )
    caps = CapabilityManager()
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", caps)
    monkeypatch.setitem(srv.app.config, "AGENT_HOOKS", None)
    srv.app.config["CAPABILITIES"].enable(Capability.CONTROL_NATIVE)
    return srv.app.test_client()


# ---------------------------------------------------------------------------
# Authentication and capability
# ---------------------------------------------------------------------------


def test_preview_requires_a_token(client):
    assert client.post("/agent/preview", json={"x": 1, "y": 2}).status_code == 401


def test_preview_requires_control_native(monkeypatch, hooks):
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(
        path=os.path.join(tempfile.mkdtemp(), "token")))
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", CapabilityManager())
    monkeypatch.setitem(srv.app.config, "AGENT_HOOKS", hooks)
    c = srv.app.test_client()
    resp = c.post("/agent/preview", json={"x": 1, "y": 2}, headers=_auth())
    assert resp.status_code == 403, "must be off by default"


def test_action_endpoints_require_a_token(client):
    assert client.post("/agent/action", json={
        "action_type": "click_target", "x": 1, "y": 2}).status_code == 401
    assert client.post("/agent/stop", json={}).status_code == 401


def test_action_endpoints_require_control_native(monkeypatch, hooks):
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(
        path=os.path.join(tempfile.mkdtemp(), "token")))
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", CapabilityManager())
    monkeypatch.setitem(srv.app.config, "AGENT_HOOKS", hooks)
    c = srv.app.test_client()
    assert c.post("/agent/stop", json={}, headers=_auth()).status_code == 403


# ---------------------------------------------------------------------------
# Preview is visual only
# ---------------------------------------------------------------------------


def test_preview_draws_and_clicks_nothing(client, hooks):
    resp = client.post("/agent/preview",
                       json={"x": 300, "y": 400, "reason": "the search button"},
                       headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert hooks.performed == [], "preview must never execute an action"
    assert hooks.rec.previews == [(300, 400, None, "the search button")]


def test_preview_does_not_raise_an_approval_prompt(client, hooks):
    """A preview is not an action request and must not ask for permission."""
    client.post("/agent/preview", json={"x": 10, "y": 10}, headers=_auth())
    assert hooks.rec.approvals == []


def test_preview_supports_negative_monitor_coordinates(client, hooks):
    resp = client.post("/agent/preview",
                       json={"x": -1500, "y": -900,
                             "highlight": [-1600, -1000, 200, 60]},
                       headers=_auth())
    assert resp.status_code == 200
    x, y, highlight, _label = hooks.rec.previews[0]
    assert (x, y) == (-1500, -900)
    assert highlight == (-1600, -1000, 200, 60)


def test_preview_validates_the_highlight(client, hooks):
    resp = client.post("/agent/preview",
                       json={"x": 1, "y": 1, "highlight": [0, 0, 0, 10]},
                       headers=_auth())
    assert resp.status_code == 400
    assert hooks.rec.previews == []


def test_preview_rejects_absurd_highlight(client):
    resp = client.post("/agent/preview",
                       json={"x": 1, "y": 1, "highlight": [0, 0, 999999, 5]},
                       headers=_auth())
    assert resp.status_code == 400


def test_preview_requires_coordinates(client):
    assert client.post("/agent/preview", json={}, headers=_auth()).status_code == 400


def test_preview_without_a_desktop_fails_closed(monkeypatch, client, hooks):
    monkeypatch.setitem(srv.app.config, "AGENT_HOOKS", None)
    resp = client.post("/agent/preview", json={"x": 1, "y": 2}, headers=_auth())
    assert resp.status_code == 503
    assert resp.get_json()["reason"] == "no_desktop"


def test_preview_hook_raising_is_reported_not_swallowed(client, hooks, monkeypatch):
    def boom(*a):
        raise RuntimeError("pointer window died")

    monkeypatch.setattr(hooks, "preview", staticmethod(boom))
    resp = client.post("/agent/preview", json={"x": 1, "y": 2}, headers=_auth())
    assert resp.status_code == 500
    assert resp.get_json()["reason"] == "preview_failed"


# ---------------------------------------------------------------------------
# The approval handshake
# ---------------------------------------------------------------------------


def test_action_request_awaits_and_prompts(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 300, "y": 400,
        "window_title": "Example App", "reason": "press the button",
    }, headers=_auth())
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["state"] == "awaiting_approval"
    assert body["executed"] is False
    assert hooks.performed == []
    assert len(hooks.rec.approvals) == 1
    assert hooks.rec.approvals[0].action_type == "click_target"


def test_allow_executes_exactly_once(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())
    action_id = resp.get_json()["action_id"]

    allowed = client.post(f"/agent/action/{action_id}",
                          json={"allow": True}, headers=_auth())
    assert allowed.get_json()["executed"] is True
    assert hooks.performed == ["click_target"]

    # A replay of the same decision must not fire again.
    replay = client.post(f"/agent/action/{action_id}",
                         json={"allow": True}, headers=_auth())
    assert replay.status_code == 409
    assert hooks.performed == ["click_target"]


def test_deny_executes_nothing(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())
    action_id = resp.get_json()["action_id"]

    denied = client.post(f"/agent/action/{action_id}",
                         json={"allow": False}, headers=_auth())
    assert denied.get_json()["state"] == "denied"
    assert hooks.performed == []


def test_decide_requires_a_boolean(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())
    action_id = resp.get_json()["action_id"]
    bad = client.post(f"/agent/action/{action_id}",
                      json={"allow": "yes"}, headers=_auth())
    assert bad.status_code == 400
    assert hooks.performed == []


def test_unknown_action_status_is_404(client):
    assert client.get("/agent/action/nope", headers=_auth()).status_code == 404


def test_pending_status_reports_awaiting(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())
    action_id = resp.get_json()["action_id"]
    state = client.get(f"/agent/action/{action_id}", headers=_auth()).get_json()
    assert state["state"] == "awaiting_approval"
    assert state["executed"] is False


def test_status_after_deny_is_truthful(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())
    action_id = resp.get_json()["action_id"]
    client.post(f"/agent/action/{action_id}", json={"allow": False}, headers=_auth())
    state = client.get(f"/agent/action/{action_id}", headers=_auth()).get_json()
    assert state["state"] == "denied"
    assert state["executed"] is False


def test_stop_cancels_pending_and_hides_pointer(client, hooks):
    client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "window_title": "Example App"}, headers=_auth())

    stopped = client.post("/agent/stop", json={}, headers=_auth())
    assert stopped.get_json()["cancelled"] == 1
    assert hooks.rec.hidden == 1
    assert hooks.performed == []


def test_command_injection_is_rejected_end_to_end(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "click_target", "x": 5, "y": 5,
        "command": "powershell -enc AAAA"}, headers=_auth())
    assert resp.status_code == 400
    assert resp.get_json()["reason"] == "forbidden_field"
    assert hooks.performed == []
    assert hooks.rec.approvals == []


def test_unknown_action_type_is_rejected(client, hooks):
    resp = client.post("/agent/action", json={
        "action_type": "run_shell", "x": 1, "y": 1}, headers=_auth())
    assert resp.status_code == 400
    assert resp.get_json()["reason"] == "unsupported_action"


def test_malformed_payload_is_rejected(client):
    for payload in ({"action_type": "click_target"},
                    {"action_type": "click_target", "x": "a", "y": 1},
                    {"x": 1, "y": 1}):
        assert client.post("/agent/action", json=payload,
                           headers=_auth()).status_code == 400


# ---------------------------------------------------------------------------
# The Qt bridge
# ---------------------------------------------------------------------------


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class _FakePointer:
    def __init__(self):
        self.points = []
        self.hides = 0

    def point_at(self, x, y, highlight=None):
        self.points.append((x, y, highlight))

    def hide_pointer(self):
        self.hides += 1


def test_bridge_delivers_to_the_gui_thread(qapp):

    from arrow.ui.agent_bridge import AgentPointerBridge

    pointer = _FakePointer()
    bridge = AgentPointerBridge()
    bridge.attach(pointer, lambda *a: None)

    t = threading.Thread(target=lambda: bridge.request_preview(120, 240, None, "hi"))
    t.start()
    t.join()

    deadline = time.monotonic() + 3
    while not pointer.points and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()

    assert pointer.points == [(120, 240, None)]


def test_bridge_runs_on_the_main_thread(qapp):
    from PyQt6.QtCore import QThread

    from arrow.ui.agent_bridge import AgentPointerBridge

    seen = {}
    bridge = AgentPointerBridge()
    bridge.attach(_FakePointer(), lambda *a: seen.setdefault("thread", QThread.currentThread()))

    t = threading.Thread(target=lambda: bridge.request_approval("a1", "click_target", 1, 2))
    t.start()
    t.join()
    deadline = time.monotonic() + 3
    while "thread" not in seen and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()

    assert seen["thread"] == qapp.thread(), "Qt work must land on the GUI thread"


def test_bridge_hide_is_delivered(qapp):
    from arrow.ui.agent_bridge import AgentPointerBridge

    pointer = _FakePointer()
    bridge = AgentPointerBridge()
    bridge.attach(pointer, lambda *a: None)

    bridge.request_hide()
    deadline = time.monotonic() + 3
    while pointer.hides == 0 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert pointer.hides == 1


def test_bridge_without_a_pointer_does_not_raise(qapp):
    from arrow.ui.agent_bridge import AgentPointerBridge

    bridge = AgentPointerBridge()  # never attached
    bridge.request_preview(1, 2)
    bridge.request_hide()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def test_bridge_carries_negative_coordinates(qapp):
    from arrow.ui.agent_bridge import AgentPointerBridge

    pointer = _FakePointer()
    bridge = AgentPointerBridge()
    bridge.attach(pointer, lambda *a: None)

    t = threading.Thread(
        target=lambda: bridge.request_preview(-1400, -950, [-1500, -1050, 200, 60])
    )
    t.start()
    t.join()
    deadline = time.monotonic() + 3
    while not pointer.points and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert pointer.points[0][0] == -1400
    assert pointer.points[0][1] == -950


# ---------------------------------------------------------------------------
# The MCP tool
# ---------------------------------------------------------------------------


class FakeDesktop:
    def __init__(self, response=None):
        self.posts = []
        self.gets = []
        self.response = response or {"ok": True, "state": "previewed"}

    def post(self, path, payload):
        self.posts.append((path, payload))
        return self.response

    def get(self, path):
        self.gets.append(path)
        return {"ok": True, "state": "awaiting_approval", "executed": False}


@pytest.fixture
def tools(tmp_path):
    from arrow.mcp.tools import ArrowTools
    from arrow.storage.repository import Repository

    return ArrowTools(Repository(str(tmp_path / "m.db")))


def test_preview_tool_posts_to_the_desktop(tools, tmp_path):
    desktop = FakeDesktop()
    tools._desktop = desktop
    result = tools.call("arrow_preview_target", {"x": 300, "y": 400,
                                                 "reason": "the button"})
    assert result["clicked"] is False
    path, payload = desktop.posts[0]
    assert path == "/agent/preview"
    assert payload["x"] == 300 and payload["y"] == 400
    assert payload["label"] == "the button"


def test_preview_tool_reports_refusal_honestly(tools):
    tools._desktop = FakeDesktop({"ok": False, "reason": "no_desktop",
                                  "detail": "Arrow is not running"})
    from arrow.mcp.tools import ToolError

    with pytest.raises(ToolError) as exc:
        tools.call("arrow_preview_target", {"x": 1, "y": 1})
    assert "not running" in str(exc.value)


def test_preview_tool_requires_a_point(tools):
    from arrow.mcp.tools import ToolError

    tools._desktop = FakeDesktop()
    with pytest.raises(ToolError):
        tools.call("arrow_preview_target", {})


def test_preview_tool_reuses_capture_bounds(tools, tmp_path):
    import json

    from arrow.storage.database import get_db_connection

    shot = tmp_path / "s.png"
    shot.write_bytes(b"x")
    repo = tools.repo
    repo.create_capture(
        "cap-1", {"raw_user_request": "go"}, assets={"screenshot": str(shot)}
    )
    with get_db_connection(repo._db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO contexts (capture_id, data) VALUES (?, ?)",
            ("cap-1", json.dumps({"target": {
                "resolution_method": "windows_uia", "confidence_kind": "heuristic",
                "bounds": {"x": -1500, "y": -900, "width": 200, "height": 60}}})),
        )
        conn.commit()

    desktop = FakeDesktop()
    tools._desktop = desktop
    tools.call("arrow_preview_target", {"capture_id": "cap-1"})
    _, payload = desktop.posts[0]
    assert payload["x"] == -1500 and payload["y"] == -900
    assert payload["highlight"] == [-1500, -900, 200, 60]


def test_request_action_tool_never_claims_execution(tools):
    desktop = FakeDesktop({"ok": True, "state": "awaiting_approval",
                           "action_id": "a1"})
    tools._desktop = desktop
    result = tools.call("arrow_request_action",
                        {"action_type": "click_target", "x": 5, "y": 5,
                         "window_title": "Example App"})
    assert result["executed"] is False
    assert result["state"] == "awaiting_approval"
    assert desktop.posts[0][0] == "/agent/action"


def test_stop_tool_posts_to_stop(tools):
    desktop = FakeDesktop({"ok": True, "cancelled": 2})
    tools._desktop = desktop
    result = tools.call("arrow_stop_agent", {})
    assert desktop.posts[0][0] == "/agent/stop"
    assert result["cancelled"] == 2


def test_action_status_tool_uses_get(tools):
    desktop = FakeDesktop()
    tools._desktop = desktop
    tools.call("arrow_action_status", {"action_id": "a1"})
    assert desktop.gets == ["/agent/action/a1"]
    assert desktop.posts == [], "status must never decide anything"