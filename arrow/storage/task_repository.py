"""TaskBundle persistence.

Uses the same SQLite database and connection helpers as the capture store —
no second database. Capture rows are never rewritten to add a task; membership
lives entirely in ``task_captures``, so pre-existing captures stay valid and
listable and asset ownership is untouched.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from arrow.storage.database import get_db_connection, init_db
from arrow.storage.tasks import (
    CaptureArtifact,
    TaskBundle,
    TaskStatus,
    new_task_id,
)

log = logging.getLogger("arrow.storage.task_repository")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRepository:
    """Group, order and export captures under one instruction."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        init_db(self._db_path)

    # -- tasks ------------------------------------------------------------

    def create_task(
        self,
        title: str = "",
        instruction: str = "",
        project_id: Optional[str] = None,
        project_path: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> str:
        task_id = task_id or new_task_id()
        now = _now()
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                """INSERT INTO tasks
                   (task_id, created_at, updated_at, project_id, project_path,
                    title, instruction, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, now, now, project_id, project_path,
                    title, instruction, TaskStatus.DRAFT.value,
                ),
            )
            conn.commit()
        return task_id

    def get_task_row(self, task_id: str) -> Optional[dict]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_task(self, task_id: str) -> Optional[TaskBundle]:
        row = self.get_task_row(task_id)
        if row is None:
            return None
        return TaskBundle(
            task_id=row["task_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            project_id=row["project_id"],
            project_path=row["project_path"],
            title=row["title"] or "",
            instruction=row["instruction"] or "",
            status=row["status"],
            captures=self.list_task_captures(task_id),
        )

    def list_tasks(self, limit: int = 50) -> list[dict]:
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute(
                """SELECT t.*, (SELECT COUNT(*) FROM task_captures tc
                                    WHERE tc.task_id = t.task_id) AS capture_count
                   FROM tasks t ORDER BY t.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["capture_count"] = d.get("capture_count", 0)
                out.append(d)
            return out

    def get_latest_task(self) -> Optional[TaskBundle]:
        tasks = self.list_tasks(limit=1)
        if not tasks:
            return None
        return self.get_task(tasks[0]["task_id"])

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        instruction: Optional[str] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> bool:
        sets, args = [], []
        for column, value in (
            ("title", title), ("instruction", instruction),
            ("status", status), ("project_id", project_id),
            ("project_path", project_path),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                args.append(value)
        if not sets:
            return self.get_task_row(task_id) is not None
        sets.append("updated_at = ?")
        args.extend([_now(), task_id])
        with get_db_connection(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", args
            )
            conn.commit()
            return cur.rowcount > 0

    def set_status(self, task_id: str, status: str) -> bool:
        """Only ever moves forward through explicit agent evidence."""
        return self.update_task(task_id, status=status)

    def delete_task(self, task_id: str) -> bool:
        """Deletes the bundle only.

        Capture rows and their asset files are intentionally left alone: a
        capture can be referenced from history and the user may still want the
        screenshot. Asset ownership stays with the capture.
        """
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM task_captures WHERE task_id = ?", (task_id,)
            )
            cur = conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0

    # -- membership -------------------------------------------------------

    def add_capture(
        self,
        task_id: str,
        capture_id: str,
        note: str = "",
        position: Optional[int] = None,
    ) -> bool:
        """Attach a capture. A capture belongs to at most one task."""
        if self.get_task_row(task_id) is None:
            return False
        with get_db_connection(self._db_path) as conn:
            if position is None:
                position = self._next_position(conn, task_id)
            # Detach from any previous task rather than duplicating it.
            conn.execute(
                "DELETE FROM task_captures WHERE capture_id = ?", (capture_id,)
            )
            conn.execute(
                """INSERT INTO task_captures (task_id, capture_id, position, note)
                   VALUES (?, ?, ?, ?)""",
                (task_id, capture_id, position, note),
            )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (_now(), task_id),
            )
            conn.commit()
        return True

    @staticmethod
    def _next_position(conn, task_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) AS m FROM task_captures WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["m"]) + 1

    def remove_capture(self, task_id: str, capture_id: str) -> bool:
        with get_db_connection(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM task_captures WHERE task_id = ? AND capture_id = ?",
                (task_id, capture_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def reorder(self, task_id: str, capture_ids: list[str]) -> bool:
        """Apply an explicit order. Unknown ids are rejected."""
        with get_db_connection(self._db_path) as conn:
            known = {
                r["capture_id"]
                for r in conn.execute(
                    "SELECT capture_id FROM task_captures WHERE task_id = ?",
                    (task_id,),
                ).fetchall()
            }
            if set(capture_ids) != known or len(capture_ids) != len(known):
                log.warning("reorder: id set does not match task membership")
                return False
            for position, capture_id in enumerate(capture_ids, start=1):
                conn.execute(
                    "UPDATE task_captures SET position = ? WHERE task_id = ? AND capture_id = ?",
                    (position, task_id, capture_id),
                )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (_now(), task_id),
            )
            conn.commit()
        return True

    def set_capture_note(self, task_id: str, capture_id: str, note: str) -> bool:
        with get_db_connection(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE task_captures SET note = ? WHERE task_id = ? AND capture_id = ?",
                (note, task_id, capture_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def task_for_capture(self, capture_id: str) -> Optional[str]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT task_id FROM task_captures WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return row["task_id"] if row else None

    # -- hydration --------------------------------------------------------

    def list_task_captures(self, task_id: str) -> list[CaptureArtifact]:
        """Hydrate artifacts, joining capture context where it exists.

        A capture row that has since been deleted still yields an artifact with
        its note, so task ordering is never silently reshuffled.
        """
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute(
                """SELECT tc.capture_id, tc.position, tc.note,
                          s.created_at, s.mode, s.voice_transcript,
                          c.data AS context_data,
                          (SELECT path FROM assets a
                            WHERE a.capture_id = tc.capture_id
                              AND a.type = 'screenshot' LIMIT 1) AS screenshot_path
                   FROM task_captures tc
                   LEFT JOIN sessions s ON s.capture_id = tc.capture_id
                   LEFT JOIN contexts c ON c.capture_id = tc.capture_id
                   WHERE tc.task_id = ?
                   ORDER BY tc.position ASC""",
                (task_id,),
            ).fetchall()

            out: list[CaptureArtifact] = []
            for row in rows:
                cdata = {}
                if row["context_data"]:
                    try:
                        cdata = json.loads(row["context_data"])
                    except ValueError:
                        cdata = {}
                assets = {
                    a["type"]: a["path"]
                    for a in conn.execute(
                        "SELECT type, path FROM assets WHERE capture_id = ?",
                        (row["capture_id"],),
                    ).fetchall()
                }
                out.append(
                    CaptureArtifact(
                        capture_id=row["capture_id"],
                        position=int(row["position"]),
                        mode=row["mode"] or "annotate",
                        note=row["note"] or "",
                        timestamp=row["created_at"] or "",
                        instruction=row["voice_transcript"] or "",
                        window_title=cdata.get("window_title", ""),
                        application=cdata.get("process_name", "")
                        or cdata.get("application", ""),
                        target=cdata.get("target"),
                        assets=assets,
                    )
                )
            return out


__all__ = ["TaskRepository"]