import os
import json
import datetime
from dataclasses import dataclass, asdict
from typing import Optional

CAPTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


@dataclass
class CaptureRecord:
    id: str
    timestamp: str
    screenshot_path: str
    annotation_text: str = ""
    cursor_x: int = 0
    cursor_y: int = 0
    element_selector: str = ""
    element_path: str = ""
    react_components: str = ""
    computed_styles: str = ""
    accessibility: str = ""
    selected_text: str = ""
    bounding_box: Optional[dict] = None
    agentation_status: str = ""

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
        d = asdict(self)
        if self.bounding_box is None:
            d["bounding_box"] = {}
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CaptureRecord":
        if not data.get("bounding_box"):
            data["bounding_box"] = {}
        return cls(**data)


class CaptureStore:
    def __init__(self, captures_dir: str = CAPTURES_DIR):
        self._dir = captures_dir

    def _path(self, capture_id: str) -> str:
        return os.path.join(self._dir, f"{capture_id}.json")

    def add(self, record: CaptureRecord) -> None:
        os.makedirs(self._dir, exist_ok=True)
        with open(self._path(record.id), "w") as f:
            json.dump(record.to_dict(), f, indent=2)

    def get_all(self) -> list[CaptureRecord]:
        if not os.path.isdir(self._dir):
            return []
        records = []
        for fn in sorted(os.listdir(self._dir), reverse=True):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(self._dir, fn)) as f:
                        records.append(CaptureRecord.from_dict(json.load(f)))
                except Exception:
                    pass
        return records

    def get(self, capture_id: str) -> Optional[CaptureRecord]:
        p = self._path(capture_id)
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return CaptureRecord.from_dict(json.load(f))

    def update(self, record: CaptureRecord) -> None:
        self.add(record)

    def delete(self, capture_id: str) -> None:
        p = self._path(capture_id)
        if os.path.exists(p):
            os.remove(p)
