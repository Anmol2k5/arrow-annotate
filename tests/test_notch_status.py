from arrow.ui.status import (
    CapturePreview,
    ProviderOption,
    RunStatus,
    StatusProvider,
    SystemStatus,
    build_capture_preview,
)


class FakeBridge:
    def __init__(self, connected):
        self.connected = connected


def test_status_snapshot_all_real():
    provider = StatusProvider(
        ws_bridge=FakeBridge(True),
        mcp_running=lambda: True,
        codex_detect=lambda: True,
        claude_detect=lambda: False,
        repo_context=lambda: {"repository_root": "/repo", "current_branch": "main",
                              "dev_server_url": "http://localhost:3000"},
        active_capture=lambda: "cap1",
        selected_provider=lambda: "Codex",
    )
    s = provider.snapshot()
    assert s.browser_extension is True
    assert s.mcp_server is True
    assert s.codex_installed is True
    assert s.claude_installed is False
    assert s.selected_repository == "/repo"
    assert s.current_branch == "main"
    assert s.dev_server == "http://localhost:3000"
    assert s.active_capture == "cap1"
    assert s.selected_provider == "Codex"


def test_status_snapshot_defaults_no_fakes():
    provider = StatusProvider()
    s = provider.snapshot()
    assert s == SystemStatus()
    assert s.browser_extension is False
    assert s.selected_repository is None


def test_status_snapshot_survives_source_errors():
    def boom():
        raise RuntimeError("nope")

    provider = StatusProvider(mcp_running=boom, codex_detect=boom, repo_context=boom)
    s = provider.snapshot()
    assert s.mcp_server is False
    assert s.codex_installed is False
    assert s.selected_repository is None


def test_build_capture_preview():
    capture = {
        "capture_id": "cap1",
        "status": "ready",
        "assets": {"annotated": "/a/annotated.png", "raw": "/a/raw.png"},
        "change_request": {
            "raw_user_request": "Move this button here",
            "normalized_intent": "move_element",
            "summary": "Move Buy to Here",
            "source": {"label": "Buy"},
            "destination": {"label": "Here"},
            "confidence": 0.82,
            "project": {"repository_root": "/repo"},
            "likely_files": [{"source_file": "src/Buy.tsx", "source_line": 12}],
            "constraints": ["Prefer normal flow"],
            "acceptance_criteria": ["Buy appears at Here"],
            "clarification_required": False,
        },
    }
    p = build_capture_preview(capture, selected_provider="Codex")
    assert p.capture_id == "cap1"
    assert p.annotated_screenshot == "/a/annotated.png"
    assert p.raw_instruction == "Move this button here"
    assert p.interpreted_intent == "move_element"
    assert p.source_element == "Buy"
    assert p.destination == "Here"
    assert p.confidence == 0.82
    assert p.repository == "/repo"
    assert p.likely_file == "src/Buy.tsx:12"
    assert p.selected_provider == "Codex"


def test_build_preview_empty_capture():
    p = build_capture_preview({})
    assert isinstance(p, CapturePreview)
    assert p.raw_instruction == ""
    assert p.likely_file is None


def test_enums_present():
    assert RunStatus.WAITING_PERMISSION.value == "Waiting for permission"
    assert ProviderOption.COPY_ONLY.value == "Copy only"


def test_format_change_request_renders_paste_ready_prompt():
    from arrow.ui.notch import format_change_request

    cr = {
        "normalized_intent": "move_element",
        "summary": "Move Buy to Here.",
        "raw_user_request": "Move this button here and make it wider",
        "source": {"label": "Buy", "element": {"name": "Buy"}},
        "destination": {"label": "Here", "element": {"name": "Here"}},
        "confidence": 0.82,
        "likely_files": [{"source_file": "src/components/Buy.tsx", "source_line": 12}],
        "requested_changes": [{"description": "Move the source element to the destination location."}],
        "acceptance_criteria": ["Buy appears at Here."],
        "constraints": ["Prefer normal layout flow."],
    }
    text = format_change_request(cr)
    assert "**Intent:** Move element" in text
    assert "**Instruction:** Move this button here and make it wider" in text
    assert "**Source:** Buy" in text
    assert "**Destination:** Here" in text
    assert "**Confidence:** 0.82" in text
    assert "**Likely file:** src/components/Buy.tsx:12" in text
    assert "Buy appears at Here." in text
    assert "Prefer normal layout flow." in text


