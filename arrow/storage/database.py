import contextlib
import os
import sqlite3
from typing import Optional

# Use a default database file in the project root
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("ARROW_DB_PATH", os.path.join(ROOT_DIR, "arrow.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    capture_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    mode TEXT NOT NULL,
    project_id TEXT,
    raw_instruction TEXT,
    voice_transcript TEXT,
    provider TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    path TEXT NOT NULL,
    type TEXT,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contexts (
    capture_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);
"""

@contextlib.contextmanager
def get_db_connection(db_path: Optional[str] = None):
    if db_path is None:
        db_path = DB_PATH
    
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
        conn.executescript(SCHEMA)
        conn.commit()
