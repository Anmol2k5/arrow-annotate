"""
Arrow MCP tools (Phase 12).

Read-only retrieval tools plus a small set of controlled mutation tools that let
a coding agent report progress. Mutation tools update capture status only — they
never execute arbitrary operating-system actions.

Tools are transport-agnostic: :class:`ArrowTools` operates directly on a
:class:`~arrow.storage.repository.Repository` and is unit-testable without any
JSON-RPC transport.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from arrow.storage.repository import Repository

log = logging.getLogger("arrow.mcp.tools")


class ToolError(Exception):
    """Raised when a tool cannot fulfil a request (e.g. unknown capture)."""


# JSON-Schema-ish descriptors advertised via tools/list.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "arrow_get_latest_change_request",
        "description": "Get the most recent Arrow change request (structured spatial edit).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "arrow_get_change_request",
        "description": "Get a specific change request by capture_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_list_change_requests",
        "description": "List recent change requests (id, status, summary).",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "arrow_get_capture_metadata",
        "description": "Get capture metadata: status, timestamps, assets, project.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_get_project_context",
        "description": "Get repository/project context for a capture.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_get_source_context",
        "description": "Get the resolved source element context for a capture.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_get_destination_context",
        "description": "Get the resolved destination element context for a capture.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_mark_started",
        "description": "Mark a capture as being worked on by an agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_mark_completed",
        "description": "Mark a capture as completed.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_mark_failed",
        "description": "Mark a capture as failed with a reason.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_add_agent_note",
        "description": "Attach a note from the agent to a capture's history.",
        "inputSchema": {
            "type": "object",
            "properties": {"capture_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["capture_id", "note"],
        },
    },
    {
        "name": "arrow_get_ax_tree",
        "description": "Get the accessibility tree snapshot at a screen point. Returns a lightweight {role, name, bounds, children} tree. Much cheaper in tokens than a screenshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Screen X coordinate"},
                "y": {"type": "integer", "description": "Screen Y coordinate"},
                "depth": {"type": "integer", "default": 3},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "arrow_look",
        "description": "Take a fresh screenshot of the screen to verify your changes. Returns a token-optimized image (<=1568px long edge). Use this to check your own work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region {x, y, width, height} in screen coordinates. Omit to capture the primary monitor.",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
        },
    },
    {
        "name": "arrow_get_context_md",
        "description": "Get the context.md text for a capture. Contains instruction, source/destination context, AX tree, gesture trail, change request summary.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class ArrowTools:
    def __init__(self, repository: Repository):
        self.repo = repository
        self._handlers: dict[str, Callable[[dict], Any]] = {
            "arrow_get_latest_change_request": self._latest,
            "arrow_get_change_request": self._get,
            "arrow_list_change_requests": self._list,
            "arrow_get_capture_metadata": self._metadata,
            "arrow_get_project_context": self._project_context,
            "arrow_get_source_context": self._source_context,
            "arrow_get_destination_context": self._destination_context,
            "arrow_mark_started": self._mark_started,
            "arrow_mark_completed": self._mark_completed,
            "arrow_mark_failed": self._mark_failed,
            "arrow_add_agent_note": self._add_note,
            "arrow_get_ax_tree": self._ax_tree,
            "arrow_look": self._look,
            "arrow_get_context_md": self._context_md,
        }

    def names(self) -> list[str]:
        return list(self._handlers.keys())

    def call(self, name: str, arguments: dict | None = None) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool: {name}")
        return handler(arguments or {})

    # -- helpers ---------------------------------------------------------

    def _require(self, args: dict) -> dict:
        capture_id = args.get("capture_id")
        if not capture_id:
            raise ToolError("capture_id is required")
        cap = self.repo.get_capture(capture_id)
        if cap is None:
            raise ToolError(f"No capture found: {capture_id}")
        return cap

    # -- read-only tools -------------------------------------------------

    def _latest(self, args: dict) -> Any:
        cap = self.repo.get_latest_capture()
        if cap is None:
            raise ToolError("No captures available.")
        return cap["change_request"]

    def _get(self, args: dict) -> Any:
        return self._require(args)["change_request"]

    def _list(self, args: dict) -> Any:
        limit = int(args.get("limit", 20))
        out = []
        for cap in self.repo.list_captures(limit=limit):
            cr = cap["change_request"]
            out.append({
                "capture_id": cap["capture_id"],
                "status": cap["status"],
                "created_at": cap["created_at"],
                "summary": cr.get("summary", ""),
                "normalized_intent": cr.get("normalized_intent"),
            })
        return out

    def _metadata(self, args: dict) -> Any:
        cap = self._require(args)
        return {
            "capture_id": cap["capture_id"],
            "created_at": cap["created_at"],
            "updated_at": cap["updated_at"],
            "status": cap["status"],
            "project_id": cap["project_id"],
            "assets": list(cap["assets"].keys()),
            "application_mode": cap["change_request"].get("application_mode"),
        }

    def _project_context(self, args: dict) -> Any:
        return self._require(args)["change_request"].get("project", {})

    def _source_context(self, args: dict) -> Any:
        return self._require(args)["change_request"].get("source") or {}

    def _destination_context(self, args: dict) -> Any:
        return self._require(args)["change_request"].get("destination") or {}

    # -- controlled mutation tools ---------------------------------------

    def _mark_started(self, args: dict) -> Any:
        cap = self._require(args)
        self.repo.set_status(cap["capture_id"], "running", "agent started")
        return {"ok": True, "status": "running"}

    def _mark_completed(self, args: dict) -> Any:
        cap = self._require(args)
        self.repo.set_status(cap["capture_id"], "completed", args.get("note", "agent completed"))
        return {"ok": True, "status": "completed"}

    def _mark_failed(self, args: dict) -> Any:
        cap = self._require(args)
        self.repo.set_status(cap["capture_id"], "failed", args.get("reason", "agent reported failure"))
        return {"ok": True, "status": "failed"}

    def _add_note(self, args: dict) -> Any:
        cap = self._require(args)
        note = args.get("note", "")
        if not note:
            raise ToolError("note is required")
        self.repo.set_status(cap["capture_id"], cap["status"], f"agent note: {note}")
        return {"ok": True}

    # -- spatial context tools -------------------------------------------

    def _ax_tree(self, args: dict) -> Any:
        x = args.get("x")
        y = args.get("y")
        if x is None or y is None:
            raise ToolError("x and y are required")
        depth = int(args.get("depth", 3))
        from arrow.context.ax_tree import snapshot_ax_tree
        return snapshot_ax_tree(int(x), int(y), depth=depth)

    def _look(self, args: dict) -> Any:
        import base64
        from io import BytesIO

        from arrow.capture.screenshot_service import ScreenshotService
        svc = ScreenshotService()
        region = args.get("region")
        img = svc.capture_headless(region)
        img = svc.downscale_for_agent(img)
        buf = BytesIO()
        img.save(buf, format="PNG")
        blob = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "width": img.size[0],
            "height": img.size[1],
            "format": "png",
            "base64": blob,
        }

    def _context_md(self, args: dict) -> Any:
        import os

        from arrow.capture.context_file import latest_dir
        path = os.path.join(latest_dir(), "context.md")
        if not os.path.isfile(path):
            raise ToolError("No context.md available. Make a capture first.")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


__all__ = ["ArrowTools", "ToolError", "TOOL_SCHEMAS"]
