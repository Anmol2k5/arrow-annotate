"""
Provider run orchestration for one-click sends (Phase 13 convenience).

Turns a persisted ``change_request`` (from the orchestrator) into a
:class:`RunRequest` for a direct Codex / Claude Code run. Runs are confined to
the repository recorded in the change request; sensitive actions are denied by
default by the shared provider plumbing.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from arrow.providers.base import Provider, ProviderEvent, RunRequest
from arrow.providers.claude import ClaudeProvider
from arrow.providers.codex import CodexProvider

log = logging.getLogger("arrow.providers.runner")


def build_run_request(
    capture_id: str,
    change_request: dict,
    prompt: str,
    fallback_repo: Optional[str] = None,
) -> Optional[RunRequest]:
    """Build a RunRequest from a compiled change request.

    The repository attached to the capture wins; when the capture has none (e.g.
    an older record), the currently selected repository is used as a fallback.
    Returns ``None`` when still no repository is available — the agent must know
    where to work, and we never guess.
    """
    if not change_request:
        return None
    repo = (change_request.get("project") or {}).get("repository_root")
    if not repo and fallback_repo and os.path.isdir(fallback_repo):
        repo = fallback_repo
    if not repo:
        return None
    return RunRequest(
        capture_id=capture_id,
        repository_path=repo,
        prompt=prompt,
        assets=change_request.get("assets") or {},
    )


def create_provider(name: str) -> Provider:
    """Instantiate a direct-execution provider by name."""
    if name == "Codex":
        return CodexProvider()
    if name == "Claude Code":
        return ClaudeProvider()
    raise ValueError(f"Unknown provider: {name}")


def run_provider_sync(provider: Provider, request: RunRequest) -> ProviderEvent:
    """Run a provider to completion on the current thread.

    Never raises: the final event (``done`` / ``error``) is returned so the
    caller can surface a result. Designed to be called from a background thread.
    """
    final = ProviderEvent(type="status", message="Starting")
    try:
        provider.start_run(request)
        for ev in provider.stream_events():
            final = ev
    except Exception as e:  # noqa: BLE001 - surface provider failures as events
        log.exception("Provider run failed for capture %s", request.capture_id)
        final = ProviderEvent(type="error", message=str(e))
    return final


__all__ = ["build_run_request", "create_provider", "run_provider_sync"]
