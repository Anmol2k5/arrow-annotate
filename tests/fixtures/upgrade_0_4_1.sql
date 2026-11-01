-- Frozen from v0.4.1:arrow/storage/migrations.py (migrations 1–3).
-- Do not replace this released baseline with current MIGRATIONS.

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


CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_requests (
    capture_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project_id TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    data TEXT NOT NULL,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    role TEXT NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS context_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    role TEXT,
    source TEXT,
    confidence REAL,
    data TEXT NOT NULL,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT,
    error TEXT,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    detail TEXT,
    FOREIGN KEY(capture_id) REFERENCES sessions(capture_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS pending_asset_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    capture_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_capture ON assets(capture_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_created ON change_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_status_history_capture ON status_history(capture_id);


INSERT OR IGNORE INTO change_requests
    (capture_id, created_at, updated_at, project_id, status, data)
SELECT s.capture_id, s.created_at, s.updated_at, s.project_id, 'ready',
       json_extract(c.data, '$.change_request')
FROM sessions s JOIN contexts c ON c.capture_id = s.capture_id
WHERE json_valid(c.data)
  AND json_valid(json_extract(c.data, '$.change_request'))
  AND json_type(json_extract(c.data, '$.change_request')) = 'object';

INSERT INTO assets (capture_id, path, type)
SELECT cr.capture_id, a.value, replace(a.key, '_', '-')
FROM change_requests cr, json_each(
    CASE WHEN json_valid(cr.data) THEN cr.data ELSE '{}' END, '$.assets'
) a
WHERE a.type = 'text' AND a.value != ''
  AND NOT EXISTS (
      SELECT 1 FROM assets existing
      WHERE existing.capture_id = cr.capture_id
        AND existing.type = replace(a.key, '_', '-')
  );

PRAGMA user_version = 3;
