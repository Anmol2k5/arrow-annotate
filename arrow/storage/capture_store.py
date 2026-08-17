import json
import os
from typing import Optional

from arrow.storage.database import get_db_connection, init_db
from arrow.storage.schemas import CaptureRecord

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPTURES_DIR = os.path.join(ROOT_DIR, "captures")
SCREENSHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")


class CaptureStore:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        init_db(self._db_path)

    def add(self, record: CaptureRecord) -> None:
        with get_db_connection(self._db_path) as conn:
            # Upsert into sessions
            conn.execute('''
                INSERT INTO sessions (capture_id, created_at, updated_at, state, mode, project_id, raw_instruction, voice_transcript, provider, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    voice_transcript=excluded.voice_transcript
            ''', (
                record.id,
                record.timestamp,
                record.timestamp,
                "COMPLETED",
                "desktop",
                None,
                "",
                record.annotation_text or "",
                None,
                None
            ))

            # Store asset (screenshot_path)
            conn.execute('DELETE FROM assets WHERE capture_id = ?', (record.id,))
            if record.screenshot_path:
                conn.execute('INSERT INTO assets (capture_id, path, type) VALUES (?, ?, ?)',
                             (record.id, record.screenshot_path, 'screenshot'))

            # Store context
            conn.execute('DELETE FROM contexts WHERE capture_id = ?', (record.id,))
            context_data = {
                "cursor_x": record.cursor_x,
                "cursor_y": record.cursor_y,
                "element_selector": record.element_selector,
                "element_path": record.element_path,
                "react_components": record.react_components,
                "computed_styles": record.computed_styles,
                "accessibility": record.accessibility,
                "selected_text": record.selected_text,
                "bounding_box": record.bounding_box,
                "agentation_status": record.agentation_status,
                "window_title": record.window_title,
                "change_request": json.dumps(record.change_request) if record.change_request else None,
            }
            conn.execute('INSERT INTO contexts (capture_id, data) VALUES (?, ?)',
                         (record.id, json.dumps(context_data)))
            conn.commit()

    def get_all(self) -> list[CaptureRecord]:
        records = []
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute('''
                SELECT s.capture_id, s.created_at, s.voice_transcript,
                       c.data as context_data,
                       (SELECT path FROM assets WHERE capture_id = s.capture_id AND type = 'screenshot' LIMIT 1) as screenshot_path
                FROM sessions s
                LEFT JOIN contexts c ON s.capture_id = c.capture_id
                ORDER BY s.created_at DESC
            ''').fetchall()

            for row in rows:
                cdata = json.loads(row['context_data']) if row['context_data'] else {}
                records.append(self._record_from_row(row, cdata))
        return records

    def get(self, capture_id: str) -> Optional[CaptureRecord]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute('''
                SELECT s.capture_id, s.created_at, s.voice_transcript,
                       c.data as context_data,
                       (SELECT path FROM assets WHERE capture_id = s.capture_id AND type = 'screenshot' LIMIT 1) as screenshot_path
                FROM sessions s
                LEFT JOIN contexts c ON s.capture_id = c.capture_id
                WHERE s.capture_id = ?
            ''', (capture_id,)).fetchone()
            
            if not row:
                return None
                
            cdata = json.loads(row['context_data']) if row['context_data'] else {}
            return self._record_from_row(row, cdata)

    def update(self, record: CaptureRecord) -> None:
        self.add(record)

    def delete(self, capture_id: str) -> None:
        with get_db_connection(self._db_path) as conn:
            # Get asset path to delete file from disk
            asset_row = conn.execute("SELECT path FROM assets WHERE capture_id = ? AND type = 'screenshot'", (capture_id,)).fetchone()
            if asset_row and asset_row['path'] and os.path.exists(asset_row['path']):
                try:
                    os.remove(asset_row['path'])
                except OSError:
                    pass
            
            # Deleting session triggers CASCADE DELETE on assets, contexts, annotations
            conn.execute('DELETE FROM sessions WHERE capture_id = ?', (capture_id,))
            conn.commit()

    def update_change_request(self, capture_id: str, change_request: Optional[dict],
                              annotation_text: Optional[str] = None) -> None:
        """Replace the persisted change request (and optionally the instruction text).

        Used by the edit-context flow when the user edits the instruction and the
        change request is recompiled. No-op when the capture does not exist.
        """
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT data FROM contexts WHERE capture_id = ?", (capture_id,)
            ).fetchone()
            if row is None:
                return
            cdata = json.loads(row["data"]) if row["data"] else {}
            cdata["change_request"] = json.dumps(change_request) if change_request else None
            conn.execute(
                "UPDATE contexts SET data = ? WHERE capture_id = ?",
                (json.dumps(cdata), capture_id),
            )
            if annotation_text is not None:
                conn.execute(
                    "UPDATE sessions SET voice_transcript = ? WHERE capture_id = ?",
                    (annotation_text, capture_id),
                )
            conn.commit()

    @staticmethod
    def _record_from_row(row, cdata: dict) -> CaptureRecord:
        change_request = cdata.get('change_request')
        if isinstance(change_request, str):
            try:
                change_request = json.loads(change_request)
            except json.JSONDecodeError:
                change_request = None
        return CaptureRecord(
            id=row['capture_id'],
            timestamp=row['created_at'],
            annotation_text=row['voice_transcript'],
            screenshot_path=row['screenshot_path'],
            cursor_x=cdata.get('cursor_x', 0),
            cursor_y=cdata.get('cursor_y', 0),
            element_selector=cdata.get('element_selector') or "",
            element_path=cdata.get('element_path') or "",
            react_components=cdata.get('react_components') or "",
            computed_styles=cdata.get('computed_styles') or "",
            accessibility=cdata.get('accessibility') or "",
            selected_text=cdata.get('selected_text') or "",
            bounding_box=cdata.get('bounding_box'),
            agentation_status=cdata.get('agentation_status') or "",
            window_title=cdata.get('window_title') or "",
            change_request=change_request,
        )
