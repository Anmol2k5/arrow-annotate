import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from arrow import launcher


@pytest.fixture
def fresh_desktop_imports(monkeypatch):
    """The small fake runners below model a fresh process without importing app state."""
    from arrow import startup_smoke

    monkeypatch.setattr(startup_smoke, '_imported_desktop_modules', lambda: [])


def test_desktop_smoke_reports_unsupported_without_starting_app(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Linux')
    report = tmp_path / 'report.json'
    assert launcher.entrypoint(['--desktop-smoke', str(report)]) == 2
    data = json.loads(report.read_text())
    assert data['status'] == 'unsupported'
    assert data['success'] is False
    assert not (tmp_path / 'data').exists()


def test_desktop_smoke_startup_failure_is_reported_without_modal_dialog(monkeypatch, tmp_path, fresh_desktop_imports):
    from arrow import startup_smoke

    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    monkeypatch.delenv('ARROW_HOME', raising=False)
    homes = []

    def fail(*, startup_observer, error_handler):
        homes.append(os.environ['ARROW_HOME'])
        error_handler('occupied local server port')
        return 1

    monkeypatch.setattr(launcher, '_run_desktop', fail)
    report = tmp_path / 'report.json'
    assert startup_smoke.run_desktop_smoke(report) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'failed'
    assert 'occupied local server port' in json.dumps(data)
    assert 'ARROW_HOME' not in os.environ
    assert not os.path.exists(homes[0])


def test_smoke_cannot_pass_without_observer_and_preserves_explicit_home(monkeypatch, tmp_path):
    from arrow import startup_smoke

    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    home = tmp_path / 'persistent'
    monkeypatch.setenv('ARROW_HOME', str(home))
    monkeypatch.setattr(launcher, '_run_desktop', lambda **kwargs: 0)
    report = tmp_path / 'report.json'
    assert startup_smoke.run_desktop_smoke(report) == 1
    assert json.loads(report.read_text())['success'] is False
    assert os.environ['ARROW_HOME'] == str(home)


def test_isolated_windowed_smoke_releases_log_streams_before_deleting_home(monkeypatch, tmp_path, fresh_desktop_imports):
    from arrow import startup_smoke

    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    monkeypatch.delenv('ARROW_HOME', raising=False)
    streams = []

    def fail(*, startup_observer, error_handler):
        launcher._desktop_logging()
        streams.append(sys.stdout)
        error_handler('synthetic startup failure')
        return 1

    monkeypatch.setattr(launcher, '_run_desktop', fail)
    with monkeypatch.context() as windowed:
        windowed.setattr(sys, 'stdout', None)
        windowed.setattr(sys, 'stderr', None)
        assert startup_smoke.run_desktop_smoke(tmp_path / 'report.json') == 1
        assert sys.stdout is None and sys.stderr is None
        assert streams[0].closed


@pytest.mark.parametrize('preimport_database', [False, True])
def test_isolated_smoke_never_migrates_inherited_external_database(tmp_path, preimport_database):
    external = tmp_path / 'personal.db'
    with sqlite3.connect(external) as connection:
        connection.execute('CREATE TABLE personal_data (content TEXT)')
        connection.execute("INSERT INTO personal_data VALUES ('preserve my database')")
    before = external.read_bytes()
    report = tmp_path / 'report.json'
    script = textwrap.dedent('''
        import json
        import os
        import sys
        from pathlib import Path
        from arrow import launcher, startup_smoke

        if sys.argv[2] == 'True':
            import arrow.storage.database
        launcher.platform.system = lambda: 'Windows'
        observed = {}
        original_db = os.environ['ARROW_DB_PATH']

        def initialize(*, startup_observer, error_handler):
            from arrow.storage import database
            from arrow.storage.capture_store import CaptureStore
            CaptureStore()
            observed['database'] = str(Path(database.DB_PATH).resolve())
            observed['home'] = str(Path(os.environ['ARROW_HOME']).resolve())
            return 1

        launcher._run_desktop = initialize
        assert startup_smoke.run_desktop_smoke(Path(sys.argv[1])) == 1
        assert os.environ['ARROW_DB_PATH'] == original_db
        assert 'ARROW_HOME' not in os.environ
        print(json.dumps(observed))
    ''')
    environment = {**os.environ, 'ARROW_DB_PATH': str(external)}
    environment.pop('ARROW_HOME', None)
    result = subprocess.run([sys.executable, '-c', script, str(report), str(preimport_database)],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert external.read_bytes() == before
    data = json.loads(report.read_text())
    assert data['status'] == 'failed'
    observed = json.loads(result.stdout)
    if preimport_database:
        assert observed == {}
        assert any(check['name'] == 'fresh_process' and check['status'] == 'failed'
                   for check in data['checks'])
    else:
        assert Path(observed['database']).parent == Path(observed['home'])
        assert not Path(observed['home']).exists()


def test_occupied_desktop_lock_fails_smoke_without_a_message_box(monkeypatch, tmp_path):
    from PyQt6.QtCore import QLockFile

    from arrow import startup_smoke

    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    lock = QLockFile(str(tmp_path / 'desktop.lock'))
    assert lock.tryLock()

    def unexpected_modal(message):
        raise AssertionError('Smoke mode must never open a modal message box')

    monkeypatch.setattr(launcher, '_show_message', unexpected_modal)
    report = tmp_path / 'report.json'
    try:
        assert startup_smoke.run_desktop_smoke(report) == 1
        data = json.loads(report.read_text())
        assert data['status'] == 'failed'
        assert 'already running' in json.dumps(data)
    finally:
        lock.unlock()


def test_lifecycle_probe_uses_real_qt_tray_handlers_and_quit(monkeypatch, tmp_path):
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

    from arrow import startup_smoke
    from arrow.ui.tray import install_tray

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    monkeypatch.setattr(QGuiApplication, 'platformName', lambda: 'windows')
    monkeypatch.setattr(startup_smoke, '_native_visible', lambda widget: widget.isVisible())
    notch = QWidget()
    notch.expand = lambda: None
    notch.show()
    tray = install_tray(app, notch, lambda: None, lambda: None)
    app.setQuitOnLastWindowClosed(False)
    server = SimpleNamespace(_running=True, _thread=None, ws_bridge=None)
    app.aboutToQuit.connect(lambda: setattr(server, '_running', False))
    app.aboutToQuit.connect(tray.hide)
    probe = startup_smoke.DesktopLifecycleProbe()
    probe.observe(app, notch, tray, server, SimpleNamespace(_listening=False))
    assert app.exec() == 0
    probe.check_cleanup()
    assert probe.passed, probe.checks
    assert not tray.isVisible()
    assert not server._running
    notch.close()


def test_lifecycle_callback_failure_quits_and_reports_failure(monkeypatch):
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication, QWidget

    from arrow import startup_smoke

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QGuiApplication, 'platformName', lambda: 'windows')
    monkeypatch.setattr(startup_smoke, '_native_visible', lambda widget: True)
    notch = QWidget()
    notch.show()
    probe = startup_smoke.DesktopLifecycleProbe()
    probe.observe(app, notch, None, SimpleNamespace(_running=True), SimpleNamespace(_listening=False))
    assert app.exec() == 0
    assert not probe.passed
    assert any(check['status'] == 'failed' for check in probe.checks)
    notch.close()
