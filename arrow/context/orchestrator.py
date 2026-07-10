import logging
from typing import Any, Dict

from arrow.capture.session import Annotation, CaptureSession
from arrow.context.browser_adapter import BrowserAdapter
from arrow.context.ocr_adapter import OCRAdapter
from arrow.context.windows_uia_adapter import WindowsUIAAdapter

logger = logging.getLogger("arrow.context.orchestrator")


class ContextOrchestrator:
    """
    Orchestrates the resolution of spatial annotations (source and destination anchors)
    and environmental details using the appropriate adapter cascade.
    """
    def __init__(self, ws_bridge: Any = None) -> None:
        self.browser_adapter = BrowserAdapter(ws_bridge)
        self.uia_adapter = WindowsUIAAdapter()
        self.ocr_adapter = OCRAdapter()

    def resolve_session_context(self, session: CaptureSession, raw_img: Any = None) -> None:
        """
        Resolves anchors and compiles environment context for the current capture session.
        Mutates the session object in-place.
        """
        # 1. Resolve source anchor
        source_ann = next((a for a in session.annotations if a.role == "source"), None)
        if source_ann:
            session.source_anchor = self.resolve_annotation_anchor(source_ann, session.capture_id, raw_img)

        # 2. Resolve destination anchor
        dest_ann = next((a for a in session.annotations if a.role == "destination"), None)
        if dest_ann:
            session.destination_anchor = self.resolve_annotation_anchor(dest_ann, session.capture_id, raw_img)

        # 3. Set environment context
        from arrow.context.highlight_resolver import _get_foreground_window_info
        win_info = _get_foreground_window_info()
        session.context = {
            "window_title": win_info.get("title", "") if win_info else "",
            "process_name": win_info.get("exe_name", "") if win_info else "",
            "pid": win_info.get("pid", 0) if win_info else 0,
        }

    def resolve_annotation_anchor(self, ann: Annotation, capture_id: str, raw_img: Any = None) -> Dict[str, Any]:
        """
        Resolves an annotation to a structured anchor dict with status, confidence, source,
        evidence, and metadata.
        """
        geom = ann.geometry
        if not geom:
            return {
                "status": "unresolved",
                "confidence": 0.0,
                "source": "none",
                "evidence": ["No geometry provided"],
                "capture_id": capture_id,
                "metadata": {}
            }

        # Calculate bounding box center
        x = int(geom.get("x", 0.0) + (geom.get("width", 0.0) or geom.get("w", 0.0)) / 2)
        y = int(geom.get("y", 0.0) + (geom.get("height", 0.0) or geom.get("h", 0.0)) / 2)

        from arrow.context.highlight_resolver import _get_foreground_window_info
        win_info = _get_foreground_window_info()
        exe_name = win_info.get("exe_name", "").lower() if win_info else ""

        evidence = []
        metadata = {}

        # Cascade 1: Webpage Context (Browser extension DOM)
        if self.browser_adapter.is_browser_active(exe_name):
            evidence.append(f"Active application is a browser: {exe_name}")
            el_data = self.browser_adapter.inspect_element(x, y)
            if el_data:
                evidence.append("DOM element successfully resolved via browser extension")
                metadata.update({
                    "element_selector": el_data.get("selector", "") or el_data.get("cssSelector", ""),
                    "element_path": el_data.get("path", "") or el_data.get("xpath", ""),
                    "react_components": el_data.get("reactComponent", ""),
                    "selected_text": el_data.get("selectedText", ""),
                    "url": el_data.get("url", ""),
                    "tag_name": el_data.get("tagName", ""),
                })
                return {
                    "status": "resolved",
                    "confidence": 0.95,
                    "source": "browser_dom",
                    "evidence": evidence,
                    "capture_id": capture_id,
                    "metadata": metadata
                }
            else:
                evidence.append("Browser extension connection failed or returned no match")

        # Cascade 2: Windows UI Automation (UIA)
        evidence.append("Checking Windows UI Automation (UIA)")
        uia_info = self.uia_adapter.inspect_at_point(x, y)
        if uia_info:
            evidence.append(f"UIA matched node of type {uia_info.get('type')}")
            metadata.update({
                "element_name": uia_info.get("name", ""),
                "element_type": uia_info.get("type", ""),
                "automation_id": uia_info.get("automation_id", ""),
            })
            return {
                "status": "resolved",
                "confidence": 0.85,
                "source": "uia",
                "evidence": evidence,
                "capture_id": capture_id,
                "metadata": metadata
            }

        # Cascade 3: OCR Fallback
        if raw_img:
            evidence.append("UI Automation found nothing; running OCR fallback")
            ocr_results = self.ocr_adapter.run_ocr(raw_img)
            # Find detection matching target point coordinates
            for det in ocr_results:
                bx = det["bounding_box"]  # (left, top, right, bottom)
                if bx[0] <= x <= bx[2] and bx[1] <= y <= bx[3]:
                    evidence.append(f"OCR successfully matched word '{det['text']}' in crop region")
                    metadata.update({
                        "element_name": det["text"],
                        "selected_text": det["text"],
                    })
                    return {
                        "status": "resolved",
                        "confidence": float(0.70 * det["confidence"]),
                        "source": "ocr",
                        "evidence": evidence,
                        "capture_id": capture_id,
                        "metadata": metadata
                    }

        # Cascade 4: Visual Only Fallback (low confidence)
        evidence.append("All structural and text resolvers failed. Defaulting to raw screenshot coordinates.")
        return {
            "status": "unresolved",
            "confidence": 0.25,
            "source": "screenshot_only",
            "evidence": evidence,
            "capture_id": capture_id,
            "metadata": {}
        }
