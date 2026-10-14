"""
Context file and latest-capture mirroring.

Produces two outputs for every capture:

1. ``context.md`` — a Markdown document combining the annotated screenshot
   path, gesture trail, voice transcript, AX/UIA element context, resolved
   anchors, and change request summary.  Cheap for an LLM to read.

2. ``~/.arrow/latest/`` mirror — the annotated screenshot, context.md and a
   manifest.json are written to a fixed path so *any* agent can consume
   them by file path, even without MCP support.

Boundary discipline: this module validates its inputs from the pipeline
result and writes files.  It never reads Qt state or touches the UI.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from arrow.storage.settings import config_dir

LATEST_DIR = os.path.join(os.environ.get("ARROW_HOME") or str(Path.home() / ".arrow"), "latest")


def latest_dir() -> str:
    """Resolve runtime configuration rather than caching a user's home at import."""
    return os.path.join(config_dir(), "latest")


def build_context_md(
    capture_id: str,
    instruction: str,
    source_context: Optional[dict] = None,
    destination_context: Optional[dict] = None,
    ax_tree: Optional[list] = None,
    gesture_trail: Optional[list] = None,
    repository: Optional[dict] = None,
    change_request: Optional[dict] = None,
    annotated_path: Optional[str] = None,
    agent_annotated_path: Optional[str] = None,
) -> str:
    """Build a Markdown context document from pipeline results.

    Each section is only emitted when it has content, keeping the token
    count proportional to actual context.
    """
    lines: list[str] = []
    lines.append(f"# Arrow Capture {capture_id}\n")

    if instruction:
        lines.append("## User Instruction\n")
        lines.append(f"{instruction}\n")

    if annotated_path:
        lines.append("## Annotated Screenshot\n")
        lines.append(f"Path: `{annotated_path}`\n")
    if agent_annotated_path:
        lines.append(f"Agent-optimized: `{agent_annotated_path}`\n")

    if source_context:
        lines.append("## Source Element\n")
        lines.append(_format_context(source_context))

    if destination_context:
        lines.append("## Destination Element\n")
        lines.append(_format_context(destination_context))

    if ax_tree:
        lines.append("## Accessibility Tree\n")
        lines.append("```json")
        lines.append(json.dumps(ax_tree, indent=2, default=str))
        lines.append("```\n")

    if gesture_trail:
        lines.append("## Gesture Trail\n")
        lines.append(f"{len(gesture_trail)} points recorded.\n")
        if len(gesture_trail) > 0:
            first = gesture_trail[0]
            last = gesture_trail[-1]
            lines.append(f"Start: ({first.get('x', 0):.0f}, {first.get('y', 0):.0f})")
            lines.append(f"End: ({last.get('x', 0):.0f}, {last.get('y', 0):.0f})\n")

    if repository:
        lines.append("## Repository Context\n")
        for key in ("repository_root", "current_branch", "framework", "dev_server_url"):
            val = repository.get(key)
            if val:
                lines.append(f"- **{key}**: {val}")
        lines.append("")

    if change_request:
        lines.append("## Change Request Summary\n")
        summary = change_request.get("summary", "")
        intent = change_request.get("normalized_intent", "unknown")
        confidence = change_request.get("confidence", 0.0)
        lines.append(f"- **Intent**: {intent}")
        lines.append(f"- **Confidence**: {confidence:.2f}")
        if summary:
            lines.append(f"- **Summary**: {summary}")

        criteria = change_request.get("acceptance_criteria", [])
        if criteria:
            lines.append("\n### Acceptance Criteria\n")
            for c in criteria:
                lines.append(f"- {c}")

        likely = change_request.get("likely_files", [])
        if likely:
            lines.append("\n### Likely Files\n")
            for f in likely:
                path = f.get("source_file", "") if isinstance(f, dict) else str(f)
                lines.append(f"- `{path}`")
        lines.append("")

    return "\n".join(lines)


def mirror_latest(
    annotated_path: str,
    context_md: str,
    capture_id: str,
    assets: Optional[dict] = None,
) -> str:
    """Write the latest capture to ``~/.arrow/latest/`` for file-path access.

    Returns the directory path.
    """
    directory = latest_dir()
    os.makedirs(directory, exist_ok=True)

    # Copy the annotated screenshot.
    dst_img = os.path.join(directory, "capture.png")
    if os.path.isfile(annotated_path):
        shutil.copy2(annotated_path, dst_img)

    # Write context.md.
    dst_ctx = os.path.join(directory, "context.md")
    with open(dst_ctx, "w", encoding="utf-8") as f:
        f.write(context_md)

    # Write manifest.json.
    manifest: dict[str, Any] = {
        "capture_id": capture_id,
        "capture_path": dst_img,
        "context_path": dst_ctx,
    }
    if assets:
        manifest["assets"] = assets
    dst_manifest = os.path.join(directory, "manifest.json")
    with open(dst_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return directory


def _format_context(ctx: dict) -> str:
    """Format a source/destination context dict as readable Markdown."""
    lines: list[str] = []
    for key in ("source", "tag", "role", "name", "text", "selector",
                "control_type", "automation_id", "window_title",
                "confidence"):
        val = ctx.get(key)
        if val:
            lines.append(f"- **{key}**: {val}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["build_context_md", "mirror_latest", "latest_dir", "LATEST_DIR"]
