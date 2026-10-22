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

import json
import logging
from typing import Any, Callable, Optional

from arrow.storage.repository import Repository

log = logging.getLogger("arrow.mcp.tools")

# Agent-optimized images stay well under typical MCP client limits while
# remaining legible; a raw 4K frame would blow a context window.
MAX_IMAGE_BYTES = 1_500_000


class ToolError(Exception):
    """Raised when a tool cannot fulfil a request (e.g. unknown capture)."""


class RawContent:
    """A tool result that is already a list of MCP content blocks.

    Needed for images: MCP clients only render a real ``image`` content block,
    so a base64 string wrapped in a text block is not actually viewable.
    """

    def __init__(self, content: list[dict]) -> None:
        self.content = content


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
    # -- task-aware (existing-session handoff) --------------------------
    {
        "name": "arrow_get_latest_task",
        "description": "Get the most recent Arrow TaskBundle: the user's grouped screenshots and their instruction. Use this when the user says 'my latest task' or 'the screenshots I just took'.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "arrow_list_tasks",
        "description": "List Arrow task bundles (id, title, instruction, status, capture count), newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "arrow_get_task_context",
        "description": "Get one task bundle as a full JSON manifest: captures in order, target resolution provenance, bounds and asset paths.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "arrow_get_task_markdown",
        "description": "Get one task bundle as agent-readable Markdown, including screenshot paths and any missing files.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "arrow_list_task_captures",
        "description": "List the captures in a task, in user-defined order, with app/window and target resolution details.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "arrow_get_capture_image",
        "description": "Return a capture screenshot as real MCP image content the agent can actually see. asset defaults to the annotated screenshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "capture_id": {"type": "string"},
                "asset": {
                    "type": "string",
                    "enum": ["screenshot", "raw", "annotated", "context-crop",
                             "source-crop", "destination-crop"],
                    "default": "screenshot",
                },
            },
            "required": ["capture_id"],
        },
    },
    {
        "name": "arrow_get_fresh_screen_context",
        "description": "Take a NEW screenshot right now to verify a change, plus the focused window title. Timestamped so you can tell it apart from an older capture.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region {x, y, width, height} in virtual-desktop coordinates.",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                }
            },
        },
    },
    {
        "name": "arrow_preview_target",
        "description": (
            "blue pointer at it. Visual only: this never clicks, never moves "
            "the mouse and never changes anything. Provide coordinates, or a "
            "capture_id from a task to reuse that capture's resolved bounds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Screen X in virtual-desktop coordinates"},
                "y": {"type": "integer", "description": "Screen Y in virtual-desktop coordinates"},
                "capture_id": {
                    "type": "string",
                    "description": "Reuse a capture's resolved target bounds instead of x/y.",
                },
                "reason": {"type": "string", "description": "Shown to the user, e.g. 'the search button'"},
            },
        },
    },
    {
        "name": "arrow_request_action",
        "description": (
            "Ask the user to ALLOW or DENY one bounded screen action "
            "(click_target, scroll_target). This only raises a prompt and "
            "returns 'awaiting_approval'. It never performs anything; poll "
            "arrow_action_status for the outcome. Arrow refuses to act when "
            "the target cannot be re-identified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "enum": ["click_target", "scroll_target"]},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "window_title": {
                    "type": "string",
                    "description": "Foreground window title the action is approved for. "
                                   "Arrow aborts if focus changes.",
                },
                "reason": {"type": "string"},
                "expected_outcome": {"type": "string"},
            },
            "required": ["action_type", "x", "y"],
        },
    },
    {
        "name": "arrow_action_status",
        "description": (
            "Check the outcome of an action previously requested with "
            "arrow_request_action. Reports awaiting_approval, denied, "
            "executed or refused-with-reason."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string"}},
            "required": ["action_id"],
        },
    },
    {
        "name": "arrow_stop_agent",
        "description": "Immediately cancel every pending agent approval and hide the agent pointer.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class DesktopClient:
    """Talks to the running desktop app over the authenticated local API.

    Separate process: the MCP server may be driven from a different terminal
    than the app, so anything visual must go over HTTP. Requests are refused
    rather than faked when the app is not running or refuses the capability.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 5.0):
        self._base_url = base_url
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        if self._base_url is None:
            from arrow.core.config import get_config

            self._base_url = get_config().base_url
        return self._base_url

    def _token(self) -> str:
        from arrow.server.security import TokenManager

        return TokenManager().get_or_create()

    def get(self, path: str) -> dict:
        import json as _json
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self._token()}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                detail = _json.loads(body)
            except ValueError:
                detail = {"error": body[:200]}
            detail.setdefault("http_status", e.code)
            return detail
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "reason": "desktop_unreachable",
                "detail": f"Could not reach the Arrow desktop app: {e}",
            }

    def post(self, path: str, payload: dict) -> dict:
        import json as _json
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                detail = _json.loads(body)
            except ValueError:
                detail = {"error": body[:200]}
            detail.setdefault("http_status", e.code)
            return detail
        except Exception as e:  # noqa: BLE001 - app may simply not be running
            return {
                "ok": False,
                "reason": "desktop_unreachable",
                "detail": (
                    f"Could not reach the Arrow desktop app at {self.base_url}: {e}. "
                    "Start Arrow first; screenshots and tasks still work without it."
                ),
            }


class ArrowTools:
    def __init__(
        self,
        repository: Repository,
        task_repository: Any = None,
        desktop: Any = None,
    ):
        self.repo = repository
        self._task_repo = task_repository
        self._desktop = desktop
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
            "arrow_get_latest_task": self._latest_task,
            "arrow_list_tasks": self._list_tasks,
            "arrow_get_task_context": self._task_context,
            "arrow_get_task_markdown": self._task_markdown,
            "arrow_list_task_captures": self._task_captures,
            "arrow_get_capture_image": self._capture_image,
            "arrow_get_fresh_screen_context": self._fresh_screen,
            "arrow_preview_target": self._preview_target,
            "arrow_request_action": self._request_action,
            "arrow_action_status": self._action_status,
            "arrow_stop_agent": self._stop_agent,
        }

    @property
    def desktop(self):
        if self._desktop is None:
            self._desktop = DesktopClient()
        return self._desktop

    @property
    def tasks(self):
        """Lazily built so existing capture-only callers are unaffected."""
        if self._task_repo is None:
            from arrow.storage.task_repository import TaskRepository

            self._task_repo = TaskRepository(self.repo._db_path)
        return self._task_repo

    def _require_task(self, args: dict):
        task_id = args.get("task_id")
        if not task_id:
            raise ToolError("task_id is required")
        task = self.tasks.get_task(task_id)
        if task is None:
            raise ToolError(f"No task found: {task_id}")
        return task

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

    # -- task-aware handoff ---------------------------------------------

    def _latest_task(self, args: dict) -> Any:
        task = self.tasks.get_latest_task()
        if task is None:
            raise ToolError(
                "No Arrow tasks yet. Ask the user to press the notch's "
                "'+ Task' button, then click elements with Point mode."
            )
        return task.to_manifest()

    def _list_tasks(self, args: dict) -> Any:
        limit = int(args.get("limit", 20))
        return [
            {
                "task_id": t["task_id"],
                "title": t["title"],
                "instruction": t["instruction"],
                "status": t["status"],
                "capture_count": t["capture_count"],
                "updated_at": t["updated_at"],
                "project_path": t["project_path"],
            }
            for t in self.tasks.list_tasks(limit=limit)
        ]

    def _task_context(self, args: dict) -> Any:
        return self._require_task(args).to_manifest()

    def _task_markdown(self, args: dict) -> Any:
        return self._require_task(args).to_markdown()

    def _task_captures(self, args: dict) -> Any:
        task = self._require_task(args)
        return [c.to_manifest() for c in task.captures]

    def _capture_image(self, args: dict) -> Any:
        """Return real MCP image content for a capture screenshot.

        The path is taken from the database, never from the caller, so a
        capture id cannot be used to read an arbitrary file.
        """
        import base64
        import os

        cap = self._require(args)
        asset = args.get("asset") or "screenshot"
        assets = cap.get("assets") or {}
        path = assets.get(asset)
        if not path:
            # Fall back to the capture's primary screenshot.
            path = assets.get("screenshot")
            asset = "screenshot"
        if not path:
            raise ToolError(f"Capture {cap['capture_id']} has no image asset")

        if not os.path.isfile(path):
            raise ToolError(
                f"Image file for capture {cap['capture_id']} is missing on disk: {path}"
            )
        size = os.path.getsize(path)
        if size > MAX_IMAGE_BYTES:
            raise ToolError(
                f"Image is {size} bytes, above the {MAX_IMAGE_BYTES} byte limit; "
                "use arrow_get_capture_metadata for paths instead."
            )
        with open(path, "rb") as fh:
            blob = base64.b64encode(fh.read()).decode("ascii")
        return RawContent([
            {
                "type": "image",
                "data": blob,
                "mimeType": "image/png",
                "_meta": {"capture_id": cap["capture_id"], "asset": asset},
            }
        ])

    def _fresh_screen(self, args: dict) -> Any:
        """A genuinely new screenshot, labelled with when it was taken."""
        import base64
        import ctypes
        from datetime import datetime, timezone
        from io import BytesIO

        from arrow.capture.screenshot_service import ScreenshotService

        svc = ScreenshotService()
        try:
            img = svc.capture_headless(args.get("region"))
        except Exception as e:
            raise ToolError(f"Screen capture failed: {e}") from None
        img = svc.downscale_for_agent(img)

        title = ""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            text_buf = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, text_buf, len(text_buf))
            title = text_buf.value
        except Exception:
            title = ""

        png_buf = BytesIO()
        img.save(png_buf, format="PNG")
        blob = base64.b64encode(png_buf.getvalue()).decode("ascii")
        return RawContent([
            {
                "type": "text",
                "text": json.dumps({
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "window_title": title,
                    "width": img.size[0],
                    "height": img.size[1],
                    "note": "Freshly captured for this request; not a stored capture.",
                }, indent=2),
            },
            {"type": "image", "data": blob, "mimeType": "image/png"},
        ])

    # -- agent pointer + approved actions ---------------------------------

    def _preview_bounds(self, args: dict) -> dict:
        """Prefer a capture's resolved bounds; else use the given point."""
        capture_id = args.get("capture_id")
        if capture_id:
            # The resolved target lives in the capture's context, not in the
            # change-request row, so read it via the capture store.
            from arrow.storage.capture_store import CaptureStore

            self._require({"capture_id": capture_id})  # existence + authz check
            record = CaptureStore(self.repo._db_path).get(capture_id)
            target = (record.target if record else None) or {}
            bounds = target.get("bounds")
            if bounds:
                return {
                    "x": int(bounds["x"]),
                    "y": int(bounds["y"]),
                    "highlight": [
                        int(bounds["x"]), int(bounds["y"]),
                        int(bounds["width"]), int(bounds["height"]),
                    ],
                    "source": f"capture:{capture_id}",
                    "resolution_method": target.get("resolution_method", "unknown"),
                }
            raise ToolError(
                f"Capture {capture_id} has no resolved bounds; pass x and y instead."
            )
        x, y = args.get("x"), args.get("y")
        if x is None or y is None:
            raise ToolError("Provide either capture_id, or both x and y")
        if isinstance(x, bool) or isinstance(y, bool):
            raise ToolError("x and y must be integers")
        return {"x": int(x), "y": int(y), "highlight": None, "source": "arguments"}

    def _preview_target(self, args: dict) -> Any:
        """Visual only. Returns exactly what the desktop reported."""
        where = self._preview_bounds(args)
        result = self.desktop.post(
            "/agent/preview",
            {
                "x": where["x"],
                "y": where["y"],
                "highlight": where["highlight"],
                "label": args.get("reason", ""),
            },
        )
        if not result.get("ok"):
            raise ToolError(
                result.get("detail") or result.get("reason") or "Preview refused."
            )
        return {
            "ok": True,
            "previewed_at": where,
            "clicked": False,
            "note": "Pointer animated to the point. Nothing was clicked.",
        }

    def _request_action(self, args: dict) -> Any:
        payload = {
            "action_type": args.get("action_type"),
            "x": args.get("x"),
            "y": args.get("y"),
            "window_title": args.get("window_title"),
            "reason": args.get("reason", ""),
            "expected_outcome": args.get("expected_outcome", ""),
        }
        result = self.desktop.post("/agent/action", payload)
        if not result.get("ok"):
            raise ToolError(
                result.get("detail") or result.get("reason") or "Action refused."
            )
        return {
            **result,
            "executed": False,
            "note": "Waiting on the user. Poll arrow_action_status for the outcome.",
        }

    def _action_status(self, args: dict) -> Any:
        action_id = args.get("action_id")
        if not action_id:
            raise ToolError("action_id is required")
        result = self.desktop.get(f"/agent/action/{action_id}")
        if not result.get("ok"):
            raise ToolError(
                result.get("detail") or result.get("reason") or "Unknown action."
            )
        return result

    def _stop_agent(self, args: dict) -> Any:
        return self.desktop.post("/agent/stop", {})


__all__ = [
    "ArrowTools",
    "DesktopClient",
    "RawContent",
    "ToolError",
    "TOOL_SCHEMAS",
    "MAX_IMAGE_BYTES",
]
