"""
Codex CLI provider adapter (Phase 13).

Detects the installed Codex CLI and runs it inside the selected repository,
passing the structured request as the prompt. Streams progress to the notch and
supports cancellation. Authentication tokens are never read or stored.
"""

from __future__ import annotations

import os

from arrow.providers.base import BaseCLIProvider, RunRequest


class CodexProvider(BaseCLIProvider):
    name = "Codex"
    cli_name = "codex"

    def build_command(self, request: RunRequest) -> list[str]:
        # `codex exec` runs a non-interactive task with a prompt.
        # The prompt embeds the change request; assets are referenced by path so
        # Codex can open them from within the repository sandbox.
        prompt = request.prompt
        annotated = request.assets.get("annotated")
        if annotated and os.path.isfile(annotated):
            prompt += f"\n\nAnnotated screenshot: {annotated}"
        return [self.cli_name, "exec", "--cd", request.repository_path, prompt]


__all__ = ["CodexProvider"]
