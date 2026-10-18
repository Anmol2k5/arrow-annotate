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
    npm_package = "@openai/codex"

    def build_command(self, request: RunRequest) -> list[str]:
        # `codex exec` runs a non-interactive task with a prompt.
        command = [self.cli_name, "exec", "--sandbox", "workspace-write", "--cd", request.repository_path]
        for key in ("agent-annotated", "annotated"):
            annotated = request.assets.get(key)
            if annotated and os.path.isfile(annotated):
                command.extend(["--image", annotated])
                break
        return [*command, "--", request.prompt]


__all__ = ["CodexProvider"]
