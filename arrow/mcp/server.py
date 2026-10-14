"""
Arrow local MCP server (Phase 12).

Implements the Model Context Protocol over JSON-RPC 2.0 (stdio transport) with no
third-party dependency, so Codex and Claude Code can retrieve Arrow context
without copy-paste.

The :func:`dispatch` function is transport-agnostic and unit-testable; the
:class:`MCPServer` wires it to stdio.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

from arrow.mcp.resources import ResourceProvider
from arrow.mcp.tools import TOOL_SCHEMAS, ArrowTools, ToolError
from arrow.storage.repository import Repository

log = logging.getLogger("arrow.mcp.server")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "arrow-mcp", "version": "1.0.0"}


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def dispatch(request: dict, tools: ArrowTools, resources: ResourceProvider) -> Optional[dict]:
    """Handle a single JSON-RPC request. Returns a response, or None for notifications."""
    if not isinstance(request, dict):
        return _error(None, -32600, "Invalid request: expected an object")
    method = request.get("method")
    request_id = request.get("id")
    if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error(request_id, -32600, "Invalid JSON-RPC request")

    # Notifications (no id) get no response.
    if "id" not in request:
        return None
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params: expected an object")

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": SERVER_INFO,
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOL_SCHEMAS})

    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "Tool name must be a string and arguments an object")
        try:
            value = tools.call(name, arguments)
        except ToolError as e:
            return _result(request_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })
        except Exception as e:  # pragma: no cover - defensive
            log.exception("tool call failed")
            return _error(request_id, -32603, f"Internal error: {e}")
        if name == "arrow_look":
            return _result(request_id, {
                "content": [{"type": "image", "mimeType": "image/png", "data": value["base64"]}],
            })
        return _result(request_id, {
            "content": [{"type": "text", "text": json.dumps(value, indent=2)}],
        })

    if method == "resources/list":
        return _result(request_id, {"resources": resources.list_resources()})

    if method == "resources/read":
        uri = params.get("uri", "")
        if not isinstance(uri, str):
            return _error(request_id, -32602, "Resource URI must be a string")
        try:
            content = resources.read_resource(uri)
        except FileNotFoundError as e:
            return _error(request_id, -32602, str(e))
        return _result(request_id, {"contents": [content]})

    return _error(request_id, -32601, f"Method not found: {method}")


class MCPServer:
    def __init__(self, db_path: Optional[str] = None, repository: Optional[Repository] = None):
        self.repo = repository or Repository(db_path)
        self.tools = ArrowTools(self.repo)
        self.resources = ResourceProvider(self.repo)

    def handle(self, request: dict) -> Optional[dict]:
        return dispatch(request, self.tools, self.resources)

    def serve_stdio(self) -> None:  # pragma: no cover - I/O loop
        log.info("Arrow MCP server started on stdio")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")
                sys.stdout.flush()
                continue
            response = self.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    MCPServer().serve_stdio()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["MCPServer", "dispatch", "PROTOCOL_VERSION", "SERVER_INFO"]
