"""Task-aware MCP handoff: existing-session retrieval.

Distinguishes three things the brief forbids conflating:
context saved locally, context available over MCP, and evidence that an agent
actually retrieved it. Also verifies images arrive as real MCP image content,
not a base64 string hidden in a text block.
"""

from __future__ import annotations

import base64
import json

import pytest

from arrow.mcp.server import MCPServer, dispatch
from arrow.mcp.tools import ArrowTools, ToolError
from arrow.storage.database import get_db_connection
from arrow.storage.repository import Repository
from arrow.storage.task_repository import TaskRepository

# A 1x1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def wired(tmp_path):
    db = str(tmp_path / "mcp.db")
    repo = Repository(db)
    tasks = TaskRepository(db)
    server = MCPServer(db_path=db, repository=repo)
    return server, repo, tasks, db


def _seed(repo, tasks, shot):
    task_id = tasks.create_task(
        title="Move the search bar",
        instruction="Move the selected search bar into the navbar.",
        project_path=r"D:\projects\example",
    )
    # Use the real persistence API so sessions/change_requests/assets stay
    # consistent exactly as the capture pipeline would leave them.
    for cid, title in (("cap-1", "Example App"), ("cap-2", "Example App")):
        repo.create_capture(
            capture_id=cid,
            change_request={
                "raw_user_request": f"note for {cid}",
                "summary": f"move {cid}",
            },
            assets={"screenshot": str(shot)},
            mode="desktop",
        )
        with get_db_connection(repo._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO contexts (capture_id, data) VALUES (?, ?)",
                (cid, json.dumps({"window_title": title, "process_name": "chrome.exe"})),
            )
            conn.commit()
        tasks.add_capture(task_id, cid)
    return task_id


def _call(server, name, args=None):
    return dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": args or {}}},
        server.tools,
        server.resources,
    )


# -- retrieval --------------------------------------------------------------


def test_latest_task_returns_the_manifest(wired, tmp_path):
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    server, repo, tasks, db = wired
    _seed(repo, tasks, shot)

    payload = json.loads(_call(server, "arrow_get_latest_task")["result"]["content"][0]["text"])
    assert payload["instruction"].startswith("Move the selected")
    assert payload["capture_count"] == 2


def test_latest_task_without_any_task_is_a_clear_error(wired):
    server, _repo, _tasks, _db = wired
    resp = _call(server, "arrow_get_latest_task")
    assert resp["result"]["isError"] is True
    assert "No Arrow tasks yet" in resp["result"]["content"][0]["text"]


def test_list_tasks(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)

    items = json.loads(_call(server, "arrow_list_tasks")["result"]["content"][0]["text"])
    assert items[0]["task_id"] == task_id
    assert items[0]["capture_count"] == 2


def test_get_task_context_by_id(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)

    payload = json.loads(
        _call(server, "arrow_get_task_context", {"task_id": task_id})["result"]["content"][0]["text"]
    )
    assert payload["task_id"] == task_id
    assert [c["order"] for c in payload["captures"]] == [1, 2]


def test_deleted_task_cannot_be_retrieved(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)
    tasks.delete_task(task_id)

    resp = _call(server, "arrow_get_task_context", {"task_id": task_id})
    assert resp["result"]["isError"] is True
    assert "No task found" in resp["result"]["content"][0]["text"]


def test_task_captures_are_returned_in_user_order(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)
    tasks.reorder(task_id, ["cap-2", "cap-1"])

    caps = json.loads(
        _call(server, "arrow_list_task_captures", {"task_id": task_id})["result"]["content"][0]["text"]
    )
    assert [c["capture_id"] for c in caps] == ["cap-2", "cap-1"]


def test_task_markdown_is_available(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)

    text = _call(server, "arrow_get_task_markdown", {"task_id": task_id})["result"]["content"][0]["text"]
    assert "# Arrow Task Context" in text
    assert "## Capture 1" in text


def test_missing_task_id_is_rejected(wired):
    server, _repo, _tasks, _db = wired
    resp = _call(server, "arrow_get_task_context", {})
    assert resp["result"]["isError"] is True
    assert "task_id is required" in resp["result"]["content"][0]["text"]


# -- image transport --------------------------------------------------------


