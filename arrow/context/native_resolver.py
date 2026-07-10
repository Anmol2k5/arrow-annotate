"""
Native Windows application context (Phase 8).

Resolves the element at an exact source/destination screen point when the target
is not a webpage.

Resolution cascade:
  1. Windows UI Automation (UIA)  — pixel-perfect accessibility tree.
  2. OCR fallback                 — only when UIA fails; text + bounds per monitor.
  3. Visual-only fallback         — screenshot region is the only evidence.

Rules honoured here:
  * OCR coordinates are always reported in the coordinate space of the monitor
    they were captured on; they are never applied to another monitor.
  * Ambiguous OCR returns multiple candidates.
  * This resolver is read-only. It never clicks or types into any target.
  * Nothing is fabricated: fields that cannot be observed stay ``None``/empty.

UIA and OCR access are injectable so the resolution logic is unit-testable
without a live desktop.
"""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("bluely.native")

# Interactive UIA control types that raise resolution confidence.
_INTERACTIVE_TYPES = {
    "Button", "Hyperlink", "MenuItem", "TabItem", "TreeItem", "ListItem",
    "RadioButton", "CheckBox", "ComboBox", "Edit", "Slider", "SplitButton",
    "Spinner", "ToggleButton",
}

_MAX_PARENTS = 8


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class Rect(BaseModel):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


class NativeElementContext(BaseModel):
    process_name: Optional[str] = None
    window_title: Optional[str] = None
    control_type: Optional[str] = None
    name: Optional[str] = None
    automation_id: Optional[str] = None
    class_name: Optional[str] = None
    bounding_rect: Optional[Rect] = None
    parent_hierarchy: list[str] = Field(default_factory=list)
    enabled: Optional[bool] = None
    focused: Optional[bool] = None
    accessibility: dict = Field(default_factory=dict)


class OCRCandidate(BaseModel):
    text: str
    bounding_rect: Rect
    confidence: float
    monitor: str
    coordinate_space: str = "monitor_local_pixels"


class NativeResolverResult(BaseModel):
    status: str  # "resolved" | "low_confidence" | "ocr" | "unresolved" | "failed"
    confidence: float = 0.0
    source: str  # "windows_uia" | "ocr" | "visual" | "none"
    evidence: list[str] = Field(default_factory=list)
    capture_id: Optional[str] = None
    role: Optional[str] = None  # "source" | "destination" | None
    point: Optional[list[int]] = None
    monitor: Optional[str] = None
    coordinate_space: Optional[str] = None
    element: Optional[NativeElementContext] = None
    ocr_candidates: list[OCRCandidate] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


# Provider type aliases.
UIAProvider = Callable[[int, int], Optional[NativeElementContext]]
# Returns (monitor_name, [candidates]) for the monitor containing the point.
OCRProvider = Callable[[int, int], "tuple[Optional[str], list[OCRCandidate]]"]


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _process_name_from_pid(pid: int) -> Optional[str]:
    if not pid:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:  # pragma: no cover - platform dependent
        log.debug("process name lookup failed for pid %s: %s", pid, e)
    return None


# ---------------------------------------------------------------------------
# Default UIA provider
# ---------------------------------------------------------------------------

def _control_rect(control) -> Optional[Rect]:
    try:
        r = control.BoundingRectangle
        if r is None:
            return None
        return Rect(left=r.left, top=r.top, right=r.right, bottom=r.bottom)
    except Exception:
        return None


def _safe(getter, default=None):
    try:
        value = getter()
        return value if value not in ("", None) else default
    except Exception:
        return default


def _default_uia_provider(x: int, y: int) -> Optional[NativeElementContext]:  # pragma: no cover - needs desktop
    try:
        import uiautomation as auto
    except ImportError:
        log.debug("uiautomation not installed — UIA disabled")
        return None

    try:
        control = auto.ControlFromPoint(x, y)
    except Exception as e:
        log.debug("ControlFromPoint(%d,%d) failed: %s", x, y, e)
        return None
    if control is None:
        return None

    pid = _safe(lambda: control.ProcessId, 0) or 0
    process_name = _process_name_from_pid(pid)

    # Walk up for parent hierarchy + top-level window title.
    parents: list[str] = []
    window_title: Optional[str] = None
    node = control
    for _ in range(_MAX_PARENTS + 4):
        try:
            node = node.GetParentControl()
        except Exception:
            break
        if node is None:
            break
        ctype = _safe(lambda: node.ControlTypeName, "") or ""
        cname = _safe(lambda: node.Name, "") or ""
        if len(parents) < _MAX_PARENTS:
            parents.append(f"{ctype}:{cname}"[:120])
        if ctype in ("Window", "Pane") and cname and window_title is None:
            window_title = cname
    if window_title is None:
        try:
            top = auto.GetForegroundControl()
            if top is not None:
                window_title = _safe(lambda: top.Name)
        except Exception:
            pass

    accessibility = {
        "localized_control_type": _safe(lambda: control.LocalizedControlType),
        "help_text": _safe(lambda: control.HelpText),
        "access_key": _safe(lambda: control.AccessKey),
        "is_offscreen": _safe(lambda: bool(control.IsOffscreen)),
        "is_keyboard_focusable": _safe(lambda: bool(control.IsKeyboardFocusable)),
    }
    value = _safe(lambda: control.GetValuePattern().Value)
    if value:
        accessibility["value"] = value
    accessibility = {k: v for k, v in accessibility.items() if v is not None}

    return NativeElementContext(
        process_name=process_name,
        window_title=window_title,
        control_type=_safe(lambda: control.ControlTypeName),
        name=_safe(lambda: control.Name),
        automation_id=_safe(lambda: control.AutomationId),
        class_name=_safe(lambda: control.ClassName),
        bounding_rect=_control_rect(control),
        parent_hierarchy=parents,
        enabled=_safe(lambda: bool(control.IsEnabled)),
        focused=_safe(lambda: bool(control.HasKeyboardFocus)),
        accessibility=accessibility,
    )


