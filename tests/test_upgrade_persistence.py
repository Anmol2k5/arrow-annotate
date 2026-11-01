"""Exercise released on-disk data and the real source MCP stdio entry point."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from arrow.launcher import app_version

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_upgrade_smoke", ROOT / "scripts" / "windows_upgrade_smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
SOURCE_COMMAND = [sys.executable, str(ROOT / "main.py"), "--mcp"]
VERSION_COMMAND = [sys.executable, str(ROOT / "main.py"), "--version"]


@pytest.fixture
def seeded(tmp_path):
    home = tmp_path / "isolated upgrade home नमस्ते"
    smoke.seed(home)
    return home


def verify(home, expected_version=None):
    return smoke.check(home, SOURCE_COMMAND, expected_version or app_version(), VERSION_COMMAND)


def test_released_fixture_roundtrips_real_mcp(seeded):
    report = verify(seeded)
    assert report["success"]
    assert report["schema_version"] >= 3
    assert report["preferences"]["capture_shortcut"] == "ctrl+shift"
    assert report["mcp"]["metadata"]["original_voice_transcript"] != report["mcp"]["metadata"]["current_instruction"]
    # A second bundle read may add handoff assets; semantic preservation still passes.
    assert verify(seeded)["success"]
    from PIL import Image
    with Image.open(smoke.expected_fixture(seeded)["screenshot_path"]) as image:
        image.load()
        assert image.size == (2, 2)


@pytest.mark.parametrize("key,value", [
    ("capture_shortcut", "ctrl+space"), ("speech_language", "en-US"),
    ("clipboard_mode", "two_step"), ("auto_expand_capture", True), ("keep_notch_open", False),
    ("selected_project_dir", "missing repository"),
])
def test_changed_preferences_fail(seeded, key, value):
    path = seeded / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config[key] = value
    smoke.write_json(path, config)
    with pytest.raises(ValueError, match="Saved preferences changed"):
        verify(seeded)


def test_missing_selected_repository_fails(seeded):
    Path(smoke.expected_fixture(seeded)["preferences"]["selected_project_dir"]).rmdir()
    with pytest.raises(ValueError, match="repository directory is missing"):
        verify(seeded)


@pytest.mark.parametrize("field", ["original_voice_transcript", "current_instruction", "annotations", "capture_context"])
def test_changed_capture_context_fails(seeded, field):
    with sqlite3.connect(seeded / "arrow.db") as conn:
        row = conn.execute("SELECT data FROM contexts WHERE capture_id=?", (smoke.CAPTURE_ID,)).fetchone()
        context = json.loads(row[0])
        context[field] = "corrupted synthetic context"
        conn.execute("UPDATE contexts SET data=? WHERE capture_id=?", (json.dumps(context), smoke.CAPTURE_ID))
    with pytest.raises(ValueError, match="Capture context changed"):
        verify(seeded)


@pytest.mark.parametrize("remove", [False, True])
def test_changed_or_missing_png_fails(seeded, remove):
    image = Path(smoke.expected_fixture(seeded)["screenshot_path"])
    if remove:
        image.unlink()
    else:
        image.write_bytes(b"not the original synthetic PNG")
    with pytest.raises((ValueError, FileNotFoundError)):
        verify(seeded)


def test_deleted_capture_fails(seeded):
    with sqlite3.connect(seeded / "arrow.db") as conn:
        conn.execute("DELETE FROM sessions WHERE capture_id=?", (smoke.CAPTURE_ID,))
    with pytest.raises(ValueError, match="SQLite foreign keys|capture is missing"):
        verify(seeded)


def test_wrong_installed_version_fails(seeded):
    with pytest.raises(ValueError, match="Installed MCP version changed"):
        verify(seeded, "0.0.0-wrong-version")


def test_seed_refuses_existing_user_files(tmp_path):
    home = tmp_path / "existing home"
    home.mkdir()
    config = home / "config.json"
    config.write_text('{"capture_shortcut":"real-user-value"}', encoding="utf-8")
    original = config.read_bytes()
    with pytest.raises(ValueError, match="refusing existing data"):
        smoke.seed(home)
    assert config.read_bytes() == original
    assert not (home / "arrow.db").exists()


def test_seed_cli_and_failure_report(tmp_path):
    home = tmp_path / "synthetic home"
    report_path = tmp_path / "report.json"
    command = [sys.executable, str(ROOT / "scripts" / "windows_upgrade_smoke.py"),
               "seed", str(home), "--report", str(report_path)]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["schema_version"] == 3
    assert subprocess.run(command, capture_output=True, check=False).returncode == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not report["success"]
    assert "refusing existing data" in report["error"]


def test_report_cannot_overwrite_home_data(seeded):
    config = seeded / "config.json"
    original = config.read_bytes()
    assert smoke.main(["seed", str(seeded), "--report", str(config)]) == 1
    assert config.read_bytes() == original


def test_frozen_release_fixture_does_not_import_current_migrations(tmp_path, monkeypatch):
    import arrow.storage.migrations
    monkeypatch.setattr(arrow.storage.migrations, "MIGRATIONS", [(999, "invalid SQL")])
    home = tmp_path / "release home"
    smoke.seed(home)
    with sqlite3.connect(home / "arrow.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
