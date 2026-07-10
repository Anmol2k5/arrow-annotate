"""
High-level capture repository (Phase 10).

Provides atomic capture creation/deletion, asset management with logged +
retried deletion, provider-run and status tracking, settings, retention and a
full data wipe. Structured records live in SQLite; large binary assets live on
disk and are referenced by the ``assets`` table.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from arrow.storage.database import get_db_connection, init_db

log = logging.getLogger("arrow.storage.repository")

_MAX_DELETE_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Dependable local store for captures, assets and provider runs."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        init_db(self._db_path)

    # -- projects --------------------------------------------------------

    def upsert_project(self, project_id: str, path: str, name: Optional[str] = None) -> None:
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                """INSERT INTO projects (id, path, name, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET path=excluded.path, name=excluded.name""",
                (project_id, path, name, _now()),
            )
            conn.commit()

    # -- captures --------------------------------------------------------

    def create_capture(
        self,
        capture_id: str,
        change_request: dict,
        assets: Optional[dict[str, str]] = None,
        project_id: Optional[str] = None,
        mode: str = "web",
        status: str = "ready",
    ) -> None:
        """Atomically persist a capture, its change request and its assets."""
        assets = assets or {}
        now = _now()
        with get_db_connection(self._db_path) as conn:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """INSERT INTO sessions
                       (capture_id, created_at, updated_at, state, mode, project_id, raw_instruction, voice_transcript, provider, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(capture_id) DO UPDATE SET updated_at=excluded.updated_at, state=excluded.state""",
                    (capture_id, now, now, status.upper(), mode, project_id,
                     change_request.get("raw_user_request", ""), "", None, None),
                )
                conn.execute(
                    """INSERT INTO change_requests (capture_id, created_at, updated_at, project_id, status, data)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(capture_id) DO UPDATE SET updated_at=excluded.updated_at,
                           status=excluded.status, data=excluded.data""",
                    (capture_id, now, now, project_id, status, json.dumps(change_request)),
                )
                conn.execute("DELETE FROM assets WHERE capture_id = ?", (capture_id,))
                for asset_type, path in assets.items():
                    if path:
                        conn.execute(
                            "INSERT INTO assets (capture_id, path, type) VALUES (?, ?, ?)",
                            (capture_id, os.path.abspath(path), asset_type),
                        )
                conn.execute(
                    "INSERT INTO status_history (capture_id, status, timestamp, detail) VALUES (?, ?, ?, ?)",
                    (capture_id, status, now, "capture created"),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("Atomic capture creation failed for %s", capture_id)
                raise

    def get_capture(self, capture_id: str) -> Optional[dict]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT capture_id, created_at, updated_at, project_id, status, data FROM change_requests WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_capture(conn, row)

    def get_latest_capture(self) -> Optional[dict]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT capture_id, created_at, updated_at, project_id, status, data FROM change_requests ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self._row_to_capture(conn, row)

    def list_captures(self, limit: int = 50) -> list[dict]:
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT capture_id, created_at, updated_at, project_id, status, data FROM change_requests ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_capture(conn, r) for r in rows]

    def _row_to_capture(self, conn, row) -> dict:
        try:
            data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            log.error("Corrupted change_request JSON for %s", row["capture_id"])
            data = {"_corrupted": True}
        assets = {
            a["type"]: a["path"]
            for a in conn.execute(
                "SELECT type, path FROM assets WHERE capture_id = ?", (row["capture_id"],)
            ).fetchall()
        }
        return {
            "capture_id": row["capture_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "project_id": row["project_id"],
            "status": row["status"],
            "change_request": data,
            "assets": assets,
        }

    def set_status(self, capture_id: str, status: str, detail: Optional[str] = None) -> None:
        now = _now()
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE change_requests SET status = ?, updated_at = ? WHERE capture_id = ?",
                (status, now, capture_id),
            )
            conn.execute(
                "INSERT INTO status_history (capture_id, status, timestamp, detail) VALUES (?, ?, ?, ?)",
                (capture_id, status, now, detail),
            )
            conn.commit()

    def get_asset_path(self, capture_id: str, asset_type: str) -> Optional[str]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT path FROM assets WHERE capture_id = ? AND type = ? LIMIT 1",
                (capture_id, asset_type),
            ).fetchone()
            return row["path"] if row else None

    # -- provider runs ---------------------------------------------------

    def add_provider_run(self, capture_id: str, provider: str, status: str = "started") -> int:
        with get_db_connection(self._db_path) as conn:
            cur = conn.execute(
                "INSERT INTO provider_runs (capture_id, provider, status, started_at) VALUES (?, ?, ?, ?)",
                (capture_id, provider, status, _now()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_provider_run(self, run_id: int, status: str, notes: Optional[str] = None,
                            error: Optional[str] = None) -> None:
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE provider_runs SET status = ?, finished_at = ?, notes = ?, error = ? WHERE id = ?",
                (status, _now(), notes, error, run_id),
            )
            conn.commit()

    # -- deletion --------------------------------------------------------

    def delete_capture(self, capture_id: str) -> None:
        """Atomically delete a capture and all associated assets (files + rows)."""
        with get_db_connection(self._db_path) as conn:
            asset_paths = [
                r["path"] for r in conn.execute(
                    "SELECT path FROM assets WHERE capture_id = ?", (capture_id,)
                ).fetchall()
            ]
            try:
                conn.execute("BEGIN")
                # Cascades to annotations/assets/contexts/change_requests/etc.
                conn.execute("DELETE FROM sessions WHERE capture_id = ?", (capture_id,))
                conn.execute("DELETE FROM change_requests WHERE capture_id = ?", (capture_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("Atomic capture deletion failed for %s", capture_id)
                raise
            self._delete_asset_files(conn, asset_paths, capture_id)

    def _delete_asset_files(self, conn, paths: list[str], capture_id: Optional[str]) -> None:
        for path in paths:
            if not path or not os.path.exists(path):
                continue
            if not self._try_remove(path):
                log.warning("Deferring failed asset deletion: %s", path)
                conn.execute(
                    "INSERT INTO pending_asset_deletions (path, capture_id, attempts, created_at) VALUES (?, ?, ?, ?)",
                    (path, capture_id, 1, _now()),
                )
        conn.commit()

    @staticmethod
    def _try_remove(path: str) -> bool:
        try:
            os.remove(path)
            return True
        except OSError as e:
            log.error("Failed to delete asset %s: %s", path, e)
            return False

    def retry_pending_deletions(self) -> int:
        """Retry deferred asset deletions. Returns count still pending."""
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, path, attempts FROM pending_asset_deletions"
            ).fetchall()
            for r in rows:
                if not os.path.exists(r["path"]) or self._try_remove(r["path"]):
                    conn.execute("DELETE FROM pending_asset_deletions WHERE id = ?", (r["id"],))
                elif r["attempts"] + 1 >= _MAX_DELETE_ATTEMPTS:
                    log.error("Giving up on asset deletion after %d attempts: %s",
                              _MAX_DELETE_ATTEMPTS, r["path"])
                    conn.execute(
                        "UPDATE pending_asset_deletions SET attempts = ?, last_error = ? WHERE id = ?",
                        (r["attempts"] + 1, "max attempts reached", r["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE pending_asset_deletions SET attempts = ? WHERE id = ?",
                        (r["attempts"] + 1, r["id"]),
                    )
            conn.commit()
            return conn.execute("SELECT COUNT(*) FROM pending_asset_deletions").fetchone()[0]

    def delete_all(self) -> None:
        """Delete every capture and all associated asset files."""
        for cap in self.list_captures(limit=100000):
            self.delete_capture(cap["capture_id"])

    def apply_retention(self, max_count: Optional[int] = None,
                        max_age_days: Optional[int] = None) -> int:
        """Delete captures beyond retention limits. Returns number deleted."""
        deleted = 0
        captures = self.list_captures(limit=100000)
        to_delete: set[str] = set()

        if max_count is not None and len(captures) > max_count:
            for cap in captures[max_count:]:
                to_delete.add(cap["capture_id"])

        if max_age_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            for cap in captures:
                try:
                    created = datetime.fromisoformat(cap["created_at"])
                except ValueError:
                    continue
                if created < cutoff:
                    to_delete.add(cap["capture_id"])

        for capture_id in to_delete:
            self.delete_capture(capture_id)
            deleted += 1
        return deleted

    # -- settings --------------------------------------------------------

    def set_setting(self, key: str, value: Any) -> None:
        with get_db_connection(self._db_path) as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return default


__all__ = ["Repository"]