# ---------------------------------------------------------------------------
# Default OCR provider (per-monitor)
# ---------------------------------------------------------------------------

_ocr_engine = None


def _get_ocr():  # pragma: no cover - heavy optional dependency
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            _ocr_engine = RapidOCR()
        except Exception as e:
            log.debug("OCR engine unavailable: %s", e)
            return None
    return _ocr_engine


def _default_ocr_provider(x: int, y: int) -> "tuple[Optional[str], list[OCRCandidate]]":  # pragma: no cover
    ocr = _get_ocr()
    if ocr is None:
        return None, []
    try:
        import mss
        import numpy as np
        from PIL import Image

        with mss.mss() as sct:
            monitor = None
            monitor_index = None
            for i, mon in enumerate(sct.monitors[1:], start=1):
                if (mon["left"] <= x < mon["left"] + mon["width"]
                        and mon["top"] <= y < mon["top"] + mon["height"]):
                    monitor = mon
                    monitor_index = i
                    break
            if monitor is None:
                return None, []
            monitor_name = f"monitor_{monitor_index}"
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        result, _ = ocr(np.array(img))
        if not result:
            return monitor_name, []

        local_x = x - monitor["left"]
        local_y = y - monitor["top"]

        candidates: list[OCRCandidate] = []
        for det in result:
            try:
                box, text, conf = det
            except Exception:
                continue
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            rect = Rect(left=min(xs), top=min(ys), right=max(xs), bottom=max(ys))
            candidates.append(OCRCandidate(
                text=text, bounding_rect=rect, confidence=float(conf),
                monitor=monitor_name,
            ))

        containing = [c for c in candidates if c.bounding_rect.contains(local_x, local_y)]
        chosen = containing if containing else candidates
        chosen.sort(key=lambda c: c.confidence, reverse=True)
        return monitor_name, chosen[:5]
    except Exception as e:
        log.debug("OCR provider failed: %s", e)
        return None, []


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class NativeContextResolver:
    """Resolves native Windows element context at a screen point.

    Args:
        uia_provider: Callable ``(x, y) -> NativeElementContext | None``.
        ocr_provider: Callable ``(x, y) -> (monitor_name, [OCRCandidate])``.
    """

    def __init__(
        self,
        uia_provider: Optional[UIAProvider] = None,
        ocr_provider: Optional[OCRProvider] = None,
    ):
        self._uia = uia_provider or _default_uia_provider
        self._ocr = ocr_provider or _default_ocr_provider

    def resolve_point(
        self,
        x: int,
        y: int,
        capture_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> NativeResolverResult:
        point = [int(x), int(y)]

        # Tier 1 — UIA
        try:
            element = self._uia(int(x), int(y))
        except Exception as e:
            log.warning("UIA provider raised: %s", e)
            element = None

        if element is not None:
            confidence, evidence = _score_uia(element)
            status = "resolved" if confidence >= 0.7 else "low_confidence"
            return NativeResolverResult(
                status=status,
                confidence=confidence,
                source="windows_uia",
                evidence=evidence,
                capture_id=capture_id,
                role=role,
                point=point,
                coordinate_space="physical_screen",
                element=element,
            )

        # Tier 2 — OCR fallback (only when UIA failed)
        try:
            monitor_name, candidates = self._ocr(int(x), int(y))
        except Exception as e:
            log.warning("OCR provider raised: %s", e)
            monitor_name, candidates = None, []

        if candidates:
            top = candidates[0]
            ambiguous = len(candidates) > 1
            confidence = round(top.confidence * (0.7 if ambiguous else 0.85), 3)
            evidence = [
                f'UIA returned no element; OCR read "{top.text}" on {top.monitor}.',
            ]
            if ambiguous:
                evidence.append(f"{len(candidates)} OCR candidates — result is ambiguous.")
            return NativeResolverResult(
                status="ocr" if confidence >= 0.5 else "low_confidence",
                confidence=confidence,
                source="ocr",
                evidence=evidence,
                capture_id=capture_id,
                role=role,
                point=point,
                monitor=monitor_name,
                coordinate_space="monitor_local_pixels",
                ocr_candidates=candidates,
            )

        # Tier 3 — visual-only fallback
        return NativeResolverResult(
            status="unresolved",
            confidence=0.0,
            source="visual",
            evidence=["Neither UIA nor OCR could resolve an element at this point."],
            capture_id=capture_id,
            role=role,
            point=point,
            monitor=monitor_name,
        )


def _score_uia(element: NativeElementContext) -> "tuple[float, list[str]]":
    confidence = 0.6
    evidence: list[str] = ["UIA resolved an element at the point."]
    if element.control_type in _INTERACTIVE_TYPES:
        confidence += 0.15
        evidence.append(f"Interactive control type: {element.control_type}.")
    if element.automation_id:
        confidence += 0.15
        evidence.append(f'AutomationId present: "{element.automation_id}".')
    if element.name:
        confidence += 0.1
        evidence.append(f'Accessible name: "{element.name}".')
    return min(round(confidence, 3), 0.98), evidence


__all__ = [
    "Rect",
    "NativeElementContext",
    "OCRCandidate",
    "NativeResolverResult",
    "NativeContextResolver",
]
