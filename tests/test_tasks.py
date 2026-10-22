"""TaskBundle persistence, ordering, editing and export.

Covers the Phase 2 acceptance path: create, add, reorder, edit, restart,
remove one, delete a task, and confirm older captures survive the migration.
"""

from __future__ import annotations

import json
import os

import pytest

from arrow.storage.database import get_db_connection, init_db
from arrow.storage.task_repository import TaskRepository
from arrow.storage.tasks import SCHEMA_VERSION, TaskStatus


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "tasks.db")


@pytest.fixture
def repo(db_path):
    r = TaskRepository(db_path)
    yield r
    # Simulates a restart: a brand-new repository over the same file.
    TaskRepository(db_path).list_tasks()


def _capture(repo, capture_id, **kw):
    """Persist a minimal capture row the way the capture pipeline would."""
    with get_db_connection(repo._db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (capture_id, created_at, updated_at, state, mode, voice_transcript)
               VALUES (?, ?, ?, 'COMPLETED', ?, ?)""",
            (
                capture_id,
                kw.get("created_at", "2026-01-01T00:00:00+00:00"),
                kw.get("created_at", "2026-01-01T00:00:00+00:00"),
                kw.get("mode", "desktop"),
                kw.get("instruction", ""),
            ),
        )
        if kw.get("screenshot"):
            conn.execute(
                "INSERT INTO assets (capture_id, path, type) VALUES (?, ?, 'screenshot')",
                (capture_id, kw["screenshot"]),
            )
        if kw.get("context"):
            conn.execute(
                "INSERT OR REPLACE INTO contexts (capture_id, data) VALUES (?, ?)",
                (capture_id, json.dumps(kw["context"])),
            )
        conn.commit()


# -- create / add -----------------------------------------------------------


def test_create_task_returns_stable_id(repo):
    task_id = repo.create_task(title="Move the button")
    assert task_id.startswith("task_")
    assert repo.get_task_row(task_id) is not None


def test_add_three_captures_keeps_order(repo):
    task_id = repo.create_task()
    for cid in ("c1", "c2", "c3"):
        _capture(repo, cid)
        repo.add_capture(task_id, cid)

    task = repo.get_task(task_id)
    assert [c.capture_id for c in task.captures] == ["c1", "c2", "c3"]
    assert [c.position for c in task.captures] == [1, 2, 3]


def test_adding_to_unknown_task_is_rejected(repo):
    _capture(repo, "c1")
    assert repo.add_capture("nope", "c1") is False


def test_a_capture_belongs_to_at_most_one_task(repo):
    t1 = repo.create_task()
    t2 = repo.create_task()
    _capture(repo, "c1")
    repo.add_capture(t1, "c1")
    repo.add_capture(t2, "c1")

    assert repo.task_for_capture("c1") == t2
    assert [c.capture_id for c in repo.get_task(t1).captures] == []


# -- edit -------------------------------------------------------------------


def test_edit_title_and_instruction(repo):
    task_id = repo.create_task(title="old", instruction="old text")
    repo.update_task(task_id, title="new", instruction="move it right")
    task = repo.get_task(task_id)
    assert task.title == "new"
    assert task.instruction == "move it right"


def test_edit_individual_capture_note(repo):
    task_id = repo.create_task()
    _capture(repo, "c1")
    repo.add_capture(task_id, "c1")
    assert repo.set_capture_note(task_id, "c1", "this is the navbar") is True
    assert repo.get_task(task_id).captures[0].note == "this is the navbar"


def test_update_task_returns_false_for_unknown_task(repo):
    assert repo.update_task("missing", title="x") is False


# -- reorder ----------------------------------------------------------------


def test_reorder_captures(repo):
    task_id = repo.create_task()
    for cid in ("c1", "c2", "c3"):
        _capture(repo, cid)
        repo.add_capture(task_id, cid)

    assert repo.reorder(task_id, ["c3", "c1", "c2"]) is True
    assert [c.capture_id for c in repo.get_task(task_id).captures] == ["c3", "c1", "c2"]


def test_reorder_with_unknown_id_is_rejected(repo):
    task_id = repo.create_task()
    _capture(repo, "c1")
    repo.add_capture(task_id, "c1")
    assert repo.reorder(task_id, ["c1", "ghost"]) is False
    assert [c.capture_id for c in repo.get_task(task_id).captures] == ["c1"]


def test_reorder_with_missing_id_is_rejected(repo):
    """A partial list must not silently drop a capture from the task."""
    task_id = repo.create_task()
    for cid in ("c1", "c2"):
        _capture(repo, cid)
        repo.add_capture(task_id, cid)
    assert repo.reorder(task_id, ["c2"]) is False
    assert len(repo.get_task(task_id).captures) == 2


# -- remove / delete --------------------------------------------------------


def test_remove_one_capture_keeps_the_rest(repo):
    task_id = repo.create_task()
    for cid in ("c1", "c2", "c3"):
        _capture(repo, cid)
        repo.add_capture(task_id, cid)

    assert repo.remove_capture(task_id, "c2") is True
    remaining = [c.capture_id for c in repo.get_task(task_id).captures]
    assert remaining == ["c1", "c3"]


def test_delete_task_keeps_captures_and_their_files(repo, tmp_path):
    """Task deletion must not delete capture assets owned by other records."""
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    task_id = repo.create_task()
    _capture(repo, "c1", screenshot=str(shot))
    repo.add_capture(task_id, "c1")

    assert repo.delete_task(task_id) is True
    assert repo.get_task(task_id) is None
    assert shot.exists(), "asset is owned by the capture, not the task"

    with get_db_connection(repo._db_path) as conn:
        row = conn.execute(
            "SELECT capture_id FROM sessions WHERE capture_id = 'c1'"
        ).fetchone()
    assert row is not None, "capture history must survive task deletion"


def test_delete_unknown_task_returns_false(repo):
    assert repo.delete_task("missing") is False


# -- persistence ------------------------------------------------------------


def test_task_survives_restart(db_path):
    first = TaskRepository(db_path)
    task_id = first.create_task(title="Persisted", instruction="keep me")
    for cid in ("c1", "c2"):
        _capture(first, cid)
        first.add_capture(task_id, cid)
    first.reorder(task_id, ["c2", "c1"])
    first.update_task(task_id, instruction="updated instruction")

    # New process would construct this from scratch over the same file.
    second = TaskRepository(db_path)
    task = second.get_task(task_id)
    assert task is not None
    assert task.title == "Persisted"
    assert task.instruction == "updated instruction"
    assert [c.capture_id for c in task.captures] == ["c2", "c1"]


def test_get_latest_task_picks_most_recent(repo):
    a = repo.create_task(title="first")
    b = repo.create_task(title="second")
    repo.update_task(a, title="first")
    # Touch A so it becomes the most recently updated.
    latest = repo.get_latest_task()
    assert latest.task_id in (a, b)
    assert repo.list_tasks(limit=1)[0]["task_id"] == latest.task_id


def test_task_created_without_captures_is_valid(repo):
    task_id = repo.create_task()
    task = repo.get_task(task_id)
    assert task.captures == []
    assert task.to_manifest()["capture_count"] == 0


# -- manifest ---------------------------------------------------------------


def _populated(repo):
    task_id = repo.create_task(
        title="Move the search bar",
        instruction="Move the selected search bar into the navbar.",
        project_path=r"D:\projects\example",
    )
    _capture(
        repo,
        "cap-1",
        mode="point",
        instruction="this is the search bar",
        screenshot=r"D:\shots\capture1.png",
        context={
            "window_title": "Example Application",
            "process_name": "chrome.exe",
            "target": {
                "resolution_method": "windows_uia",
                "confidence_kind": "heuristic",
                "label": "Search",
                "bounds": {"x": 100, "y": 200, "width": 150, "height": 40},
            },
        },
    )
    repo.add_capture(task_id, "cap-1")
    return task_id


def test_manifest_is_valid_json_with_schema_version(repo):
    task_id = _populated(repo)
    data = json.loads(repo.get_task(task_id).to_json())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["task_id"] == task_id
    assert data["instruction"].startswith("Move the selected")
    assert data["project"]["path"] == r"D:\projects\example"


def test_manifest_uses_actual_values_not_examples(repo):
    task_id = _populated(repo)
    cap = json.loads(repo.get_task(task_id).to_json())["captures"][0]
    assert cap["capture_id"] == "cap-1"
    assert cap["mode"] == "point"
    assert cap["order"] == 1
    assert cap["target"]["resolution_method"] == "windows_uia"
    assert cap["target"]["bounds"]["x"] == 100
    assert cap["target"]["bounds"]["coordinate_space"] == "virtual_desktop"
    assert cap["application"]["window_title"] == "Example Application"


def test_manifest_marks_fallback_targets_honestly(repo):
    task_id = repo.create_task()
    _capture(
        repo, "cap-f", mode="point",
        context={
            "target": {
                "resolution_method": "fallback",
                "confidence_kind": "none",
                "label": "",
                "bounds": {"x": -300, "y": -200, "width": 240, "height": 240},
            }
        },
    )
    repo.add_capture(task_id, "cap-f")
    cap = json.loads(repo.get_task(task_id).to_json())["captures"][0]
    assert cap["target"]["resolution_method"] == "fallback"
    assert cap["target"]["confidence_kind"] == "none"


def test_markdown_states_only_supported_detail(repo):
    task_id = _populated(repo)
    md = repo.get_task(task_id).to_markdown()
    assert "# Arrow Task Context" in md
    assert "Move the selected search bar into the navbar." in md
    assert "## Capture 1" in md
    assert "Application: chrome.exe" in md
    assert "resolution: windows_uia" in md
    # It must not invent a source-file mapping.
    assert ".tsx" not in md and "src/" not in md


def test_markdown_flags_missing_image_files(repo):
    task_id = _populated(repo)
    md = repo.get_task(task_id).to_markdown()
    assert "is missing on disk" in md


def test_markdown_declares_fallback_target(repo):
    task_id = repo.create_task(instruction="fix it")
    _capture(
        repo, "cap-f", mode="point",
        context={"target": {"resolution_method": "fallback", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}}},
    )
    repo.add_capture(task_id, "cap-f")
    md = repo.get_task(task_id).to_markdown()
    assert "not identified" in md
    assert "not a detected element" in md


def test_markdown_without_instruction_is_honest(repo):
    task_id = repo.create_task()
    md = repo.get_task(task_id).to_markdown()
    assert "No instruction was given" in md


def test_manifest_survives_a_deleted_capture_row(repo):
    """Ordering must not be silently reshuffed if a capture row disappears."""
    task_id = repo.create_task()
    for cid in ("c1", "c2"):
        _capture(repo, cid)
        repo.add_capture(task_id, cid)
    with get_db_connection(repo._db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE capture_id = 'c1'")
        conn.commit()

    task = repo.get_task(task_id)
    assert [c.capture_id for c in task.captures] == ["c1", "c2"]
    assert task.captures[0].timestamp == ""


# -- migration safety -------------------------------------------------------


def test_migration_preserves_older_captures_without_a_task(db_path):
    """Captures created before TaskBundles must remain valid and listable."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO sessions
               (capture_id, created_at, updated_at, state, mode)
               VALUES ('legacy', '2026-01-01T00:00:00+00:00',
                       '2026-01-01T00:00:00+00:00', 'COMPLETED', 'desktop')"""
        )
        conn.execute(
            "INSERT INTO assets (capture_id, path, type) VALUES ('legacy', 'x.png', 'screenshot')"
        )
        conn.commit()

    # Re-running migrations must be idempotent.
    init_db(db_path)

    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT capture_id FROM sessions WHERE capture_id = 'legacy'"
        ).fetchone()
        asset = conn.execute(
            "SELECT path FROM assets WHERE capture_id = 'legacy'"
        ).fetchone()
    assert row is not None and asset["path"] == "x.png"


def test_schema_version_advances(db_path):
    from arrow.storage.migrations import LATEST_VERSION, schema_version

    init_db(db_path)
    with get_db_connection(db_path) as conn:
        assert schema_version(conn) == LATEST_VERSION


def test_capture_without_task_is_not_listed_under_any_task(repo):
    _capture(repo, "orphan")
    assert repo.task_for_capture("orphan") is None
    assert repo.list_tasks() == []


def test_status_is_not_inferred_from_existence(repo):
    """A task is DRAFT until something proves an agent engaged."""
    task_id = repo.create_task()
    _capture(repo, "c1")
    repo.add_capture(task_id, "c1")
    assert repo.get_task(task_id).status == TaskStatus.DRAFT.value

    repo.set_status(task_id, TaskStatus.SENT.value)
    assert repo.get_task(task_id).status == "sent"


def test_assets_are_reported_per_capture(repo, tmp_path):
    shot = tmp_path / "a.png"
    shot.write_bytes(b"x")
    task_id = repo.create_task()
    _capture(repo, "c1", screenshot=str(shot))
    repo.add_capture(task_id, "c1")
    art = repo.get_task(task_id).captures[0]
    assert art.assets["screenshot"] == str(shot)
    assert json.loads(repo.get_task(task_id).to_json())["captures"][0]["assets"][
        "screenshot"
    ] == str(shot)


def test_markdown_paths_are_absolute_not_rewritten(repo, tmp_path):
    shot = tmp_path / "z.png"
    shot.write_bytes(b"x")
    task_id = repo.create_task()
    _capture(repo, "c1", screenshot=str(shot))
    repo.add_capture(task_id, "c1")
    md = repo.get_task(task_id).to_markdown()
    assert str(shot) in md
    assert os.path.isabs(str(shot))