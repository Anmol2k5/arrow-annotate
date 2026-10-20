import contextlib
import os
import sqlite3
from typing import Optional

from arrow.core.paths import data_dir
from arrow.storage.migrations import run_migrations

# Installed applications store data beside user settings; source checkouts keep the original path.
ROOT_DIR = str(data_dir())
DB_PATH = os.environ.get("ARROW_DB_PATH", os.path.join(ROOT_DIR, "arrow.db"))


@contextlib.contextmanager
def get_db_connection(db_path: Optional[str] = None):
    if db_path is None:
        db_path = DB_PATH

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
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
        db_path = DB_PATH
    with get_db_connection(db_path) as conn:
        run_migrations(conn)
