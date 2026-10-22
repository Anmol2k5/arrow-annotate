import json
import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CaptureRecord(BaseModel):
    id: str
    timestamp: str
    screenshot_path: str
    # Every file the pipeline wrote for this capture (raw, crops, agent
    # copies...). Deletion must remove all of them, not just the annotated
    # screenshot — otherwise files accumulate in screenshots/ forever.
    assets: Dict[str, str] = Field(default_factory=dict)
    annotation_text: str = ""
    cursor_x: int = 0
    cursor_y: int = 0
    element_selector: str = ""
    element_path: str = ""
    react_components: str = ""
    computed_styles: str = ""
    accessibility: str = ""
    selected_text: str = ""
    bounding_box: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Point Mode provenance: how the target was resolved, its confidence and
    # the evidence behind it. Absent for freehand captures.
    target: Optional[Dict[str, Any]] = None
    agentation_status: str = ""
    window_title: str = ""
    change_request: Optional[Dict[str, Any]] = None

    def formatted_context(self) -> str:
        parts = []
        if self.annotation_text:
            parts.append(f"**Voice Annotation:** {self.annotation_text}")
        parts.append(f"**Cursor:** ({self.cursor_x}, {self.cursor_y})")
        if self.element_selector and self.element_selector != "web_page":
            parts.append(f"**CSS Selector:** `{self.element_selector}`")
        if self.element_path:
            parts.append(f"**Element Path:** `{self.element_path}`")
        if self.react_components:
            parts.append(f"**React Tree:** {self.react_components}")
        if self.selected_text:
            parts.append(f"**Selected Text:** {self.selected_text}")
        if self.computed_styles and self.computed_styles not in ("{}", ""):
            try:
                styles = json.loads(self.computed_styles)
                s = "; ".join(f"{k}: {v}" for k, v in list(styles.items())[:8])
                parts.append(f"**Styles:** `{s}`")
            except json.JSONDecodeError:
                pass
        if self.accessibility and self.accessibility not in ("{}", ""):
            try:
                a11y = json.loads(self.accessibility)
                s = "; ".join(f"{k}: {v}" for k, v in a11y.items())
                parts.append(f"**A11y:** {s}")
            except json.JSONDecodeError:
                pass
        if self.bounding_box:
            b = self.bounding_box
            parts.append(f"**Box:** x={b.get('x')} y={b.get('y')} w={b.get('width')} h={b.get('height')}")
        parts.append(f"**File:** `{os.path.basename(self.screenshot_path)}`")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        d = self.model_dump()
        if self.bounding_box is None:
            d["bounding_box"] = {}
        if self.change_request is None:
            d["change_request"] = {}
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CaptureRecord":
        if not data.get("bounding_box"):
            data["bounding_box"] = {}
        return cls(**data)
