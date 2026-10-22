"""ARROW_HOME must be honored by every runtime consumer that writes user data.

The parsing layer already validates ARROW_HOME (tests/test_config.py); this file
pins the *consumers*, which is where propagation actually breaks: the database
and the capture asset directories were derived from ``__file__`` instead.
"""

import importlib
import os

import pytest


@pytest.fixture
def arrow_home(tmp_path, monkeypatch):
    """Point ARROW_HOME at an isolated directory and reload the consumers."""
    home = tmp_path / "arrowhome"
    home.mkdir()
    monkeypatch.setenv("ARROW_HOME", str(home))
    monkeypatch.delenv("ARROW_DB_PATH", raising=False)
    return home


def _reimport(name):
    module = importlib.import_module(name)
    return importlib.reload(module)


def test_database_honors_arrow_home(arrow_home):
    database = _reimport("arrow.storage.database")
    expected = os.path.join(str(arrow_home), "arrow.db")
    assert database.default_db_path() == expected


def test_capture_store_dirs_honor_arrow_home(arrow_home):
    store = _reimport("arrow.storage.capture_store")
    assert store.screenshots_dir() == os.path.join(str(arrow_home), "screenshots")
    assert store.captures_dir() == os.path.join(str(arrow_home), "captures")


def test_stored_captures_land_under_arrow_home(arrow_home, tmp_path):
    """End-to-end: a record written by CaptureStore lives under ARROW_HOME."""
    from arrow.storage.capture_store import CaptureStore
    from arrow.storage.schemas import CaptureRecord

    store = CaptureStore()
    record = CaptureRecord(
        id="cap-home-test",
        timestamp="2026-01-01T00:00:00+00:00",
        screenshot_path=os.path.join(str(arrow_home), "screenshots", "cap-home-test.png"),
    )
    store.add(record)
    try:
        db = os.path.join(str(arrow_home), "arrow.db")
        assert os.path.isfile(db), f"expected DB under ARROW_HOME, not {db}"
        assert store.get("cap-home-test") is not None
    finally:
        store.delete("cap-home-test")


# -- legacy data migration -------------------------------------------------
# Before this change the database and asset directories were derived from the
# checkout path. Existing installs must not silently lose their history.

LEGACY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_legacy_repo_data_is_migrated_into_arrow_home(arrow_home, tmp_path, monkeypatch):
    """A pre-existing repo-local database moves into ARROW_HOME exactly once."""
    from arrow.core.config import migrate_legacy_home

    legacy_db = tmp_path / "legacy" / "arrow.db"
    legacy_db.parent.mkdir()
    legacy_db.write_bytes(b"legacy-db")
    legacy_shots = tmp_path / "legacy" / "screenshots"
    legacy_shots.mkdir()
    (legacy_shots / "old.png").write_bytes(b"old-png")

    monkeypatch.setattr("arrow.core.config.legacy_root", lambda: str(tmp_path / "legacy"))

    moved_db = migrate_legacy_home()
    assert moved_db is True
    assert (arrow_home / "arrow.db").is_file()
    assert (arrow_home / "screenshots" / "old.png").is_file()
    assert not legacy_db.exists()

    # Idempotent: a second run is a no-op and never clobbers live data.
    (arrow_home / "arrow.db").write_bytes(b"live-db")
    assert migrate_legacy_home() is False
    assert (arrow_home / "arrow.db").read_bytes() == b"live-db"


def test_migration_never_overwrites_existing_arrow_home(tmp_path, monkeypatch):
    """If ARROW_HOME already has a database, legacy data is left untouched."""
    from arrow.core.config import migrate_legacy_home

    home = tmp_path / "home"
    (home / "screenshots").mkdir(parents=True)
    (home / "arrow.db").write_bytes(b"live")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "arrow.db").write_bytes(b"old")

    monkeypatch.setattr("arrow.core.config.legacy_root", lambda: str(legacy))
    monkeypatch.setattr("arrow.core.config.resolve_home", lambda: str(home))

    assert migrate_legacy_home() is False
    assert (home / "arrow.db").read_bytes() == b"live"
    assert (legacy / "arrow.db").read_bytes() == b"old"


def test_migration_does_nothing_without_legacy_data(tmp_path, monkeypatch):
    """A fresh install with no legacy checkout data is a no-op."""
    from arrow.core.config import migrate_legacy_home

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("arrow.core.config.legacy_root", lambda: str(tmp_path / "nope"))
    monkeypatch.setattr("arrow.core.config.resolve_home", lambda: str(home))

    assert migrate_legacy_home() is False
    assert not (home / "arrow.db").exists()