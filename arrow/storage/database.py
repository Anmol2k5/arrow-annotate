import contextlib
import os
import sqlite3
from typing import Optional

from arrow.core.config import migrate_legacy_home, resolve_db_path
from arrow.storage.migrations import run_migrations

# ARROW_DB_PATH overrides, else <ARROW_HOME>/arrow.db. Resolved from ARROW_HOME
# so a packaged build never writes into its own (possibly read-only) directory.
DB_PATH = resolve_db_path()


def default_db_path() -> str:
    """Current default database location (re-reads ARROW_HOME/ARROW_DB_PATH)."""
    return resolve_db_path()


@contextlib.contextmanager
def get_db_connection(db_path: Optional[str] = None):
    if db_path is None:
        db_path = default_db_path()

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # PRAGMA must be executed for every connection to enable foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    if db_path is None:
        # First call on a default path is startup: adopt any pre-ARROW_HOME data.
        migrate_legacy_home()
        db_path = default_db_path()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with get_db_connection(db_path) as conn:
        run_migrations(conn)
