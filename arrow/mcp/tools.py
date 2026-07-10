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


__all__ = ["ArrowTools", "ToolError", "TOOL_SCHEMAS"]
