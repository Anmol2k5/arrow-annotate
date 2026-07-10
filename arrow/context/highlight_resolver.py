"""
Highlight resolver — Windows equivalent of TipTourHighlightSourceResolver.

Resolves a user-highlighted screen region into a file, URL, text selection,
or screenshot-only source plus the tools that make sense for that source.

Resolution cascade (TipTour pattern, Windows-native):
  1. Explicit file path (from request)
  2. UIA at sampled points in highlight rect → AXURL/AXDocument/AXFilename equivalents
  3. Browser extension (WebSocket bridge) for DOM inspection
  4. Window title parsing for known editor/app patterns
  5. Fallback: screenshot_only with reduced confidence
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("bluely.highlight")

# ---------------------------------------------------------------------------
# Data types  (mirrors TipTourHighlightSourceResolution)
# ---------------------------------------------------------------------------

@dataclass
class HighlightToolCapability:
    id: str
    title: str
    endpoint: str | None
    mode: str          # "observe" | "action" | "provider" | "agent_file_tool"
    reason: str


@dataclass
class HighlightResolution:
    ok: bool
    kind: str                    # "local_file" | "remote_page_url" | "remote_image_url" | "screenshot_only"
    source: str                  # resolution method identifier
    file_path: str | None
    source_url: str | None
    app_name: str | None
    bundle_identifier: str | None  # Windows: executable name as pseudo-bundle
    process_identifier: int | None
    window_title: str | None
    confidence: float
    reason: str | None
    message: str | None
    content_category: str         # "code" | "image" | "text" | "markdown" | "json" | "pdf" | "web" | "visual" | "file" | "unknown"
    file_extension: str | None
    mime_type: str | None
    selected_text: str | None
    highlight_screen_rect: list[float] | None  # [x, y, w, h]
    tools: list[HighlightToolCapability]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "kind": self.kind,
            "source": self.source,
            "file_path": self.file_path,
            "source_url": self.source_url,
            "app_name": self.app_name,
            "bundle_identifier": self.bundle_identifier,
            "process_identifier": self.process_identifier,
            "window_title": self.window_title,
            "confidence": self.confidence,
            "reason": self.reason,
            "message": self.message,
            "content_category": self.content_category,
            "file_extension": self.file_extension,
            "mime_type": self.mime_type,
            "selected_text": self.selected_text,
            "highlight_screen_rect": self.highlight_screen_rect,
            "tools": [{"id": t.id, "title": t.title, "endpoint": t.endpoint,
                       "mode": t.mode, "reason": t.reason} for t in self.tools],
        }


# ---------------------------------------------------------------------------
# File-extension sets  (same categories as TipTour)
# ---------------------------------------------------------------------------

IMAGE_EXTS = {"jpg", "jpeg", "png", "heic", "heif", "webp", "avif", "tif", "tiff", "gif", "bmp"}
TEXT_EXTS = {"txt", "text", "rtf", "log", "csv", "tsv", "yaml", "yml", "toml", "ini", "env"}
MARKDOWN_EXTS = {"md", "markdown", "mdx"}
JSON_EXTS = {"json", "jsonl"}
CODE_EXTS = {
    "swift", "py", "js", "jsx", "ts", "tsx", "html", "css", "scss",
    "java", "kt", "go", "rs", "rb", "php", "c", "h", "cpp", "hpp",
    "m", "mm", "sh", "zsh", "bash", "sql",
}


# ---------------------------------------------------------------------------
# Known-application patterns  (Windows equivalent of TipTour's AppleScript cases)
# ---------------------------------------------------------------------------

def _known_app_file_path(title: str, exe_name: str) -> str | None:
    """Parse file paths from window titles of known apps."""
    title = title.strip()
    if not title:
        return None

    exe_lower = exe_name.lower() if exe_name else ""

    # VS Code: "file.ts - project - Visual Studio Code"
    if "code" in exe_lower or "visual studio code" in exe_lower:
        parts = title.split(" - ")
        if len(parts) >= 2:
            candidate = parts[0].strip()
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

    # Notepad++: "file.txt - Notepad++"
    if "notepad++" in exe_lower or "notepad++" in title.lower():
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2:
            candidate = parts[0].strip()
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

    # Sublime Text: "file.txt - Sublime Text"
    if "sublime" in exe_lower:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2:
            candidate = parts[0].strip()
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

    # Notepad: "file.txt - Notepad"
    if "notepad" in exe_lower and "notepad++" not in exe_lower:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2:
            candidate = parts[0].strip()
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

    # IntelliJ / JetBrains: "file.ts — project [/path/to/project]"
    if any(x in exe_lower for x in ("jetbrains", "intellij", "pycharm", "webstorm")):
        parts = title.split(" [")
        if len(parts) >= 2:
            project_path = parts[-1].rstrip("]")
            if os.path.isdir(project_path):
                return project_path

    return None


def _is_browser(exe_name: str) -> bool:
    """Check if the foreground app is a known browser."""
    if not exe_name:
        return False
    browsers = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                "opera.exe", "vivaldi.exe", "msedge.exe"}
    return exe_name.lower() in browsers


# ---------------------------------------------------------------------------
# Foreground window helpers  (Win32 via ctypes, consistent with server.py)
# ---------------------------------------------------------------------------

def _get_foreground_window_info() -> dict | None:
    """Get foreground window info using Win32 API (no pywin32 dependency)."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        length = user32.GetWindowTextLengthW(hwnd) + 1
        title_buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, title_buf, length)
        title = title_buf.value

        exe_path = ""
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                                       False, pid.value)
        if handle:
            exe_buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, exe_buf, ctypes.byref(size)):
                exe_path = exe_buf.value
            kernel32.CloseHandle(handle)

        exe_name = os.path.basename(exe_path) if exe_path else ""

        return {
            "hwnd": hwnd,
            "pid": pid.value,
            "title": title or "",
            "exe_name": exe_name,
            "exe_path": exe_path,
        }
    except Exception as e:
        log.debug("_get_foreground_window_info failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# UIA helpers at a given screen point
# ---------------------------------------------------------------------------

def _get_uia_info_at_point(cx: int, cy: int, pid: int | None = None
                           ) -> dict | None:
    """Query Windows UIA at a screen point and extract URL/document/filename."""
    try:
        import uiautomation as auto
    except ImportError:
        return None

    try:
        element = auto.ControlFromPoint(cx, cy)
        if element is None:
            return None

        if pid is not None:
            pass

        info: dict[str, Any] = {}
        try:
            info["name"] = element.Name or ""
        except Exception:
            info["name"] = ""
        try:
            info["ctrl_type"] = element.ControlTypeName or ""
        except Exception:
            info["ctrl_type"] = ""
        try:
            info["automation_id"] = element.AutomationId or ""
        except Exception:
            info["automation_id"] = ""

        # Try to get Value pattern (often contains URLs in browser address bars)
        try:
            value = element.GetPatternValue("Value")
            if value:
                info["value"] = value
        except Exception:
            pass

        # Try LegacyIAccessible for additional info
        try:
            default_action = element.GetPatternValue("LegacyIAccessible")
            if default_action:
                info["legacy"] = str(default_action)
        except Exception:
            pass

        # Bounding rectangle
        try:
            r = element.BoundingRectangle
            if r:
                info["bbox"] = (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass

        return info
    except Exception as e:
        log.debug("UIA point query failed at (%d,%d): %s", cx, cy, e)
        return None


def _focusable_element_at(cx: int, cy: int) -> Any | None:
    """Get first focusable/interactive UIA element at a point."""
    try:
        import uiautomation as auto
        element = auto.ControlFromPoint(cx, cy)
        if element is None:
            return None
        # Walk up to find an interactive ancestor
        if element.ControlTypeName not in ("Pane", "Window", "Custom"):
            return element
        parent = element
        for _ in range(10):
            try:
                parent = parent.GetParentControl()
            except Exception:
                break
            if parent and parent.ControlTypeName not in ("Pane", "Window", "Custom", ""):
                return parent
        return element
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Browser URL extraction via window title
# ---------------------------------------------------------------------------

_BROWSER_TITLE_PATTERNS = [
    # "Page Title - Google Chrome"
    (re.compile(r"^(.+?)\s*[-–—|]\s*(Google Chrome|Chromium|Brave|Opera)$"), 1),
    # "Page Title - Microsoft Edge" / "Page Title - Edge"
    (re.compile(r"^(.+?)\s*[-–—|]\s*(Microsoft Edge|Edge)$"), 1),
    # "Page Title - Mozilla Firefox"
    (re.compile(r"^(.+?)\s*[-–—|]\s*(Mozilla Firefox|Firefox)$"), 1),
    # "Page Title — Vivaldi"
    (re.compile(r"^(.+?)\s*[-–—|]\s*Vivaldi$"), 1),
]


def _extract_browser_page_title(window_title: str) -> str | None:
    """Extract the page title from a browser window title."""
    for pattern, group in _BROWSER_TITLE_PATTERNS:
        m = pattern.match(window_title.strip())
        if m:
            return m.group(group).strip()
    return None


# ---------------------------------------------------------------------------
# Content categorization  (same as TipTour)
# ---------------------------------------------------------------------------

def _content_category_for(file_ext: str | None, source_url: str | None, kind: str) -> str:
    if not file_ext:
        if kind == "remote_page_url":
            return "web"
        return "visual" if kind == "screenshot_only" else "unknown"
    if file_ext in IMAGE_EXTS:
        return "image"
    if file_ext in CODE_EXTS:
        return "code"
    if file_ext in MARKDOWN_EXTS:
        return "markdown"
    if file_ext in JSON_EXTS:
        return "json"
    if file_ext in TEXT_EXTS:
        return "text"
    if file_ext == "pdf":
        return "pdf"
    if source_url and kind == "remote_page_url":
        return "web"
    return "file"


def _mime_type_for(file_ext: str | None, content_category: str) -> str | None:
    if not file_ext:
        return "text/plain" if content_category == "text" else None
    mime_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "heic": "image/heic", "heif": "image/heif", "webp": "image/webp",
        "avif": "image/avif", "tif": "image/tiff", "tiff": "image/tiff",
        "gif": "image/gif", "bmp": "image/bmp",
        "pdf": "application/pdf",
        "json": "application/json", "jsonl": "application/json",
        "md": "text/markdown", "markdown": "text/markdown",
        "html": "text/html", "htm": "text/html",
        "csv": "text/csv",
    }
    mime = mime_map.get(file_ext)
    if mime:
        return mime
    if content_category in ("text", "code", "markdown"):
        return "text/plain"
    return None


# ---------------------------------------------------------------------------
# Tool capabilities  (mirrors TipTour's toolCapabilities)
# ---------------------------------------------------------------------------

def _tool_capabilities_for(
    kind: str,
    content_category: str,
    file_path: str | None,
    source_url: str | None,
    selected_text: str | None,
) -> list[HighlightToolCapability]:
    tools: list[HighlightToolCapability] = [
        HighlightToolCapability(
            id="visual_context",
            title="Get visual context",
            endpoint="/v1/visual-context",
            mode="observe",
            reason="Always useful for highlighted screen regions.",
        )
    ]

    if file_path or source_url:
        tools.append(
            HighlightToolCapability(
                id="open_source",
                title="Open source",
                endpoint="/v1/workflow-plan",
                mode="action",
                reason="The highlighted context resolved to a file or URL.",
            )
        )

    if content_category == "image":
        tools.append(
            HighlightToolCapability(
                id="image_edit",
                title="Edit image",
                endpoint="/v1/image-edit",
                mode="provider",
                reason="Image content can be edited with the configured image model.",
            )
        )
    elif content_category in ("text", "code", "markdown", "json"):
        tools.append(
            HighlightToolCapability(
                id="text_edit",
                title="Edit text",
                endpoint=None,
                mode="agent_file_tool",
                reason="Text-like content should be edited by the outer agent using file tools, then verified through TipTour if needed.",
            )
        )
    elif content_category == "pdf":
        tools.append(
            HighlightToolCapability(
                id="document_extract",
                title="Extract document text",
                endpoint=None,
                mode="agent_file_tool",
                reason="PDFs need document parsing or visual context before editing.",
            )
        )

    if selected_text:
        tools.append(
            HighlightToolCapability(
                id="selected_text_edit",
                title="Edit selected text",
                endpoint="/v1/workflow-plan",
                mode="action",
                reason="TipTour captured an active text selection or painted text range.",
            )
        )

    if kind == "screenshot_only":
        tools.append(
            HighlightToolCapability(
                id="screenshot_crop",
                title="Use screenshot crop",
                endpoint="/v1/visual-context",
                mode="observe",
                reason="No source file was resolved, so screenshot/crop context is the reliable fallback.",
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Sampled points within highlight rect  (same strategy as TipTour)
# ---------------------------------------------------------------------------

def _sampled_points(x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    """Generate candidate points within the rect for element probing."""
    points: list[tuple[int, int]] = []
    cx, cy = x + w // 2, y + h // 2

    points.append((cx, cy))
    points.append((cx + w // 4, cy))
    points.append((cx - w // 4, cy))
    points.append((cx, cy + h // 4))
    points.append((cx, cy - h // 4))
    points.append((x + w // 4, y + h // 4))
    points.append((x + 3 * w // 4, y + h // 4))
    points.append((x + w // 4, y + 3 * h // 4))
    points.append((x + 3 * w // 4, y + 3 * h // 4))
    points.append((x + 1, y + 1))

    seen: set[str] = set()
    return [p for p in points if seen.add(f"{p[0]}:{p[1]}") is None]


# ---------------------------------------------------------------------------
# Public API — HighlightResolver
# ---------------------------------------------------------------------------

class HighlightResolver:
    """Windows-native highlight resolver following TipTour's pattern.

    Args:
        ws_bridge: Optional WebSocketBridge for browser DOM inspection.
    """

    def __init__(self, ws_bridge: Any | None = None):
        self._ws_bridge = ws_bridge

    def resolve(
        self,
        rect: tuple[int, int, int, int],
        explicit_file_path: str | None = None,
        selected_text: str | None = None,
    ) -> HighlightResolution:
        """Resolve a highlighted screen rect into a source context.

        Args:
            rect: (x, y, width, height) in logical screen pixels.
            explicit_file_path: Optional explicit file path from the caller.
            selected_text: Optional text selection captured alongside the highlight.

        Returns:
            HighlightResolution with confidence, content_category, tools, etc.
        """
        x, y, w, h = rect
        rect_f = [float(x), float(y), float(w), float(h)]

        # 1. Explicit file path (highest confidence, skip everything else)
        if explicit_file_path:
            resolution = self._make_local_file_resolution(
                path=explicit_file_path,
                source="request.source_file_path",
                confidence=1.0,
                rect=rect_f,
                selected_text=selected_text,
            )
            if resolution:
                return resolution

        # 2. Get foreground window context
        win_info = _get_foreground_window_info()
        if win_info:
            # 3. Try UIA at sampled points
            uia_resolution = self._resolve_via_uia(rect, win_info, rect_f, selected_text)
            if uia_resolution:
                return uia_resolution

            # 4. Try browser extension via WebSocket
            browser_resolution = self._resolve_via_browser(win_info, rect, rect_f, selected_text)
            if browser_resolution:
                return browser_resolution

            # 5. Try window-title-based file path extraction
            title_resolution = self._resolve_via_title(win_info, rect_f, selected_text)
            if title_resolution:
                return title_resolution

        # 6. Fallback: screenshot only
        return self._make_screenshot_resolution(
            win_info=win_info,
            rect=rect_f,
            selected_text=selected_text,
        )

    # --- Resolution tiers ---

    def _resolve_via_uia(
        self,
        rect: tuple[int, int, int, int],
        win_info: dict,
        rect_f: list[float],
        selected_text: str | None,
    ) -> Optional[HighlightResolution]:
        """Probe UIA at sampled points — equivalent to TipTour's AXUIElement path."""
        x, y, w, h = rect
        points = _sampled_points(x, y, w, h)
        pid = win_info.get("pid")

        for px, py in points:
            info = _get_uia_info_at_point(px, py, pid)
            if not info:
                continue

            name = info.get("name", "")
            value = info.get("value", "")

            # Check for URL in value or name
            url_str = value or name
            if url_str and (url_str.startswith("http://") or url_str.startswith("https://") or url_str.startswith("file://")):
                url_str = url_str.strip()
                return self._make_url_resolution(
                    url=url_str,
                    source="accessibility.uia_value",
                    win_info=win_info,
                    rect=rect_f,
                    selected_text=selected_text,
                    confidence=0.85,
                )

            # Check for file path in name or value
            if name and os.path.exists(name):
                return self._make_local_file_resolution(
                    path=name,
                    source="accessibility.uia_name",
                    confidence=0.85,
                    rect=rect_f,
                    selected_text=selected_text,
                )
            if value and os.path.exists(value):
                return self._make_local_file_resolution(
                    path=value,
                    source="accessibility.uia_value",
                    confidence=0.85,
                    rect=rect_f,
                    selected_text=selected_text,
                )

        # Try focused element
        try:
            import uiautomation as auto
            focused = auto.GetFocusedControl()
            if focused:
                f_name = focused.Name or ""
                f_value = ""
                try:
                    f_value = focused.GetPatternValue("Value") or ""
                except Exception:
                    pass
                url_str = f_value or f_name
                if url_str.startswith("http"):
                    return self._make_url_resolution(
                        url=url_str.strip(),
                        source="accessibility.focused_element",
                        win_info=win_info,
                        rect=rect_f,
                        selected_text=selected_text,
                        confidence=0.75,
                    )
                if f_name and os.path.exists(f_name):
                    return self._make_local_file_resolution(
                        path=f_name,
                        source="accessibility.focused_element",
                        confidence=0.75,
                        rect=rect_f,
                        selected_text=selected_text,
                    )
        except Exception:
            pass

        return None

    def _resolve_via_browser(
        self,
        win_info: dict,
        rect: tuple[int, int, int, int],
        rect_f: list[float],
        selected_text: str | None,
    ) -> Optional[HighlightResolution]:
        """Use WebSocket bridge to inspect DOM at highlight center."""
        exe_name = win_info.get("exe_name", "")
        if not _is_browser(exe_name):
            return None
        if not self._ws_bridge:
            return None
        if not getattr(self._ws_bridge, "connected", False):
            return None

        x, y = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2

        try:
            result = self._ws_bridge.inspect(x, y, timeout=3.0)
            if not result or result.get("status") != "ok":
                return None

            el = result.get("element", {}) or result
            page_url = el.get("url") or el.get("pageUrl", "")
            text_content = el.get("text", "") or el.get("selectedText", "")

            if page_url:
                confidence = 0.6
                url = page_url
                scheme = (url.split(":")[0] if ":" in url else "").lower()
                if scheme == "file":
                    confidence = 0.75

                resolution = self._make_url_resolution(
                    url=url,
                    source="websocket.browser.inspect",
                    win_info=win_info,
                    rect=rect_f,
                    selected_text=selected_text or text_content or None,
                    confidence=confidence,
                )
                window_title_page = _extract_browser_page_title(win_info.get("title", ""))
                if window_title_page and not resolution.source_url:
                    resolution.source_url = url
                return resolution

            # If no URL, use text content as selected text fallback
            if text_content:
                return self._make_screenshot_resolution(
                    win_info=win_info,
                    rect=rect_f,
                    selected_text=selected_text or text_content,
                    kind="remote_page_url",
                    confidence=0.45,
                    message="Found text content in browser but could not resolve page URL.",
                )
        except Exception as e:
            log.debug("Browser resolution failed: %s", e)

        return None

    def _resolve_via_title(
        self,
        win_info: dict,
        rect_f: list[float],
        selected_text: str | None,
    ) -> Optional[HighlightResolution]:
        """Extract file path from window title for known apps."""
        title = win_info.get("title", "")
        exe_name = win_info.get("exe_name", "")
        file_path = _known_app_file_path(title, exe_name)
        if file_path:
            return self._make_local_file_resolution(
                path=file_path,
                source="applescript.window_title",
                confidence=0.8 if os.path.isfile(file_path) else 0.6,
                rect=rect_f,
                selected_text=selected_text,
            )

        # Browser page title extraction (lower confidence, no URL)
        if _is_browser(exe_name):
            page_title = _extract_browser_page_title(title)
            if page_title:
                return HighlightResolution(
                    ok=True,
                    kind="remote_page_url",
                    source="window_title.browser_tab",
                    file_path=None,
                    source_url=None,
                    app_name=os.path.splitext(exe_name)[0].title() if exe_name else None,
                    bundle_identifier=exe_name,
                    process_identifier=win_info.get("pid"),
                    window_title=title,
                    confidence=0.35,
                    reason="page_title_only",
                    message=f"Browser tab title resolved ('{page_title}') but no URL could be extracted. "
                            "The outer agent may need navigation context.",
                    content_category="web",
                    file_extension=None,
                    mime_type=None,
                    selected_text=selected_text,
                    highlight_screen_rect=rect_f,
                    tools=_tool_capabilities_for(
                        "remote_page_url", "web", None, None, selected_text
                    ),
                )

        return None

    # --- Resolution builders ---

    def _make_local_file_resolution(
        self,
        path: str,
        source: str,
        confidence: float,
        rect: list[float],
        selected_text: str | None,
    ) -> Optional[HighlightResolution]:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            return None

        ext = os.path.splitext(path)[1].lstrip(".").lower() or None
        cat = _content_category_for(ext, None, "local_file")

        return HighlightResolution(
            ok=True,
            kind="local_file",
            source=source,
            file_path=path,
            source_url=None,
            app_name=None,
            bundle_identifier=None,
            process_identifier=None,
            window_title=None,
            confidence=min(confidence, 0.95),
            reason=None,
            message="Resolved the local file for the highlighted context.",
            content_category=cat,
            file_extension=ext,
            mime_type=_mime_type_for(ext, cat),
            selected_text=selected_text,
            highlight_screen_rect=rect,
            tools=_tool_capabilities_for("local_file", cat, path, None, selected_text),
        )

    def _make_url_resolution(
        self,
        url: str,
        source: str,
        win_info: dict,
        rect: list[float],
        selected_text: str | None,
        confidence: float,
    ) -> HighlightResolution:
        if url.startswith("file://"):
            file_path = url[7:]
            file_resolution = self._make_local_file_resolution(
                path=file_path, source=source, confidence=confidence,
                rect=rect, selected_text=selected_text,
            )
            if file_resolution:
                return file_resolution

        ext = None
        parsed_ext = url.rsplit(".", 1)
        if len(parsed_ext) > 1:
            ext = parsed_ext[1].split("?")[0].split("#")[0].lower()

        kind = "remote_image_url" if ext in IMAGE_EXTS else "remote_page_url"
        cat = _content_category_for(ext, url, kind)

        exe_name = win_info.get("exe_name", "") if win_info else ""

        return HighlightResolution(
            ok=True,
            kind=kind,
            source=source,
            file_path=None,
            source_url=url,
            app_name=os.path.splitext(exe_name)[0].title() if exe_name else None,
            bundle_identifier=exe_name or None,
            process_identifier=win_info.get("pid") if win_info else None,
            window_title=win_info.get("title") if win_info else None,
            confidence=confidence,
            reason=None,
            message="Resolved a browser URL. The outer agent can inspect or download it if needed.",
            content_category=cat,
            file_extension=ext,
            mime_type=_mime_type_for(ext, cat),
            selected_text=selected_text,
            highlight_screen_rect=rect,
            tools=_tool_capabilities_for(kind, cat, None, url, selected_text),
        )

    def _make_screenshot_resolution(
        self,
        win_info: dict | None,
        rect: list[float],
        selected_text: str | None,
        kind: str = "screenshot_only",
        confidence: float = 0.25,
        message: str | None = None,
    ) -> HighlightResolution:
        return HighlightResolution(
            ok=False,
            kind=kind,
            source="highlight_screenshot",
            file_path=None,
            source_url=None,
            app_name=win_info.get("exe_name", "") if win_info else None,
            bundle_identifier=win_info.get("exe_name") if win_info else None,
            process_identifier=win_info.get("pid") if win_info else None,
            window_title=win_info.get("title") if win_info else None,
            confidence=confidence,
            reason="source_file_unresolved",
            message=message or (
                "Could not resolve a local file or URL. "
                "Bluely can still provide visual context for the highlighted region."
            ),
            content_category="visual",
            file_extension=None,
            mime_type=None,
            selected_text=selected_text,
            highlight_screen_rect=rect,
            tools=_tool_capabilities_for(kind, "visual", None, None, selected_text),
        )


__all__ = [
    "HighlightResolver",
    "HighlightResolution",
    "HighlightToolCapability",
]
