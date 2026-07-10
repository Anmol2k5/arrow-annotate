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
