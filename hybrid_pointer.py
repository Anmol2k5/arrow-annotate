"""
Hybrid pointer — local element resolution without API keys.

Ported from clicky-windows/ai/hybrid_pointer.py for the Bluely agent.

Two-tier resolver, each tier faster and cheaper than the next:

  Tier 1  Windows UI Automation (UIA)     ~5 ms     pixel-perfect
          Walks the OS accessibility tree, finds elements by name/role.
          Works in every standard UI: Chrome/Edge/Firefox, VS Code, IDEs,
          Office, Electron apps, native Win32, WinUI/UWP, Settings, etc.

  Tier 2  Offline OCR (RapidOCR/ONNX)     ~300 ms   text-perfect
          For canvas apps where UIA gives no tree: Figma, Photoshop, games,
          older Java/Swing UIs. Runs entirely on CPU, no API calls.

Public API:
    find_target(query: str, ...) -> Optional[Target]

The caller treats Target as opaque — it has .center_xy in LOGICAL screen
pixels, ready to feed directly into OSController.click().
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any

log = logging.getLogger("bluely.pointer")


@dataclass
class Target:
    """A pointing target with exact pixel coordinates in LOGICAL screen space."""
    x: int                # center X
    y: int                # center Y
    bbox: Tuple[int, int, int, int]   # (left, top, right, bottom)
    label: str            # what we matched (button text, control type, etc.)
    source: str           # "uia" | "ocr"
    confidence: float     # 0.0–1.0

    @property
    def center_xy(self) -> Tuple[int, int]:
        return (self.x, self.y)


# ──────────────────────────────────────────────────────────────────────────────
#  Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

_INTERACTIVE_TYPES = {
    # Most reliable click targets in UIA
    "Button", "Hyperlink", "MenuItem", "TabItem", "TreeItem", "ListItem",
    "RadioButton", "CheckBox", "ComboBox", "Edit", "Text",
    "Custom",  # often used by Electron / web apps
}


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score_match(query: str, element_name: str, element_type: str) -> float:
    """Fuzzy match score 0..1. Boosts:
      - exact substring match in the element name
      - interactive control types
      - whole-word match
    Penalises:
      - element names much longer than the query (coincidental substring hits)
    """
    q = _normalize(query)
    name = _normalize(element_name)
    if not q or not name:
        return 0.0
    score = 0.0
    if q == name:
        score = 1.0
    elif q in name:
        score = 0.85
    else:
        # Word overlap
        q_words = set(q.split())
        n_words = set(name.split())
        if q_words and n_words:
            overlap = len(q_words & n_words) / max(len(q_words), 1)
            score = overlap * 0.7
    if element_type in _INTERACTIVE_TYPES:
        score = min(1.0, score + 0.1)
    # Penalise when element name is much longer than query — these are
    # usually paragraphs of text, chat messages, or document content where
    # a few words matched by coincidence.
    len_ratio = len(q) / max(len(name), 1)
    if len_ratio < 0.3:
        score *= len_ratio * 2   # heavy penalty
    elif len_ratio < 0.5:
        score *= 0.7             # mild penalty
    return score


# ──────────────────────────────────────────────────────────────────────────────
#  TIER 1 — Windows UI Automation
# ──────────────────────────────────────────────────────────────────────────────

def _find_via_uia(query: str, min_score: float = 0.5) -> Optional[Target]:
    """Walk the UIA tree for the foreground window + descendants, find best match."""
    try:
        import uiautomation as auto
    except ImportError:
        log.debug("uiautomation not installed — Tier 1 (UIA) disabled")
        return None

    try:
        root = auto.GetForegroundControl()
        if root is None:
            root = auto.GetRootControl()
    except Exception as e:
        log.debug("UIA root lookup failed: %s", e)
        return None

    best: Optional[Tuple[float, Any]] = None
    queue: List[Tuple[Any, int]] = [(root, 0)]
    visited = 0
    MAX_NODES = 3500
    MAX_DEPTH = 40

    while queue and visited < MAX_NODES:
        node, depth = queue.pop(0)
        visited += 1
        try:
            name = node.Name or ""
            ctrl_type = node.ControlTypeName or ""
            rect = node.BoundingRectangle
        except Exception:
            continue
        # Skip off-screen / zero-size
        if not rect or rect.width() <= 0 or rect.height() <= 0:
            pass
        # Skip text blocks / paragraphs — real controls have short names
        elif len(name) > 120:
            pass
        else:
            score = _score_match(query, name, ctrl_type)
            # Also try AutomationId as backup match source
            if score < 0.85:
                try:
                    aid = getattr(node, "AutomationId", "") or ""
                    if aid:
                        score = max(score, _score_match(query, aid, ctrl_type) * 0.8)
                except Exception:
                    pass
            if score >= min_score and (best is None or score > best[0]):
                best = (score, node)

        if depth < MAX_DEPTH:
            try:
                for child in node.GetChildren():
                    queue.append((child, depth + 1))
            except Exception:
                continue

    if not best:
        log.debug("UIA: no match for %r (scanned %d nodes)", query, visited)
        return None

    score, node = best
    r = node.BoundingRectangle
    cx = (r.left + r.right) // 2
    cy = (r.top + r.bottom) // 2
    log.info("UIA hit: %r -> %s [%s] @ (%d,%d) score=%.2f",
             query, node.Name, node.ControlTypeName, cx, cy, score)
    print(f"[HybridPointer] UIA hit: '{node.Name}' [{node.ControlTypeName}] "
          f"@ ({cx},{cy}) score={score:.2f}", flush=True)
    return Target(
        x=cx, y=cy,
        bbox=(r.left, r.top, r.right, r.bottom),
        label=node.Name or node.ControlTypeName,
        source="uia",
        confidence=score,
    )


# ──────────────────────────────────────────────────────────────────────────────
#  TIER 2 — Offline OCR (RapidOCR, ONNX)
# ──────────────────────────────────────────────────────────────────────────────

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            _ocr_engine = RapidOCR()
        except ImportError:
            log.debug("rapidocr-onnxruntime not installed — Tier 2 (OCR) disabled")
            return None
        except Exception as e:
            log.warning("OCR engine init failed: %s", e)
            return None
    return _ocr_engine


def _find_via_ocr(query: str, screenshot_path: Optional[str] = None,
                  pil_image=None, min_score: float = 0.5) -> Optional[Target]:
    """Run OCR on the primary screen, fuzzy-match the query against detected text."""
    ocr = _get_ocr()
    if ocr is None:
        return None

    try:
        if pil_image is None and screenshot_path is None:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[1]
                raw = sct.grab(mon)
                from PIL import Image
                pil_image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        import numpy as np
        if pil_image is not None:
            img_arr = np.array(pil_image)
        else:
            img_arr = screenshot_path  # RapidOCR accepts paths directly

        result, _ = ocr(img_arr)
        if not result:
            log.debug("OCR returned no detections")
            return None

        best: Optional[Tuple[float, dict]] = None
        for det in result:
            try:
                box, text, conf = det
            except Exception:
                continue
            if conf < 0.4:
                continue
            score = _score_match(query, text, "")
            if score >= min_score and (best is None or score > best[0]):
                xs = [int(p[0]) for p in box]
                ys = [int(p[1]) for p in box]
                best = (score, {
                    "text": text,
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                    "conf": conf,
                })

        if not best:
            log.debug("OCR: no text matched %r", query)
            return None

        score, hit = best
        l, t, r, b = hit["bbox"]
        cx, cy = (l + r) // 2, (t + b) // 2
        log.info("OCR hit: %r -> %r @ (%d,%d) score=%.2f",
                 query, hit["text"], cx, cy, score)
        print(f"[HybridPointer] OCR hit: '{hit['text']}' @ ({cx},{cy}) "
              f"score={score:.2f}", flush=True)
        return Target(
            x=cx, y=cy, bbox=hit["bbox"],
            label=hit["text"], source="ocr",
            confidence=score * hit["conf"],
        )
    except Exception as e:
        log.warning("OCR tier failed: %s", e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def find_target(
    query: str,
    *,
    pil_image=None,
    skip_uia: bool = False,
    skip_ocr: bool = False,
) -> Optional[Target]:
    """Resolve a natural-language pointing query into pixel coordinates.

    Tries UIA → OCR in order. Returns the first hit with confidence
    >= the tier's threshold. Returns None if both tiers whiff.

    Note: This is a synchronous function (UIA + OCR are blocking but fast).

    Args:
        query:        what to find (e.g. "save button", "send icon",
                      "login text field").
        pil_image:    PIL.Image of the full screen — used by OCR tier. Optional;
                      OCR will capture its own if not provided.
        skip_*:       Force-skip a tier (for testing or perf-sensitive paths).

    Returns:
        Target with .center_xy in logical screen pixels, or None.
    """
    if not query or not query.strip():
        return None

    # Tier 1: UIA — fast, free, often perfect
    if not skip_uia:
        t = _find_via_uia(query)
        if t is not None and t.confidence >= 0.5:
            return t

    # Tier 2: OCR — text-based fallback for canvas apps
    if not skip_ocr:
        t = _find_via_ocr(query, pil_image=pil_image)
        if t is not None and t.confidence >= 0.5:
            return t

    log.debug("Hybrid pointer tiers 1+2 failed for query: %r", query)
    return None


__all__ = ["Target", "find_target"]
