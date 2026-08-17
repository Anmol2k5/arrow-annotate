"""Tests for edit-context recompile (edited instruction → new change request)."""

from arrow.intent.compiler import recompile_change_request
from arrow.intent.schemas import Intent
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord

OLD_CR = {
    "capture_id": "cap-1",
    "application_mode": "web",
    "project": {"repository_root": "/repo"},
    "raw_user_request": "Move this button here.",
    "normalized_intent": "move_element",
    "source": {
        "label": "Current element",
        "coordinate_space": "virtual_screen",
        "geometry": {"x": 10, "y": 20, "width": 30, "height": 40},
        "element": {
            "name": "Get started",
            "source": "browser_dom",
            "confidence": 0.9,
            "selector": "button#cta",
        },
        "source_mapping": {
            "resolved": True,
            "source_file": "src/Buy.tsx",
            "source_line": 12,
            "confidence": 0.8,
        },
        "resolution_confidence": 0.9,
        "resolution_source": "browser_dom",
    },
    "destination": {
        "label": "Move here",
        "coordinate_space": "virtual_screen",
        "geometry": {"x": 300, "y": 20, "width": 30, "height": 40},
        "element": {"name": "Here", "source": "browser_dom", "confidence": 0.9},
        "source_mapping": {},
        "resolution_confidence": 0.9,
        "resolution_source": "browser_dom",
    },
    "assets": {"annotated": "/repo/annotated.png"},
}


def test_recompile_preserves_anchors_and_project():
    new = recompile_change_request(OLD_CR, "Move this button here.")
    assert new is not None
    assert new.capture_id == "cap-1"
    assert new.project["repository_root"] == "/repo"
    assert new.normalized_intent == Intent.MOVE_ELEMENT
    assert new.raw_user_request == "Move this button here."

    # Anchors, element context and source mapping survive the recompile.
    assert new.source.label == "Current element"
    assert new.source.element["name"] == "Get started"
    assert new.source.source_mapping["source_file"] == "src/Buy.tsx"
    assert new.source.resolution_source == "browser_dom"
    assert new.destination is not None
    assert new.destination.label == "Move here"


def test_recompile_changes_intent_with_new_instruction():
    # With a destination anchor the intent stays move; use a source-only
    # request to observe the intent actually changing.
    src_only = {k: v for k, v in OLD_CR.items() if k != "destination"}

    moved = recompile_change_request(src_only, "Move this button here.")
    assert moved.normalized_intent == Intent.MOVE_ELEMENT

    resized = recompile_change_request(src_only, "Make this button slightly wider.")
    assert resized.normalized_intent == Intent.RESIZE_ELEMENT
    assert any(c.operation == "resize" for c in resized.requested_changes)


def test_recompile_with_destination_keeps_move_intent():
    # Design: a destination anchor always implies a move, so a resize-only
    # instruction still produces the resize change on top of the move.
    new = recompile_change_request(OLD_CR, "Make this button slightly wider.")
    assert new.normalized_intent == Intent.MOVE_ELEMENT
    assert any(c.operation == "resize" for c in new.requested_changes)


def test_recompile_empty_returns_none():
    assert recompile_change_request({}, "x") is None
    assert recompile_change_request(None, "x") is None


def test_recompile_is_deterministic():
    a = recompile_change_request(OLD_CR, "Move this button here and keep the mobile layout.")
    b = recompile_change_request(OLD_CR, "Move this button here and keep the mobile layout.")
    assert a.to_dict() == b.to_dict()


def test_update_change_request_round_trip(tmp_path):
    store = CaptureStore(db_path=str(tmp_path / "t.db"))
    store.add(CaptureRecord(
        id="cap-1",
        timestamp="2026-01-01T00:00:00",
        screenshot_path="/s/a.png",
        annotation_text="old text",
    ))

    store.update_change_request(
        "cap-1", {"normalized_intent": "resize_element"}, annotation_text="new text"
    )
    got = store.get("cap-1")
    assert got.change_request["normalized_intent"] == "resize_element"
    assert got.annotation_text == "new text"

    # Clearing the request back to None is allowed.
    store.update_change_request("cap-1", None)
    assert store.get("cap-1").change_request is None


def test_update_change_request_missing_capture_is_noop(tmp_path):
    store = CaptureStore(db_path=str(tmp_path / "t.db"))
    store.update_change_request("does-not-exist", {"x": 1})  # must not raise
