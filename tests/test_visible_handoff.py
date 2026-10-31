from types import SimpleNamespace

from PIL import Image

from arrow.providers import handoff
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord


def test_codex_opens_interactive_with_image_and_per_session_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'state'))
    image = tmp_path / 'image.png'
    Image.new('RGB', (20, 20), 'red').save(image)
    db = str(tmp_path / 'captures.db')
    CaptureStore(db).add(CaptureRecord(id='one', timestamp='now', screenshot_path=str(image),
        annotation_text='move', change_request={'capture_id': 'one', 'raw_user_request': 'move',
            'project': {'repository_root': str(tmp_path)}, 'assets': {'annotated': str(image)}}))
    launched = []
    provider = SimpleNamespace(detect=lambda: True, _resolve_command=lambda args: args)
    monkeypatch.setattr(handoff, 'create_provider', lambda name: provider)
    monkeypatch.setattr(handoff.subprocess, 'Popen', lambda args, **kwargs: launched.append((args, kwargs)))
    result = handoff.handoff_capture('one', 'Codex', db)
    args, options = launched[0]
    assert args[0] == 'codex' and 'exec' not in args
    assert '--image' in args and '--cd' in args
    assert any('mcp_servers.arrow.command=' in arg for arg in args)
    assert 'arrow_get_capture_bundle' in args[-1]
    assert options['cwd'] == str(tmp_path) and options['shell'] is False
    assert result.status == 'started'
    assert 'completed' not in result.message.lower()
    assert not (tmp_path / 'state' / 'config.json').exists()


def test_status_remains_available_without_hostname_dns(monkeypatch):
    from arrow.server import server
    def fail(*args):
        raise OSError('No DNS')
    monkeypatch.setattr(server.socket, 'gethostbyname', fail)
    response = server.app.test_client().get('/status')
    assert response.status_code == 200
    assert response.json['status'] == 'healthy'
    assert response.json['ip'] == '127.0.0.1'


def test_gallery_refresh_preserves_copy_and_handoff_state(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    from arrow.ui.notch import ScreenshotsView
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('ARROW_DB_PATH', str(tmp_path / 'captures.db'))
    app = QApplication.instance() or QApplication([])
    image = tmp_path / 'saved.png'
    Image.new('RGB', (10, 10), 'blue').save(image)
    store = CaptureStore()
    store.add(CaptureRecord(id='one', timestamp='now', screenshot_path=str(image),
        annotation_text='Move this', change_request={'capture_id': 'one', 'raw_user_request': 'Move this'}))
    gallery = ScreenshotsView()
    card = gallery._thumbnails[0]
    card._copy_request()
    card._set_sending(True, 'Codex')
    gallery._scan_existing()
    assert gallery._thumbnails[0] is card
    assert card._combined_copy_button.text() == '2 · Copy prompt'
    assert not card._provider_buttons['send'].isEnabled()
    gallery.close()
    app.processEvents()


def test_mcp_child_reads_the_same_database_as_source_desktop(tmp_path, monkeypatch):
    from arrow.storage import database
    db = tmp_path / 'source-checkout' / 'arrow.db'
    monkeypatch.setattr(database, 'DB_PATH', str(db))
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'different-user-home'))
    assert handoff.mcp_server_config()['env']['ARROW_DB_PATH'] == str(db)
