"""
Accessibility tree snapshot.

Walks the Windows UIA tree from a screen point and returns a lightweight
list of ``{role, name, bounds, children}`` dicts.  Each entry costs ~20-30
tokens, making a window's worth a few thousand tokens total.

The hybrid approach (AX tree + screenshot) beats either alone at 69-72%
vs 56% task success in OSWorld benchmarks.

Boundary discipline: UIA is an external system boundary.  All UIA calls
are guarded; the function never raises, always returns a usable (possibly
empty) list.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("arrow.context.ax_tree")

# How deep to walk the tree from the target element.
DEFAULT_DEPTH = 3


def snapshot_ax_tree(
    x: int,
    y: int,
    depth: int = DEFAULT_DEPTH,
) -> list[dict]:
    """Walk the UIA tree at ``(x, y)`` and return a lightweight AX snapshot.

    Returns an empty list when UIA is unavailable or the point doesn't
    resolve to an element.
    """
    try:
        import uiautomation as auto
    except ImportError:
        log.debug("uiautomation not installed, AX tree unavailable")
        return []

    try:
        root = auto.ControlFromPoint(x, y)
    except Exception:
        log.debug("ControlFromPoint(%d, %d) failed", x, y, exc_info=True)
        return []

    if root is None:
        return []

    return [_walk(root, depth)]


def _walk(control: Any, remaining: int) -> dict:
    """Recursively build a tree node dict."""
    node: dict[str, Any] = {
        "role": _safe(lambda: control.ControlTypeName, "Unknown"),
        "name": _safe(lambda: control.Name, ""),
    }

    rect = _safe_rect(control)
    if rect:
        node["bounds"] = rect

    aid = _safe(lambda: control.AutomationId, "")
    if aid:
        node["automationId"] = aid

    if remaining > 0:
        children = _get_children(control, remaining - 1)
        if children:
            node["children"] = children

    return node


def _get_children(control: Any, remaining: int) -> list[dict]:
    """Collect immediate children, capped at 20 to stay token-cheap."""
    try:
        kids = control.GetChildren()
    except Exception:
        return []
    if not kids:
        return []
    # Cap to avoid runaway token costs on dense UIs.
    return [_walk(k, remaining) for k in kids[:20]]


def _safe(fn, default=""):
    try:
        val = fn()
        return val if val not in ("", None) else default
    except Exception:
        return default


def _safe_rect(control: Any) -> Optional[dict]:
    try:
        r = control.BoundingRectangle
        if r is None:
            return None
        return {
            "x": r.left,
            "y": r.top,
            "width": r.right - r.left,
            "height": r.bottom - r.top,
        }
    except Exception:
        return None


__all__ = ["snapshot_ax_tree", "DEFAULT_DEPTH"]
