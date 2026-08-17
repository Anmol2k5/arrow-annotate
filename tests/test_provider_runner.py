"""Tests for one-click provider run orchestration (arrow.providers.runner)."""

import pytest

from arrow.providers.base import (
    Provider,
    ProviderEvent,
    ProviderStatus,
    ValidationResult,
)
from arrow.providers.claude import ClaudeProvider
from arrow.providers.codex import CodexProvider
from arrow.providers.runner import (
    build_run_request,
    create_provider,
    run_provider_sync,
)


class FakeProvider(Provider):
    name = "Fake"

    def __init__(self, events=None, fail_start=False):
        self._events = events or []
        self._fail_start = fail_start

    def detect(self) -> bool:
        return True

    def validate(self, repository_path: str) -> ValidationResult:
        return ValidationResult(ok=True)

    def start_run(self, request) -> None:
        if self._fail_start:
            raise RuntimeError("boom")

    def stream_events(self):
        for e in self._events:
            yield e

    def cancel_run(self) -> None:
        pass

    def get_status(self) -> ProviderStatus:
        return ProviderStatus.RUNNING


def change_request_with_repo(repo="/repo") -> dict:
    return {
        "capture_id": "cap-1",
        "project": {"repository_root": repo},
        "assets": {"annotated": "/repo/annotated.png"},
        "normalized_intent": "move_element",
    }


def test_build_run_request_from_change_request():
    req = build_run_request("cap-1", change_request_with_repo(), "Move it")
    assert req is not None
    assert req.capture_id == "cap-1"
    assert req.repository_path == "/repo"
    assert req.prompt == "Move it"
    assert req.assets == {"annotated": "/repo/annotated.png"}


def test_build_run_request_requires_repository():
    assert build_run_request("cap-1", {"project": {}}, "Move it") is None
    assert build_run_request("cap-1", {}, "Move it") is None


def test_build_run_request_falls_back_to_current_repo(tmp_path):
    # Older captures have no repo attached; the currently selected repo is used.
    cr = {"capture_id": "cap-1", "project": {}, "assets": {}}
    req = build_run_request("cap-1", cr, "Move it", fallback_repo=str(tmp_path))
    assert req is not None
    assert req.repository_path == str(tmp_path)


def test_build_run_request_ignores_invalid_fallback(tmp_path):
    cr = {"capture_id": "cap-1", "project": {}, "assets": {}}
    assert build_run_request("cap-1", cr, "Move it",
                             fallback_repo=str(tmp_path / "nope")) is None


def test_build_run_request_capture_repo_wins_over_fallback(tmp_path):
    cr = {"capture_id": "cap-1", "project": {"repository_root": "/repo"}, "assets": {}}
    req = build_run_request("cap-1", cr, "Move it", fallback_repo=str(tmp_path))
    assert req.repository_path == "/repo"


def test_create_provider_names():
    assert isinstance(create_provider("Codex"), CodexProvider)
    assert isinstance(create_provider("Claude Code"), ClaudeProvider)
    with pytest.raises(ValueError):
        create_provider("Nope")


def test_run_provider_sync_returns_last_event():
    provider = FakeProvider(events=[
        ProviderEvent(type="status", message="Sending context"),
        ProviderEvent(type="log", message="editing file"),
        ProviderEvent(type="done", message="Completed"),
    ])
    req = build_run_request("cap-1", change_request_with_repo(), "Move it")
    final = run_provider_sync(provider, req)
    assert final.type == "done"
    assert final.message == "Completed"


def test_run_provider_sync_never_raises_on_failure():
    provider = FakeProvider(fail_start=True)
    req = build_run_request("cap-1", change_request_with_repo(), "Move it")
    final = run_provider_sync(provider, req)
    assert final.type == "error"
    assert "boom" in final.message
