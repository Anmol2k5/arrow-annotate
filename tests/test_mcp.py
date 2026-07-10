import pytest

from arrow.mcp.server import MCPServer
from arrow.mcp.tools import ArrowTools, ToolError
from arrow.storage.repository import Repository


def _cr(capture_id="cap1"):
    return {
        "schema_version": 1,
        "capture_id": capture_id,
        "raw_user_request": "move this button here",
        "normalized_intent": "move_element",
        "summary": "Move Buy to Here",
        "source": {"label": "Buy", "element": {"selector": "#buy"}},
        "destination": {"label": "Here"},
        "project": {"repository_root": "/repo", "current_branch": "main"},
        "likely_files": [{"source_file": "src/Buy.tsx", "source_line": 3}],
        "confidence": 0.8,
    }


@pytest.fixture
def repo(tmp_path):
    r = Repository(str(tmp_path / "mcp.db"))
    raw = tmp_path / "raw.png"
    annotated = tmp_path / "annotated.png"
    raw.write_bytes(b"raw-bytes")
    annotated.write_bytes(b"annotated-bytes")
    r.create_capture("cap1", _cr("cap1"), assets={"raw": str(raw), "annotated": str(annotated)})
    r.create_capture("cap2", _cr("cap2"))
    return r


def test_tools_latest(repo):
    tools = ArrowTools(repo)
    cr = tools.call("arrow_get_latest_change_request")
    assert cr["capture_id"] == "cap2"


def test_tools_get_and_contexts(repo):
    tools = ArrowTools(repo)
    assert tools.call("arrow_get_change_request", {"capture_id": "cap1"})["summary"] == "Move Buy to Here"
    assert tools.call("arrow_get_source_context", {"capture_id": "cap1"})["label"] == "Buy"
    assert tools.call("arrow_get_destination_context", {"capture_id": "cap1"})["label"] == "Here"
    assert tools.call("arrow_get_project_context", {"capture_id": "cap1"})["current_branch"] == "main"


def test_tools_metadata_and_list(repo):
    tools = ArrowTools(repo)
    meta = tools.call("arrow_get_capture_metadata", {"capture_id": "cap1"})
    assert "raw" in meta["assets"]
    listed = tools.call("arrow_list_change_requests", {"limit": 10})
    assert len(listed) == 2


def test_tools_unknown_capture(repo):
    tools = ArrowTools(repo)
    with pytest.raises(ToolError):
        tools.call("arrow_get_change_request", {"capture_id": "nope"})


def test_tools_unknown_tool(repo):
    tools = ArrowTools(repo)
    with pytest.raises(ToolError):
        tools.call("nonexistent_tool")


def test_mutation_tools(repo):
    tools = ArrowTools(repo)
    assert tools.call("arrow_mark_started", {"capture_id": "cap1"})["status"] == "running"
    assert tools.call("arrow_mark_completed", {"capture_id": "cap1", "note": "ok"})["status"] == "completed"
    assert repo.get_capture("cap1")["status"] == "completed"
    tools.call("arrow_add_agent_note", {"capture_id": "cap1", "note": "hello"})


def test_dispatch_initialize_and_tools_list(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["result"]["serverInfo"]["name"] == "arrow-mcp"
    resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "arrow_get_latest_change_request" in names


def test_dispatch_tools_call(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "arrow_get_change_request", "arguments": {"capture_id": "cap1"}},
    })
    import json
    text = resp["result"]["content"][0]["text"]
    assert json.loads(text)["capture_id"] == "cap1"


def test_dispatch_tools_call_error_is_iserror(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "arrow_get_change_request", "arguments": {"capture_id": "missing"}},
    })
    assert resp["result"]["isError"] is True


def test_dispatch_resources_list_and_read(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    uris = [r["uri"] for r in resp["result"]["resources"]]
    assert "arrow://captures/cap1/raw" in uris

    resp = server.handle({
        "jsonrpc": "2.0", "id": 6, "method": "resources/read",
        "params": {"uri": "arrow://captures/cap1/raw"},
    })
    import base64
    blob = resp["result"]["contents"][0]["blob"]
    assert base64.b64decode(blob) == b"raw-bytes"


def test_dispatch_resource_not_found(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({
        "jsonrpc": "2.0", "id": 7, "method": "resources/read",
        "params": {"uri": "arrow://captures/cap1/missing-crop"},
    })
    assert "error" in resp


def test_dispatch_notification_returns_none(repo):
    server = MCPServer(repository=repo)
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_dispatch_unknown_method(repo):
    server = MCPServer(repository=repo)
    resp = server.handle({"jsonrpc": "2.0", "id": 8, "method": "bogus/method"})
    assert resp["error"]["code"] == -32601
