"""Regression checks across the desktop storage and MCP boundary."""

import base64

from arrow.mcp.resources import ResourceProvider
from arrow.mcp.tools import ArrowTools
from arrow.storage.capture_store import CaptureStore
from arrow.storage.database import get_db_connection
from arrow.storage.repository import Repository
from arrow.storage.schemas import CaptureRecord


def make_record(tmp_path):
    assets = {}
    for name in ('raw', 'annotated', 'context_crop', 'source_crop', 'destination_crop'):
        path = tmp_path / f'{name}.png'
        path.write_bytes(name.encode())
        assets[name] = str(path)
    return CaptureRecord(
        id='capture-1', timestamp='2026-10-14T00:00:00+00:00',
        screenshot_path=assets['annotated'], annotation_text='Make this wider',
        change_request={'capture_id': 'capture-1', 'summary': 'Resize button',
                        'application_mode': 'web', 'assets': assets},
    )


def test_desktop_capture_is_available_to_mcp(tmp_path):
    db = str(tmp_path / 'arrow.db')
    record = make_record(tmp_path)
    CaptureStore(db).add(record)
    tools = ArrowTools(Repository(db))
    assert tools.call('arrow_get_latest_change_request') == record.change_request
    resources = ResourceProvider(Repository(db))
    uris = {r['uri'] for r in resources.list_resources()}
    for name, path in record.change_request['assets'].items():
        uri = f"arrow://captures/{record.id}/{name.replace('_', '-')}"
        assert uri in uris
        assert base64.b64decode(resources.read_resource(uri)['blob']) == open(path, 'rb').read()


def test_edit_updates_mcp_without_resetting_agent_status(tmp_path):
    db = str(tmp_path / 'arrow.db')
    store = CaptureStore(db)
    record = make_record(tmp_path)
    store.add(record)
    repo = Repository(db)
    repo.set_status(record.id, 'running')
    revised = {**record.change_request, 'summary': 'Move button'}
    store.update_change_request(record.id, revised, 'Move it')
    assert repo.get_capture(record.id)['change_request'] == revised
    assert repo.get_capture(record.id)['status'] == 'running'
    assert store.get(record.id).annotation_text == 'Move it'


def test_desktop_delete_removes_all_capture_assets(tmp_path):
    db = str(tmp_path / 'arrow.db')
    store = CaptureStore(db)
    record = make_record(tmp_path)
    store.add(record)
    store.delete(record.id)
    assert store.get(record.id) is None
    assert Repository(db).get_capture(record.id) is None
    assert all(not __import__('os').path.exists(p) for p in record.change_request['assets'].values())


def test_upgrade_makes_legacy_desktop_captures_available_to_mcp(tmp_path):
    import json
    import sqlite3

    from arrow.storage.migrations import MIGRATIONS

    db = str(tmp_path / 'arrow.db')
    record = make_record(tmp_path)
    with sqlite3.connect(db) as conn:
        for version, sql in MIGRATIONS:
            if version <= 2:
                conn.executescript(sql)
                conn.execute(f'PRAGMA user_version = {version}')
        conn.execute("INSERT INTO sessions (capture_id, created_at, updated_at, state, mode) VALUES (?, ?, ?, 'COMPLETED', 'desktop')",
                     (record.id, record.timestamp, record.timestamp))
        conn.execute('INSERT INTO contexts (capture_id, data) VALUES (?, ?)',
                     (record.id, json.dumps({'change_request': json.dumps(record.change_request)})))
    repo = Repository(db)
    assert repo.get_capture(record.id)['change_request'] == record.change_request
    assert repo.get_asset_path(record.id, 'context-crop') == record.change_request['assets']['context_crop']
    with get_db_connection(db) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] >= 3
