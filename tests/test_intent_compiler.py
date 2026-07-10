from arrow.intent import (
    ChangeRequest,
    CompilerInput,
    Intent,
    IntentCompiler,
    MoveRelationship,
    build_markdown,
)


def _compile(**kwargs) -> ChangeRequest:
    return IntentCompiler().compile(CompilerInput(**kwargs))


def test_move_and_resize_full_flow():
    req = _compile(
        capture_id="cap1",
        application_mode="web",
        raw_instruction="Move this button here, make it slightly wider, and preserve the mobile layout.",
        annotations=[
            {"role": "source", "label": "Current button",
             "geometry": {"x": 100, "y": 100, "width": 80, "height": 30}},
            {"role": "destination", "label": "Move here",
             "geometry": {"x": 400, "y": 100, "width": 80, "height": 30}},
        ],
        source_mapping={"resolved": True, "source_file": "src/Button.tsx",
                        "source_line": 12, "component": "Button", "confidence": 0.9,
                        "evidence": ["arrow-id"]},
    )
    assert req.normalized_intent == Intent.MOVE_ELEMENT
    assert req.source.label == "Current button"
    assert req.destination.label == "Move here"
    assert any(c.operation == "move" for c in req.requested_changes)
    resize = [c for c in req.requested_changes if c.operation == "resize"]
    assert resize and resize[0].details["dimension"] == "width"
    assert resize[0].details["direction"] == "increase"
    assert resize[0].details.get("magnitude") == "slight"
    # destination is to the right of source
    assert req.move_relationship == MoveRelationship.RIGHT_OF
    assert any("mobile" in e.lower() for e in req.responsive_expectations)
    assert req.likely_files and req.likely_files[0].source_file == "src/Button.tsx"
    assert req.clarification_required is False


def test_move_without_destination_requires_clarification():
    req = _compile(
        raw_instruction="move this button",
        annotations=[{"role": "source", "label": "btn"}],
    )
    assert req.normalized_intent == Intent.MOVE_ELEMENT
    assert req.clarification_required is True
    assert any(a.field == "destination" and a.severity == "blocking" for a in req.ambiguities)


def test_explicit_relationship_keyword_priority():
    req = _compile(
        raw_instruction="move this before the header",
        annotations=[
            {"role": "source", "label": "a", "geometry": {"x": 400, "y": 100, "width": 10, "height": 10}},
            {"role": "destination", "label": "b", "geometry": {"x": 0, "y": 100, "width": 10, "height": 10}},
        ],
    )
    # keyword "before" overrides geometry (which would say left_of)
    assert req.move_relationship == MoveRelationship.BEFORE
    assert not any(inf.field == "move_relationship" for inf in req.inferences)


def test_geometry_relationship_is_marked_inference():
    req = _compile(
        raw_instruction="move it",
        annotations=[
            {"role": "source", "label": "a", "geometry": {"x": 100, "y": 100, "width": 10, "height": 10}},
            {"role": "destination", "label": "b", "geometry": {"x": 100, "y": 400, "width": 10, "height": 10}},
        ],
    )
    assert req.move_relationship == MoveRelationship.BELOW
    assert any(inf.field == "move_relationship" for inf in req.inferences)


def test_restyle_intent():
    req = _compile(
        raw_instruction="change the background color to blue",
        annotations=[{"role": "source", "label": "card"}],
    )
    assert req.normalized_intent == Intent.RESTYLE_ELEMENT
    assert any(c.operation == "restyle" for c in req.requested_changes)


def test_remove_intent():
    req = _compile(raw_instruction="remove this banner",
                   annotations=[{"role": "source", "label": "banner"}])
    assert req.normalized_intent == Intent.REMOVE_ELEMENT


def test_inspect_intent():
    req = _compile(raw_instruction="explain what this component does",
                   annotations=[{"role": "source", "label": "widget"}])
    assert req.normalized_intent == Intent.INSPECT_OR_EXPLAIN


def test_unknown_intent_blocks():
    req = _compile(raw_instruction="asdf qwerty",
                   annotations=[{"role": "source", "label": "x"}])
    assert req.normalized_intent == Intent.UNKNOWN
    assert req.clarification_required is True


def test_no_source_is_blocking():
    req = _compile(raw_instruction="make it wider")
    assert any(a.field == "source" and a.severity == "blocking" for a in req.ambiguities)
    assert req.clarification_required is True


def test_default_responsive_preserved_is_inference():
    req = _compile(raw_instruction="make it wider",
                   annotations=[{"role": "source", "label": "x"}])
    assert any("responsive" in e.lower() for e in req.responsive_expectations)
    assert any(inf.field == "responsive_expectations" for inf in req.inferences)


def test_constraints_forbid_pixel_css():
    req = _compile(raw_instruction="move this here",
                   annotations=[
                       {"role": "source", "label": "a"},
                       {"role": "destination", "label": "b"},
                   ])
    assert any("hardcoded CSS" in c for c in req.constraints)


def test_candidates_become_likely_files():
    req = _compile(
        raw_instruction="restyle this",
        annotations=[{"role": "source", "label": "x"}],
        source_mapping={"resolved": False, "candidates": [
            {"source_file": "src/A.tsx", "confidence": 0.6},
            {"source_file": "src/B.tsx", "confidence": 0.5},
        ]},
    )
    files = [f.source_file for f in req.likely_files]
    assert "src/A.tsx" in files and "src/B.tsx" in files
    assert req.likely_files[0].source_file == "src/A.tsx"  # sorted by confidence


def test_to_dict_is_json_serializable():
    req = _compile(raw_instruction="move this here",
                   annotations=[
                       {"role": "source", "label": "a"},
                       {"role": "destination", "label": "b"},
                   ])
    d = req.to_dict()
    assert d["schema_version"] == 1
    assert d["normalized_intent"] == "move_element"
    import json
    json.dumps(d)  # must not raise


def test_build_markdown_smoke():
    req = _compile(
        raw_instruction="Move this button here and make it wider",
        annotations=[
            {"role": "source", "label": "Buy", "geometry": {"x": 0, "y": 0, "width": 10, "height": 10}},
            {"role": "destination", "label": "Here", "geometry": {"x": 100, "y": 0, "width": 10, "height": 10}},
        ],
        source_mapping={"resolved": True, "source_file": "src/Buy.tsx", "source_line": 3,
                        "confidence": 0.8, "component": "Buy"},
    )
    md = build_markdown(req)
    assert "# Arrow change request" in md
    assert "Acceptance criteria" in md
    assert "src/Buy.tsx" in md
    assert "Move here".lower() in md.lower() or "Here" in md
