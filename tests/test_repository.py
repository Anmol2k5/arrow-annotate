import os

import pytest

from arrow.storage.database import get_db_connection, init_db
from arrow.storage.migrations import LATEST_VERSION, run_migrations, schema_version
from arrow.storage.repository import Repository


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "repo.db")


def _change_request(capture_id="cap1", text="move this"):
    return {
        "schema_version": 1,
        "capture_id": capture_id,
        "raw_user_request": text,
        "normalized_intent": "move_element",
    }


def test_migrations_set_version(db_path):
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        assert schema_version(conn) == LATEST_VERSION


def test_migrations_idempotent(db_path):
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        v1 = run_migrations(conn)
        v2 = run_migrations(conn)
    assert v1 == v2 == LATEST_VERSION


def test_new_tables_exist(db_path):
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("projects", "change_requests", "anchors", "context_results",
              "provider_runs", "status_history", "settings", "pending_asset_deletions"):
        assert t in names


def test_atomic_create_and_get(db_path, tmp_path):
    repo = Repository(db_path)
    raw = tmp_path / "raw.png"
    raw.write_bytes(b"img")
    repo.create_capture("cap1", _change_request(), assets={"raw": str(raw)})
    cap = repo.get_capture("cap1")
    assert cap is not None
    assert cap["change_request"]["raw_user_request"] == "move this"
    assert "raw" in cap["assets"]


def test_latest_and_list(db_path):
    repo = Repository(db_path)
    repo.create_capture("cap1", _change_request("cap1", "first"))
    repo.create_capture("cap2", _change_request("cap2", "second"))
    latest = repo.get_latest_capture()
    assert latest["capture_id"] == "cap2"
    assert len(repo.list_captures()) == 2


def test_delete_removes_asset_files(db_path, tmp_path):
    repo = Repository(db_path)
    raw = tmp_path / "raw.png"
    annotated = tmp_path / "annotated.png"
    raw.write_bytes(b"a")
    annotated.write_bytes(b"b")
    repo.create_capture("cap1", _change_request(),
                        assets={"raw": str(raw), "annotated": str(annotated)})
    repo.delete_capture("cap1")
    assert repo.get_capture("cap1") is None
    assert not raw.exists()
    assert not annotated.exists()


def test_delete_all(db_path):
    repo = Repository(db_path)
    repo.create_capture("cap1", _change_request("cap1"))
    repo.create_capture("cap2", _change_request("cap2"))
    repo.delete_all()
    assert repo.list_captures() == []


def test_retention_by_count(db_path):
    repo = Repository(db_path)
    for i in range(5):
        repo.create_capture(f"cap{i}", _change_request(f"cap{i}"))
    deleted = repo.apply_retention(max_count=2)
    assert deleted == 3
    assert len(repo.list_captures()) == 2


def test_status_history_and_set_status(db_path):
    repo = Repository(db_path)
    repo.create_capture("cap1", _change_request())
    repo.set_status("cap1", "running", "agent started")
    cap = repo.get_capture("cap1")
    assert cap["status"] == "running"
    with get_db_connection(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM status_history WHERE capture_id = 'cap1'").fetchone()[0]
    assert count >= 2  # created + running


def test_provider_run_lifecycle(db_path):
    repo = Repository(db_path)
    repo.create_capture("cap1", _change_request())
    run_id = repo.add_provider_run("cap1", "codex")
    repo.update_provider_run(run_id, "completed", notes="done")
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT status, notes FROM provider_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "completed"
    assert row["notes"] == "done"


def test_settings_roundtrip(db_path):
    repo = Repository(db_path)
    repo.set_setting("retention", {"max_count": 100})
    assert repo.get_setting("retention") == {"max_count": 100}
    assert repo.get_setting("missing", "fallback") == "fallback"


def test_corrupted_record_reported(db_path):
    repo = Repository(db_path)
    repo.create_capture("cap1", _change_request())
    with get_db_connection(db_path) as conn:
        conn.execute("UPDATE change_requests SET data = ? WHERE capture_id = 'cap1'", ("{bad json",))
        conn.commit()
    cap = repo.get_capture("cap1")
    assert cap["change_request"].get("_corrupted") is True


def test_pending_deletion_retry(db_path, tmp_path, monkeypatch):
    repo = Repository(db_path)
    asset = tmp_path / "locked.png"
    asset.write_bytes(b"x")
    repo.create_capture("cap1", _change_request(), assets={"raw": str(asset)})

    # Force the first deletion attempt to fail.
    real_remove = os.remove
    calls = {"n": 0}

    def flaky_remove(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("locked")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    repo.delete_capture("cap1")
    # File still on disk, queued for retry.
    assert asset.exists()
    remaining = repo.retry_pending_deletions()
    assert remaining == 0
    assert not asset.exists()
