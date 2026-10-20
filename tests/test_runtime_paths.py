import json
import os
import subprocess
import sys
from pathlib import Path


def test_frozen_app_data_is_outside_read_only_bundle(monkeypatch, tmp_path):
    from arrow.core import paths
    monkeypatch.delenv('ARROW_HOME', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'user')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'installed' / '_internal'), raising=False)
    assert paths.data_dir() == tmp_path / 'user' / '.arrow'
    assert paths.resource_dir() == tmp_path / 'installed' / '_internal'


def test_source_checkout_keeps_existing_data_location(monkeypatch):
    from arrow.core import paths
    monkeypatch.delenv('ARROW_HOME', raising=False)
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert paths.data_dir() == Path(__file__).resolve().parents[1]


def test_home_override_applies_to_config_and_data(monkeypatch, tmp_path):
    from arrow.core import paths
    from arrow.storage.settings import config_dir
    home = tmp_path / 'user data'
    monkeypatch.setenv('ARROW_HOME', str(home))
    assert paths.application_home() == home
    assert paths.data_dir() == home
    assert Path(config_dir()) == home
    assert home.is_dir()


def test_installed_storage_modules_share_writable_capture_directory(tmp_path):
    home = tmp_path / 'user data'
    installed = tmp_path / 'installed'
    installed.mkdir()
    installed.chmod(0o555)
    script = '''
import json, sys
sys.frozen = True
sys._MEIPASS = sys.argv[1]
from arrow.storage import database, capture_store
from arrow.capture import screenshot_service
from arrow.server import server
from arrow.storage.settings import config_dir
from pathlib import Path
Path(config_dir()).mkdir(parents=True, exist_ok=True)
database.init_db()
print(json.dumps({'db': database.DB_PATH, 'directories': [capture_store.SCREENSHOTS_DIR, screenshot_service.SCREENSHOTS_DIR, server.SCREENSHOTS_DIR]}))
'''
    result = subprocess.run([sys.executable, '-c', script, str(installed)],
                            env={**{key: value for key, value in os.environ.items() if key != 'ARROW_DB_PATH'},
                                 'ARROW_HOME': str(home)},
                            text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert Path(data['db']) == home / 'arrow.db'
    assert (home / 'arrow.db').exists()
    assert {Path(path) for path in data['directories']} == {home / 'screenshots'}
    assert list(installed.iterdir()) == []