def test_capture_image_returns_real_image_content(wired, tmp_path):
    """An agent must be able to actually SEE the screenshot."""
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)

    content = _call(server, "arrow_get_capture_image", {"capture_id": "cap-1"})["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "image", "image must be a real MCP image block"
    assert content[0]["mimeType"] == "image/png"
    assert base64.b64decode(content[0]["data"]) == PNG


def test_capture_image_is_not_wrapped_in_a_text_block(wired, tmp_path):
    """A base64 string in a text block is not viewable by an agent."""
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)

    for block in _call(server, "arrow_get_capture_image", {"capture_id": "cap-1"})["result"]["content"]:
        assert block["type"] != "text"


def test_capture_image_for_unknown_capture_is_a_clear_error(wired):
    server, _repo, _tasks, _db = wired
    resp = _call(server, "arrow_get_capture_image", {"capture_id": "ghost"})
    assert resp["result"]["isError"] is True
    assert "No capture found" in resp["result"]["content"][0]["text"]


def test_missing_image_fails_clearly(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "gone.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)
    shot.unlink()

    resp = _call(server, "arrow_get_capture_image", {"capture_id": "cap-1"})
    assert resp["result"]["isError"] is True
    assert "missing on disk" in resp["result"]["content"][0]["text"]


def test_oversized_image_is_refused_rather_than_truncated(wired, tmp_path, monkeypatch):
    import arrow.mcp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "MAX_IMAGE_BYTES", 4)
    server, repo, tasks, db = wired
    shot = tmp_path / "big.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)

    resp = _call(server, "arrow_get_capture_image", {"capture_id": "cap-1"})
    assert resp["result"]["isError"] is True
    assert "above the" in resp["result"]["content"][0]["text"]


def test_capture_image_ignores_a_caller_supplied_path(wired, tmp_path):
    """A capture id must never become an arbitrary file read."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)

    resp = _call(
        server,
        "arrow_get_capture_image",
        {"capture_id": "cap-1", "asset": str(secret)},
    )
    # Unknown asset names fall back to the recorded screenshot, never the caller's path.
    content = resp["result"]["content"]
    assert base64.b64decode(content[0]["data"]) == PNG
    assert b"TOPSECRET" not in base64.b64decode(content[0]["data"])


def test_unknown_asset_name_falls_back_to_the_screenshot(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    _seed(repo, tasks, shot)

    content = _call(
        server, "arrow_get_capture_image", {"capture_id": "cap-1", "asset": "nonsense"}
    )["result"]["content"]
    assert base64.b64decode(content[0]["data"]) == PNG


# -- honest integration state ----------------------------------------------


def test_task_status_is_not_flipped_just_by_being_available(wired, tmp_path):
    """MCP availability is not evidence an agent engaged."""
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)

    payload = json.loads(_call(server, "arrow_get_task_context", {"task_id": task_id})["result"]["content"][0]["text"])
    assert payload["status"] == "draft"


def test_agent_can_record_real_progress(wired, tmp_path):
    server, repo, tasks, db = wired
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    task_id = _seed(repo, tasks, shot)

    tasks.set_status(task_id, "running")
    payload = json.loads(_call(server, "arrow_get_task_context", {"task_id": task_id})["result"]["content"][0]["text"])
    assert payload["status"] == "running"


# -- protocol ---------------------------------------------------------------


def test_all_task_tools_are_advertised(wired):
    server, _repo, _tasks, _db = wired
    tools = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, server.tools, server.resources)
    names = {t["name"] for t in tools["result"]["tools"]}
    for expected in (
        "arrow_get_latest_task",
        "arrow_list_tasks",
        "arrow_get_task_context",
        "arrow_get_task_markdown",
        "arrow_list_task_captures",
        "arrow_get_capture_image",
        "arrow_get_fresh_screen_context",
    ):
        assert expected in names


def test_legacy_capture_tools_still_work(wired):
    server, _repo, _tasks, _db = wired
    assert "arrow_get_latest_change_request" in server.tools.names()
    assert "arrow_get_context_md" in server.tools.names()


def test_unknown_tool_is_rejected(wired):
    server, _repo, _tasks, _db = wired
    with pytest.raises(ToolError):
        server.tools.call("arrow_not_a_tool", {})


def test_tools_constructor_stays_backward_compatible(tmp_path):
    """Existing callers pass only a repository."""
    tools = ArrowTools(Repository(str(tmp_path / "x.db")))
    assert "arrow_get_latest_change_request" in tools.names()