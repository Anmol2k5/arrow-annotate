"""
Claude Code provider adapter (Phase 13).

Prefers the Claude Code CLI in non-interactive (`-p`) mode, confined to the
selected repository. A programmatic Agent-SDK integration can be layered on the
same interface later. Permission modes are respected and cancellation is
supported. Authentication tokens are never read or stored.
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

from PIL import Image

from arrow.providers.base import BaseCLIProvider, RunRequest


class ClaudeProvider(BaseCLIProvider):
    name = "Claude Code"
    cli_name = "claude"
    npm_package = "@anthropic-ai/claude-code"

    def __init__(self, *args, permission_mode: str = "default", **kwargs):
        super().__init__(*args, **kwargs)
        self.permission_mode = permission_mode

    def build_command(self, request: RunRequest) -> list[str]:
        # Claude's Agent SDK uses stream-json input for multimodal user messages.
        # Verbose output is required with print mode's stream-json output.
        return [
            self.cli_name,
            "-p",
            "--permission-mode", self.permission_mode,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
        ]

    def build_stdin(self, request: RunRequest) -> str:
        content = [{"type": "text", "text": request.prompt}]
        for key in ("agent-annotated", "annotated"):
            annotated = request.assets.get(key)
            if not annotated or not os.path.isfile(annotated):
                continue
            data = Path(annotated).read_bytes()
            with Image.open(io.BytesIO(data)) as image:
                media_type = Image.MIME.get(image.format)
            if media_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                raise ValueError("Claude image attachments must be PNG, JPEG, GIF, or WebP")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            })
            break
        return json.dumps({
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
            "session_id": "default",
        }) + "\n"


__all__ = ["ClaudeProvider"]
