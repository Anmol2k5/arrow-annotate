"""Point Mode target resolution.

A single click has to produce a useful capture even when nothing about the
element can be identified. Two outcomes, never mixed up:

* **Resolved** — UIA/OCR found a real element. Its true bounds are used and
  the resolution method plus confidence are recorded.
* **Fallback** — nothing was identified. A crop around the click is used and
  is explicitly marked ``fallback`` so no consumer can mistake it for a
  detected element.

All rectangles are virtual-desktop coordinates and may be negative when a
monitor sits left of or above the primary display.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

log = logging.getLogger("arrow.context.point_target")

# Half-extent of the fallback crop around an unresolved click.
FALLBACK_HALF = 120
# Never emit a crop smaller than this in either axis.
MIN_FALLBACK_SIZE = 16

DESKTOP_BOUNDS_KEY = "coordinate_space"


@dataclass
class PointTarget:
    """What a click resolved to (or did not)."""

    x: int
    y: int
    rect: dict
    method: str  # "windows_uia" | "ocr" | "fallback"
    confidence: float
    label: str = ""
    evidence: List[str] = field(default_factory=list)
    monitor: Optional[str] = None
    element: Optional[dict] = None

    @property
    def is_fallback(self) -> bool:
        return self.method == "fallback"

    def to_dict(self) -> dict:
        return {
            "point": {"x": self.x, "y": self.y},
            "bounds": dict(self.rect),
            "resolution_method": self.method,
            "confidence": round(self.confidence, 3),
            "confidence_kind": "heuristic" if self.method != "fallback" else "none",
            "label": self.label,
            "evidence": list(self.evidence),
            "monitor": self.monitor,
            "element": self.element,
        }


def clip_rect(rect: dict, bounds: Optional[dict]) -> dict:
    """Clip ``rect`` to ``bounds`` without ever producing a negative extent.

    ``bounds`` is a virtual-desktop rectangle that may itself have negative
    x/y. Rectangles are always moved and shrunk, never dropped: a capture at
    the very edge of a left-hand monitor must still return *something*.
    """
    x, y = int(rect["x"]), int(rect["y"])
    w, h = int(rect["width"]), int(rect["height"])

    if bounds:
        bx, by = int(bounds["x"]), int(bounds["y"])
        bw, bh = int(bounds["width"]), int(bounds["height"])
        right, bottom = min(x + w, bx + bw), min(y + h, by + bh)
        x, y = max(x, bx), max(y, by)
        w, h = max(0, right - x), max(0, bottom - y)

    return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}


def fallback_rect(
    x: int, y: int, bounds: Optional[dict] = None, half: int = FALLBACK_HALF
) -> dict:
    """Crop centred on the click, clipped to the real desktop.

    Clipping happens on the far edge only, so a click near a boundary keeps
    the full ``half`` extent on the side that has room.
    """
    rect = {
        "x": int(x) - half,
        "y": int(y) - half,
        "width": half * 2,
        "height": half * 2,
    }
    clipped = clip_rect(rect, bounds)
    # Guarantee a usable crop even for a 1px desktop sliver.
    clipped["width"] = max(clipped["width"], MIN_FALLBACK_SIZE)
    clipped["height"] = max(clipped["height"], MIN_FALLBACK_SIZE)
    return clipped


def _rect_from_element(element: Any) -> Optional[dict]:
    """Normalise a NativeElementContext bounding rect to x/y/width/height."""
    raw = getattr(element, "bounding_rect", None) or (
        element.get("bounding_rect") if isinstance(element, dict) else None
    )
    if raw is None:
        return None
    left = getattr(raw, "left", None) if not isinstance(raw, dict) else raw.get("left")
    top = getattr(raw, "top", None) if not isinstance(raw, dict) else raw.get("top")
    right = getattr(raw, "right", None) if not isinstance(raw, dict) else raw.get("right")
    bottom = getattr(raw, "bottom", None) if not isinstance(raw, dict) else raw.get("bottom")
    if left is None or top is None or right is None or bottom is None:
        return None
    return {"x": int(left), "y": int(top), "width": int(right - left), "height": int(bottom - top)}


def _label_for(element: Any) -> str:
    if isinstance(element, dict):
        name = element.get("name") or ""
        ctype = element.get("control_type") or ""
    else:
        name = getattr(element, "name", None) or ""
        ctype = getattr(element, "control_type", None) or ""
    return name or ctype or ""


def resolve_point_target(
    x: int,
    y: int,
    desktop_bounds: Optional[dict] = None,
    resolver: Any = None,
) -> PointTarget:
    """Resolve a click into a target rectangle plus honest provenance.

    Never raises: an unreachable or crashing resolver degrades to the
    fallback crop rather than failing the capture.
    """
    point = (int(x), int(y))

    if resolver is None:
        from arrow.context.native_resolver import NativeContextResolver

        resolver = NativeContextResolver()

    try:
        result = resolver.resolve_point(*point)
        status = getattr(result, "status", "unresolved")
        source = getattr(result, "source", "none")
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        evidence = list(getattr(result, "evidence", []) or [])
        monitor = getattr(result, "monitor", None)
        element = getattr(result, "element", None)
    except Exception as e:
        log.warning("point resolution failed at %s: %s", point, e)
        result = None
        status, source, confidence, evidence = "failed", "none", 0.0, [f"resolver raised: {e}"]
        monitor, element = None, None

    element_dict: Any = None
    if element is not None:
        element_dict = element.model_dump() if hasattr(element, "model_dump") else element

    rect = _rect_from_element(element) if element is not None else None
    # Only trust an identified rectangle when the resolver actually succeeded.
    if rect is not None and status in ("resolved", "low_confidence") and source != "none":
        clipped = clip_rect(rect, desktop_bounds)
        if clipped["width"] > 0 and clipped["height"] > 0:
            return PointTarget(
                x=point[0],
                y=point[1],
                rect=clipped,
                method=source,
                confidence=confidence,
                label=_label_for(element),
                evidence=evidence,
                monitor=monitor,
                element=element_dict,
            )

    reason = evidence[0] if evidence else "no element resolved at this point"
    return PointTarget(
        x=point[0],
        y=point[1],
        rect=fallback_rect(*point, bounds=desktop_bounds),
        method="fallback",
        confidence=0.0,
        label="",
        evidence=[*evidence, f"Falling back to a crop around the click: {reason}"],
        monitor=monitor,
    )


__all__ = [
    "FALLBACK_HALF",
    "MIN_FALLBACK_SIZE",
    "PointTarget",
    "clip_rect",
    "fallback_rect",
    "resolve_point_target",
]