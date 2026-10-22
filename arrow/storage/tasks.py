"""TaskBundle: several captures that answer one instruction.

A task is the unit an agent is asked about. It owns an ordered list of
captures and an instruction, and exports a stable manifest plus human-readable
Markdown.

Design rules that the rest of the app depends on:

* A capture may belong to **at most one** task, so deleting a task can never
  orphan or double-free an asset. Assets stay owned by the capture.
* Captures predating tasks remain valid and remain listable; task_id is
  nullable and nothing rewrites existing rows.
* The manifest only states what capture evidence actually supports. When the
  target was not identified the resolution method is ``fallback`` and no
  element identity is invented.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger("arrow.storage.tasks")

SCHEMA_VERSION = 1
COORDINATE_SPACE = "virtual_desktop"


class TaskStatus(str, Enum):
    """Lifecycle. Context availability is deliberately distinct from execution.

    ``DRAFT`` -> user is still composing. ``READY`` -> context exists locally.
    ``SENT`` / ``RUNNING`` / ``COMPLETED`` / ``FAILED`` require evidence that an
    agent actually engaged; never infer them from a file existing.
    """

    DRAFT = "draft"
    READY = "ready"
    HANDOFF_REQUESTED = "handoff_requested"
    SENT = "sent"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_task_id() -> str:
    from arrow.capture.session import generate_uuidv7

    return f"task_{generate_uuidv7()}"


@dataclass
class CaptureArtifact:
    """One capture as it appears inside a task manifest."""

    capture_id: str
    position: int
    mode: str = "annotate"
    note: str = ""
    timestamp: str = ""
    instruction: str = ""
    application: str = ""
    window_title: str = ""
    target: Optional[dict] = None
    assets: dict = field(default_factory=dict)
    context_file: Optional[str] = None

    def to_manifest(self) -> dict:
        bounds = (self.target or {}).get("bounds")
        return {
            "capture_id": self.capture_id,
            "mode": self.mode,
            "order": self.position,
            "timestamp": self.timestamp,
            "instruction": self.instruction,
            "note": self.note,
            "application": {
                "name": self.application,
                "window_title": self.window_title,
            },
            "target": {
                "resolution_method": (self.target or {}).get(
                    "resolution_method", "unknown"
                ),
                "confidence_kind": (self.target or {}).get(
                    "confidence_kind", "none"
                ),
                "label": (self.target or {}).get("label", ""),
                "bounds": (
                    {**bounds, "coordinate_space": COORDINATE_SPACE}
                    if bounds
                    else None
                ),
            },
            "assets": dict(self.assets),
            "context_file": self.context_file,
        }


@dataclass
class TaskBundle:
    task_id: str
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    project_id: Optional[str] = None
    project_path: Optional[str] = None
    title: str = ""
    instruction: str = ""
    status: str = TaskStatus.DRAFT.value
    captures: list[CaptureArtifact] = field(default_factory=list)

    # -- manifest ---------------------------------------------------------

    def to_manifest(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "title": self.title,
            "instruction": self.instruction,
            "project": {"path": self.project_path, "id": self.project_id},
            "capture_count": len(self.captures),
            "captures": [c.to_manifest() for c in self.captures],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_manifest(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Agent-facing Markdown. Only asserts what capture evidence supports."""
        lines = [
            "# Arrow Task Context",
            "",
            f"Task: {self.title}" if self.title else "Task: (untitled)",
            f"Task ID: {self.task_id}",
            f"Status: {self.status}",
        ]
        if self.project_path:
            lines.append(f"Project: {self.project_path}")
        lines.append("")

        if self.instruction:
            lines += ["## Requested change", "", self.instruction, ""]
        else:
            lines += [
                "## Requested change",
                "",
                "(No instruction was given; describe the change before handing off.)",
                "",
            ]

        for cap in sorted(self.captures, key=lambda c: c.position):
            lines.append(f"## Capture {cap.position}")
            lines.append("")
            if cap.instruction:
                lines.append(f"Instruction: {cap.instruction}")
            if cap.note:
                lines.append(f"Note: {cap.note}")
            if cap.application:
                lines.append(f"Application: {cap.application}")
            if cap.window_title:
                lines.append(f"Window: {cap.window_title}")

            target = cap.target or {}
            method = target.get("resolution_method", "unknown")
            if method == "fallback":
                lines.append(
                    "Target: not identified — this capture is a crop around a "
                    "click, not a detected element"
                )
            else:
                label = target.get("label") or ""
                kind = target.get("confidence_kind", "none")
                lines.append(
                    f"Target: {label or '(unnamed)'} "
                    f"(resolution: {method}, confidence: {kind})"
                )
            bounds = target.get("bounds")
            if bounds:
                lines.append(
                    f"Bounds: x={bounds.get('x')} y={bounds.get('y')} "
                    f"w={bounds.get('width')} h={bounds.get('height')} "
                    f"({COORDINATE_SPACE})"
                )
            for key, path in sorted(cap.assets.items()):
                if not path:
                    continue
                lines.append(f"{key}: {path}")
                if not os.path.exists(path):
                    lines.append(f"  (warning: {key} file is missing on disk)")
            lines.append("")

        return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "CaptureArtifact",
    "TaskBundle",
    "TaskStatus",
    "new_task_id",
]