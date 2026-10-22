import pytest

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


@pytest.mark.parametrize("instruction", [
    "yah wali chij Mujhe Yahan per chahie",
    "yeh wali cheez mujhe yahaan chahiye",
    "यह वाली चीज मुझे यहाँ चाहिए",
])
def test_spatial_desire_with_selected_source_infers_move_and_requires_destination(instruction):
    req = _compile(
        raw_instruction=instruction,
        annotations=[{"role": "source", "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}}],
    )

    assert req.normalized_intent == Intent.MOVE_ELEMENT
    assert req.raw_user_request == instruction
    assert req.clarification_required is True
    assert req.destination is None
    assert req.source.label == "selected region"
    assert any(a.field == "destination" and a.severity == "blocking" for a in req.ambiguities)
    assert any(i.field == "normalized_intent" for i in req.inferences)
    assert "clarif" in req.summary.lower()
    assert "None" not in req.summary
    assert req.source.element == {}
    assert req.likely_files == []


@pytest.mark.parametrize("instruction", ["isko yahan le aao", "इसे यहाँ ले आओ"])
def test_explicit_hindi_move_requires_destination(instruction):
    req = _compile(raw_instruction=instruction, annotations=[{"role": "source", "label": "button"}])

    assert req.normalized_intent == Intent.MOVE_ELEMENT
    assert req.clarification_required is True
    assert any(a.field == "destination" and a.severity == "blocking" for a in req.ambiguities)


@pytest.mark.parametrize("instruction, expected", [
    ("mujhe blue color chahiye", Intent.RESTYLE_ELEMENT),
    ("add button yahan chahiye", Intent.ADD_ELEMENT),
    ("mujhe yahan chahiye", Intent.UNKNOWN),
    ("yah wali chij chahiye", Intent.UNKNOWN),
])
def test_desire_word_alone_does_not_infer_move(instruction, expected):
    req = _compile(raw_instruction=instruction, annotations=[{"role": "source", "label": "card"}])

    assert req.normalized_intent == expected


def test_generic_source_label_does_not_hide_resolved_element_name():
    req = _compile(
        raw_instruction="move this here",
        annotations=[{"role": "source", "label": "Source"}, {"role": "destination", "label": "Destination"}],
        source_context={"name": "Buy now", "tagName": "BUTTON"},
        destination_context={"text": "Checkout", "tagName": "SECTION"},
    )

    assert req.source.label == "Buy now"
    assert req.destination.label == "Checkout"


def test_markdown_preserves_unknown_instruction_without_duplicate_summary():
    instruction = "please consider this"
    req = _compile(raw_instruction=instruction, annotations=[{"role": "source", "label": "card"}])

    assert build_markdown(req).count(instruction) == 1


def test_markdown_includes_canonical_screenshot_marker_references():
    req = _compile(
        raw_instruction="move this here",
        annotations=[
            {"role": "source", "type": "rectangle", "label": "1 Source",
             "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}},
            {"role": "destination", "type": "rectangle", "label": "2 Destination",
             "geometry": {"x": 200, "y": 20, "width": 80, "height": 30}},
        ],
        source_context={"name": "Buy"},
        destination_context={"name": "Checkout"},
    )

    assert req.source.model_dump().get("screenshot_marker") == "1 Source"
    assert req.destination.model_dump().get("screenshot_marker") == "2 Destination"
    assert req.summary == "Move Buy to Checkout."
    markdown = build_markdown(req)
    assert "1 Source" in markdown
    assert "2 Destination" in markdown


def test_summary_and_acceptance_identify_unresolved_items_by_recorded_marker():
    req = _compile(
        raw_instruction="yah wali chij Mujhe Yahan per chahie",
        annotations=[
            {"role": "source", "type": "rectangle", "label": "1 Source",
             "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}},
            {"role": "destination", "type": "rectangle", "label": "2 Destination",
             "geometry": {"x": 200, "y": 20, "width": 80, "height": 30}},
        ],
    )

    assert req.summary == "Move the item marked 1 Source to the area marked 2 Destination."
    assert any("the item marked 1 Source" in criterion and "the area marked 2 Destination" in criterion
               for criterion in req.acceptance_criteria)
    assert "selected region" not in req.summary


@pytest.mark.parametrize("annotation_type, label", [
    ("freehand", "selected region"),
    ("rectangle", "Current button"),
    ("freehand", "1 Source"),
])
def test_legacy_annotation_geometry_does_not_imply_screenshot_marker(annotation_type, label):
    req = _compile(
        raw_instruction="move this",
        annotations=[{"role": "source", "type": annotation_type, "label": label,
                      "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}}],
    )

    assert req.source.model_dump().get("screenshot_marker") is None
    assert "Marker in annotated screenshot" not in build_markdown(req)


def test_recompile_preserves_screenshot_marker_with_resolved_name():
    from arrow.intent.compiler import recompile_change_request

    old = _compile(
        raw_instruction="move this",
        annotations=[{"role": "source", "type": "rectangle", "label": "1 Source",
                      "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}}],
        source_context={"name": "Buy"},
    )
    edited = recompile_change_request(old.to_dict(), "move this button here")

    assert edited.source.model_dump().get("screenshot_marker") == "1 Source"
    assert edited.source.label == "Buy"
    assert "1 Source" in build_markdown(edited)


def test_context_name_matching_marker_does_not_claim_a_screenshot_marker():
    req = _compile(raw_instruction="inspect this", source_context={"name": "1 Source"})

    assert req.source.label == "1 Source"
    assert req.source.screenshot_marker is None
    assert "Marker in annotated screenshot" not in build_markdown(req)


def test_recompile_does_not_upgrade_canonical_label_to_marker_evidence():
    from arrow.intent.compiler import recompile_change_request

    edited = recompile_change_request({
        "source": {"label": "1 Source", "element": {"name": "1 Source"},
                   "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}},
    }, "inspect this")

    assert edited.source.label == "1 Source"
    assert edited.source.screenshot_marker is None
    assert "Marker in annotated screenshot" not in build_markdown(edited)


def test_empty_semantic_rectangle_does_not_record_screenshot_marker():
    req = _compile(
        raw_instruction="inspect this",
        annotations=[{"role": "source", "type": "rectangle", "label": "1 Source", "geometry": {}}],
    )

    assert req.source.screenshot_marker is None


def test_markdown_does_not_claim_markers_for_context_only_anchors():
    req = _compile(
        raw_instruction="move this here",
        source_context={"name": "Buy"},
        destination_context={"name": "Checkout"},
    )

    markdown = build_markdown(req)
    assert "1 Source" not in markdown
    assert "2 Destination" not in markdown


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
