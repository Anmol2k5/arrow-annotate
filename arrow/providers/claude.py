"""
Claude Code provider adapter (Phase 13).

Prefers the Claude Code CLI in non-interactive (`-p`) mode, confined to the
selected repository. A programmatic Agent-SDK integration can be layered on the
same interface later. Permission modes are respected and cancellation is
supported. Authentication tokens are never read or stored.
"""

from __future__ import annotations

import os

from arrow.providers.base import BaseCLIProvider, RunRequest


class ClaudeProvider(BaseCLIProvider):
    name = "Claude Code"
    cli_name = "claude"

    def __init__(self, *args, permission_mode: str = "default", **kwargs):
        super().__init__(*args, **kwargs)
        self.permission_mode = permission_mode

    def build_command(self, request: RunRequest) -> list[str]:
        prompt = request.prompt
        annotated = request.assets.get("annotated")
        if annotated and os.path.isfile(annotated):
            prompt += f"\n\nAnnotated screenshot: {annotated}"
        # `claude -p` runs a one-shot (print) request non-interactively.
        return [
            self.cli_name,
            "-p",
            "--permission-mode", self.permission_mode,
            "--",
            prompt,
        ]


__all__ = ["ClaudeProvider"]
