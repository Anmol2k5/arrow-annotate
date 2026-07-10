import json
import os
from typing import Optional

from arrow.storage.schemas import CaptureRecord

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPTURES_DIR = os.path.join(ROOT_DIR, "captures")
SCREENSHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")


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