def test_format_change_request_empty():
    from arrow.ui.notch import format_change_request

    assert format_change_request({}) == ""
    assert format_change_request(None) == ""


def test_legacy_generic_anchor_labels_prefer_resolved_element_names():
    from arrow.ui.notch import format_change_request

    text = format_change_request({
        "normalized_intent": "move_element",
        "source": {"label": "Current element", "element": {"name": "Buy"}},
        "destination": {"label": "Move here", "element": {"text": "Checkout"}},
    })

    assert "**Source:** Buy" in text
    assert "**Destination:** Checkout" in text


def test_format_change_request_exposes_missing_destination_and_inferences():
    from arrow.intent import CompilerInput, IntentCompiler
    from arrow.ui.notch import format_change_request

    instruction = "yah wali chij Mujhe Yahan per chahie"
    cr = IntentCompiler().compile(CompilerInput(
        raw_instruction=instruction,
        annotations=[{"role": "source", "type": "rectangle", "label": "1 Source",
                      "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}}],
    )).to_dict()

    text = format_change_request(cr)

    assert "**Intent:** Move element" in text
    assert f"**Instruction:** {instruction}" in text
    assert "1 Source" in text
    assert "2 Destination" not in text
    assert "**Destination:**" in text
    assert "not provided" in text.lower()
    assert "**Clarification required:** Yes" in text
    assert "before implementation" in text.lower()
    assert "**Ambiguities:**" in text
    assert "[blocking] destination" in text
    assert "**Inferences (not confirmed facts):**" in text
    assert "No repository file" in text


def test_format_change_request_uses_canonical_markers_with_resolved_names():
    from arrow.ui.notch import format_change_request

    text = format_change_request({
        "normalized_intent": "move_element",
        "source": {"label": "1 Source", "screenshot_marker": "1 Source", "element": {"name": "Buy"},
                   "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}},
        "destination": {"label": "2 Destination", "screenshot_marker": "2 Destination", "element": {"text": "Checkout"},
                        "geometry": {"x": 200, "y": 20, "width": 80, "height": 30}},
        "clarification_required": False,
    })

    assert "**Source:** Buy" in text
    assert "**Destination:** Checkout" in text
    assert "1 Source" in text
    assert "2 Destination" in text
    assert "**Clarification required:** No" in text


def test_format_change_request_does_not_claim_markers_for_context_only_anchors():
    from arrow.ui.notch import format_change_request

    text = format_change_request({
        "normalized_intent": "move_element",
        "source": {"element": {"name": "Buy"}},
        "destination": {"element": {"text": "Checkout"}},
    })

    assert "1 Source" not in text
    assert "2 Destination" not in text


def test_format_change_request_does_not_claim_markers_for_legacy_geometry():
    from arrow.ui.notch import format_change_request

    text = format_change_request({
        "normalized_intent": "move_element",
        "source": {"label": "Current button", "geometry": {"x": 10, "y": 20, "width": 80, "height": 30}},
        "destination": {"label": "Here", "geometry": {"x": 200, "y": 20, "width": 80, "height": 30}},
    })

    assert "1 Source" not in text
    assert "2 Destination" not in text


def test_format_change_request_preserves_recorded_markers_with_resolved_labels():
    from arrow.ui.notch import format_change_request

    text = format_change_request({
        "normalized_intent": "move_element",
        "source": {"label": "Buy", "screenshot_marker": "1 Source"},
        "destination": {"label": "Checkout", "screenshot_marker": "2 Destination"},
    })

    assert "**Source:** Buy" in text
    assert "**Destination:** Checkout" in text
    assert "1 Source" in text
    assert "2 Destination" in text


def test_format_change_request_does_not_treat_resolved_marker_name_as_marker_evidence():
    from arrow.intent import CompilerInput, IntentCompiler
    from arrow.ui.notch import format_change_request

    req = IntentCompiler().compile(CompilerInput(raw_instruction="inspect this", source_context={"name": "1 Source"}))
    text = format_change_request(req.to_dict())

    assert "**Source:** 1 Source" in text
    assert "marker in annotated screenshot" not in text.lower()


def test_format_change_request_preserves_instruction_without_duplicate_summary():
    from arrow.ui.notch import format_change_request

    instruction = "please consider this"
    text = format_change_request({
        "normalized_intent": "unknown",
        "summary": instruction,
        "raw_user_request": instruction,
    })

    assert text.count(instruction) == 1
    assert f"**Instruction:** {instruction}" in text
