import base64
import json
from pathlib import Path

import pytest
from PIL import Image

from arrow.context.capture_bundle import build_capture_bundle
from arrow.mcp.resources import ResourceProvider
from arrow.mcp.server import dispatch
from arrow.mcp.tools import ArrowTools, ToolError
from arrow.storage.capture_store import CaptureStore
from arrow.storage.database import get_db_connection
from arrow.storage.repository import Repository
from arrow.storage.schemas import CaptureRecord


def record(tmp_path, capture_id="capture-one", instruction="Move it", color="red"):
    path = tmp_path / f"{capture_id}.png"
    Image.new("RGB", (40, 30), color).save(path)
    return CaptureRecord(
        id=capture_id, timestamp="2026-10-31T00:00:00+00:00", screenshot_path=str(path),
        annotation_text=instruction, original_voice_transcript="original spoken words",
        annotations=[{"id": "ink", "type": "freehand", "role": "supporting",
                      "geometry": {"points": [{"x": -4, "y": 9, "t": 1}]}}],
        capture_context={"repository": {"repository_root": str(tmp_path), "current_commit": "abc123"},
                         "source": {"context": {"name": "Save", "window_title": "Editor"}},
                         "destination": {"context": {"name": "Toolbar", "window_title": "Browser"}},
                         "window_context": {"capture_start": {"window_title": "Editor"}},
                         "ax_tree": [{"name": "Save", "role": "Button"}]},
        change_request={"capture_id": capture_id, "raw_user_request": instruction,
                        "summary": instruction, "normalized_intent": "move_element",
                        "project": {"repository_root": str(tmp_path)},
                        "assets": {"annotated": str(path), "agent-annotated": str(path)}},
    )


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "state"))
    db = str(tmp_path / "captures.db")
    return CaptureStore(db), Repository(db), db


def test_bundle_is_bound_to_requested_capture_and_contains_persisted_context(tmp_path, storage):
    store, _, db = storage
    old = record(tmp_path)
    store.add(old)
    store.add(record(tmp_path, "newer", "Different instruction", "blue"))
    bundle = build_capture_bundle(old.id, db)
    assert bundle.metadata["capture_id"] == old.id
    assert bundle.metadata["original_voice_transcript"] == "original spoken words"
    assert bundle.metadata["current_instruction"] == "Move it"
    assert bundle.metadata["annotations"] == old.annotations
    assert bundle.metadata["repository_path"] == str(tmp_path)
    for value in ("Save", "Toolbar", "Editor", "Browser", "abc123", "original spoken words", old.id):
        assert value in bundle.prompt_text
    assert Path(bundle.prompt_path).read_text() == bundle.prompt_text
    assert Path(bundle.context_path).is_file()
    assert Path(bundle.directory, "capture.json").is_file()
    assert Image.open(bundle.annotated_path).getpixel((0, 0)) == (255, 0, 0)
    assert str(bundle.annotated_path) in bundle.prompt_text


def test_edits_preserve_original_speech_and_create_a_new_immutable_revision(tmp_path, storage):
    store, repo, db = storage
    cap = record(tmp_path)
    store.add(cap)
    first = build_capture_bundle(cap.id, db)
    repo.set_status(cap.id, "running")
    assert build_capture_bundle(cap.id, db).directory == first.directory
    changed = {**cap.change_request, "raw_user_request": "Make it green", "summary": "Make it green"}
    store.update_change_request(cap.id, changed, "Make it green")
    second = build_capture_bundle(cap.id, db)
    assert first.directory != second.directory
    assert "Make it green" not in Path(first.prompt_path).read_text()
    assert "Make it green" in second.prompt_text
    assert second.metadata["original_voice_transcript"] == "original spoken words"
    assert store.get(cap.id).annotation_text == "Make it green"
    assert repo.get_capture(cap.id)["status"] == "running"
    markdown = ArrowTools(repo).call("arrow_get_context_md", {"capture_id": cap.id})
    assert "Make it green" in markdown and "original spoken words" in markdown
    Image.new("RGB", (40, 30), "green").save(cap.screenshot_path)
    assert Image.open(first.annotated_path).getpixel((0, 0)) == (255, 0, 0)


def test_mcp_bundle_returns_the_stored_optimized_image_and_full_text(tmp_path, storage):
    store, repo, _ = storage
    cap = record(tmp_path)
    optimized = tmp_path / "optimized.png"
    Image.new("RGB", (20, 15), "blue").save(optimized)
    cap.change_request["assets"]["agent-annotated"] = str(optimized)
    store.add(cap)
    reply = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "arrow_get_capture_bundle", "arguments": {"capture_id": cap.id}}},
                     ArrowTools(repo), ResourceProvider(repo))
    content = reply["result"]["content"]
    payload = json.loads(next(part["text"] for part in content if part["type"] == "text"))
    assert payload["metadata"]["original_voice_transcript"] == "original spoken words"
    image = next(part for part in content if part["type"] == "image")
    assert base64.b64decode(image["data"]) == optimized.read_bytes()
    assert ArrowTools(repo).call("arrow_get_capture_bundle")["metadata"]["capture_id"] == cap.id


def test_delete_invalidates_matching_mirror_and_bundles_without_removing_other_latest(tmp_path, storage):
    from arrow.capture.context_file import latest_dir, mirror_latest
    store, repo, db = storage
    cap = record(tmp_path)
    store.add(cap)
    bundle = build_capture_bundle(cap.id, db)
    mirror_latest(cap.screenshot_path, "stale instruction", cap.id)
    store.delete(cap.id)
    assert not Path(bundle.directory).exists()
    assert not Path(latest_dir(), "capture.png").exists()
    with pytest.raises(ToolError):
        ArrowTools(repo).call("arrow_get_context_md")
    with pytest.raises((LookupError, FileNotFoundError)):
        build_capture_bundle(cap.id, db)
    old = record(tmp_path, "old")
    newer = record(tmp_path, "newer")
    store.add(old)
    store.add(newer)
    mirror_latest(newer.screenshot_path, "newer context", newer.id)
    store.delete(old.id)
    assert Path(latest_dir(), "context.md").read_text() == "newer context"


def test_scene_round_trips_and_legacy_capture_does_not_invent_original_speech(tmp_path, storage):
    store, repo, db = storage
    cap = record(tmp_path)
    store.add(cap)
    assert store.get(cap.id).annotations == cap.annotations
    with get_db_connection(db) as conn:
        assert json.loads(conn.execute("SELECT data FROM annotations").fetchone()[0]) == cap.annotations[0]
    repo.create_capture("legacy", {"raw_user_request": "old typed request"})
    bundle = build_capture_bundle("legacy", db)
    assert bundle.metadata["original_voice_transcript"] is None
    assert bundle.metadata["data_provenance"]["original_voice_transcript"] == "not_recorded"
    assert bundle.annotated_path is None
