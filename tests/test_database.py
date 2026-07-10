import json

import pytest

from arrow.storage.capture_store import CaptureStore
from arrow.storage.database import get_db_connection, init_db
from arrow.storage.schemas import CaptureRecord


@pytest.fixture
def test_db_path(tmp_path):
    db_file = tmp_path / "test_arrow.db"
    return str(db_file)

def test_database_initialization(test_db_path):
    # Initialize schema
    init_db(test_db_path)
    
    # Verify tables exist
    with get_db_connection(test_db_path) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t['name'] for t in tables}
        assert 'sessions' in table_names
        assert 'annotations' in table_names
        assert 'assets' in table_names
        assert 'contexts' in table_names

def test_capture_store_crud(test_db_path):
    store = CaptureStore(test_db_path)
    
    # Create a record
    record = CaptureRecord(
        id="test_cap_123",
        timestamp="2026-07-10T12:00:00",
        annotation_text="Test comment",
        screenshot_path="/fake/path/screenshot.png",
        cursor_x=100,
        cursor_y=200,
        window_title="Test Window"
    )
    
    # Add record
    store.add(record)
    
    # Retrieve record
    retrieved = store.get("test_cap_123")
    assert retrieved is not None
    assert retrieved.id == "test_cap_123"
    assert retrieved.annotation_text == "Test comment"
    assert retrieved.screenshot_path == "/fake/path/screenshot.png"
    assert retrieved.cursor_x == 100
    assert retrieved.window_title == "Test Window"
    
    # Get all records
    all_records = store.get_all()
    assert len(all_records) == 1
    assert all_records[0].id == "test_cap_123"
    
    # Update record
    retrieved.annotation_text = "Updated comment"
    store.update(retrieved)
    
    retrieved_updated = store.get("test_cap_123")
    assert retrieved_updated.annotation_text == "Updated comment"
    
    # Delete record
    store.delete("test_cap_123")
    assert store.get("test_cap_123") is None
    assert len(store.get_all()) == 0

def test_cascading_deletes(test_db_path):
    init_db(test_db_path)
    
    with get_db_connection(test_db_path) as conn:
        # Insert a session
        conn.execute('''
            INSERT INTO sessions (capture_id, created_at, updated_at, state, mode)
            VALUES (?, ?, ?, ?, ?)
        ''', ("cascade_test_id", "2026", "2026", "COMPLETED", "desktop"))
        
        # Insert asset and context
        conn.execute('''
            INSERT INTO assets (capture_id, path, type) VALUES (?, ?, ?)
        ''', ("cascade_test_id", "path.png", "screenshot"))
        
        conn.execute('''
            INSERT INTO contexts (capture_id, data) VALUES (?, ?)
        ''', ("cascade_test_id", json.dumps({"cursor_x": 0})))
        
        conn.commit()
        
        # Verify they exist
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 1
        
        # Delete session
        conn.execute("DELETE FROM sessions WHERE capture_id = ?", ("cascade_test_id",))
        conn.commit()
        
        # Verify cascaded deletes worked
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 0
