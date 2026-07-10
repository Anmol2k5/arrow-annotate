"""
Notch status and preview model (Phase 11).

The notch must only display state backed by the real application. This module
provides the framework-agnostic data the notch renders, so there are no fake
integrations, fake agent tasks or hardcoded activity. The PyQt notch consumes
these plain models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    READY = "Ready"
    SENDING_CONTEXT = "Sending context"
    AGENT_READING = "Agent reading request"
    EDITING_FILES = "Editing files"
    RUNNING_TESTS = "Running tests"
    WAITING_PERMISSION = "Waiting for permission"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class NotchAction(str, Enum):
    EDIT_CONTEXT = "edit_context"
    UNDO_ANNOTATION = "undo_annotation"
    REDO_ANNOTATION = "redo_annotation"
    RETAKE_SCREENSHOT = "retake_screenshot"
    SEND = "send"
    COPY_FALLBACK = "copy_fallback"
    CANCEL = "cancel"
    DELETE = "delete"
    OPEN_PROJECT = "open_project"


class ProviderOption(str, Enum):
    CODEX = "Codex"
    CLAUDE_CODE = "Claude Code"
    AGENTATION = "Agentation"
    COPY_ONLY = "Copy only"


class SystemStatus(BaseModel):
    """Real, observed application state shown in the notch header."""

    browser_extension: bool = False
    mcp_server: bool = False
    codex_installed: bool = False
    claude_installed: bool = False
    selected_repository: Optional[str] = None
    current_branch: Optional[str] = None
    dev_server: Optional[str] = None
    active_capture: Optional[str] = None
    selected_provider: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump()


class CapturePreview(BaseModel):
    """Preview card content for a single capture — all values come from stored data."""

    capture_id: Optional[str] = None
    annotated_screenshot: Optional[str] = None
    raw_screenshot: Optional[str] = None
    raw_instruction: str = ""
    interpreted_intent: str = ""
    summary: str = ""
    source_element: Optional[str] = None
    destination: Optional[str] = None
    confidence: float = 0.0
    repository: Optional[str] = None
    likely_file: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    selected_provider: Optional[str] = None
    clarification_required: bool = False

    def to_dict(self) -> dict:
        return self.model_dump()


def _safe_call(fn: Optional[Callable[[], Any]], default: Any = None) -> Any:
    if fn is None:
        return default
    try:
        return fn()
    except Exception:
        return default


class StatusProvider:
    """Assembles :class:`SystemStatus` from injected real-state sources.

    Every source is optional; a missing source simply yields ``False``/``None``
    rather than fabricated activity.
    """

    def __init__(
        self,
        ws_bridge: Any = None,
        mcp_running: Optional[Callable[[], bool]] = None,
        codex_detect: Optional[Callable[[], bool]] = None,
        claude_detect: Optional[Callable[[], bool]] = None,
        repo_context: Optional[Callable[[], Any]] = None,
        active_capture: Optional[Callable[[], Optional[str]]] = None,
        selected_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        self._ws_bridge = ws_bridge
        self._mcp_running = mcp_running
        self._codex_detect = codex_detect
        self._claude_detect = claude_detect
        self._repo_context = repo_context
        self._active_capture = active_capture
        self._selected_provider = selected_provider

    def snapshot(self) -> SystemStatus:
        repo = _safe_call(self._repo_context)
        repo_root = None
        branch = None
        dev_server = None
        if repo is not None:
            repo_root = getattr(repo, "repository_root", None) if not isinstance(repo, dict) else repo.get("repository_root")
            branch = getattr(repo, "current_branch", None) if not isinstance(repo, dict) else repo.get("current_branch")
            dev_server = getattr(repo, "dev_server_url", None) if not isinstance(repo, dict) else repo.get("dev_server_url")

        return SystemStatus(
            browser_extension=bool(getattr(self._ws_bridge, "connected", False)) if self._ws_bridge else False,
            mcp_server=bool(_safe_call(self._mcp_running, False)),
            codex_installed=bool(_safe_call(self._codex_detect, False)),
            claude_installed=bool(_safe_call(self._claude_detect, False)),
            selected_repository=repo_root,
            current_branch=branch,
            dev_server=dev_server,
            active_capture=_safe_call(self._active_capture),
            selected_provider=_safe_call(self._selected_provider),
        )


def build_capture_preview(capture: dict, selected_provider: Optional[str] = None) -> CapturePreview:
    """Build a preview card from a stored capture record (see Repository.get_capture)."""
    cr = capture.get("change_request", {}) or {}
    assets = capture.get("assets", {}) or {}

    source = cr.get("source") or {}
    destination = cr.get("destination") or {}
    likely_files = cr.get("likely_files") or []
    likely_file = None
    if likely_files:
        first = likely_files[0]
        likely_file = first.get("source_file")
        if first.get("source_line"):
            likely_file = f"{likely_file}:{first['source_line']}"

    return CapturePreview(
        capture_id=capture.get("capture_id"),
        annotated_screenshot=assets.get("annotated"),
        raw_screenshot=assets.get("raw"),
        raw_instruction=cr.get("raw_user_request", ""),
        interpreted_intent=cr.get("normalized_intent", ""),
        summary=cr.get("summary", ""),
        source_element=source.get("label"),
        destination=destination.get("label"),
        confidence=cr.get("confidence", 0.0),
        repository=(cr.get("project") or {}).get("repository_root"),
        likely_file=likely_file,
        constraints=cr.get("constraints", []),
        acceptance_criteria=cr.get("acceptance_criteria", []),
        selected_provider=selected_provider or capture.get("status"),
        clarification_required=bool(cr.get("clarification_required")),
    )


__all__ = [
    "RunStatus",
    "NotchAction",
    "ProviderOption",
    "SystemStatus",
    "CapturePreview",
    "StatusProvider",
    "build_capture_preview",
]
