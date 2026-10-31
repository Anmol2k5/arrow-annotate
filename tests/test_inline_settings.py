import json
from threading import Event
from types import SimpleNamespace

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from arrow.storage import settings
from arrow.ui.notch import DynamicNotch


def test_agents_can_copy_the_actual_local_mcp_endpoint_without_exposing_token_in_labels(tmp_path, monkeypatch):
    from arrow.server.security import TokenManager
    from arrow.server.server import app as server_app
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    tokens = TokenManager(str(tmp_path / 'token'))
    monkeypatch.setitem(server_app.config, 'TOKEN_MANAGER', tokens)
    qt = QApplication.instance() or QApplication([])
    notch = DynamicNotch(server=SimpleNamespace(_running=True, base_url='http://127.0.0.1:54321'))
    panel = notch._settings_view
    panel._refresh_endpoint()
    assert '54321/mcp' in panel.endpoint_status.text()
    assert tokens.get_or_create() not in panel.endpoint_status.text()
    panel.copy_mcp_button.click()
    config = json.loads(qt.clipboard().text())['mcpServers']['arrow']
    assert config['url'] == 'http://127.0.0.1:54321/mcp'
    assert config['headers']['Authorization'] == 'Bearer ' + tokens.get_or_create()
    notch.close()


def test_settings_replace_captures_inside_the_same_notch(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    assert callable(getattr(notch, 'show_settings', None)), 'Settings must open inside the notch'
    notch.show_settings()
    app.processEvents()
    panel = notch._settings_view
    assert notch.isAncestorOf(panel)
    assert notch._content_stack.currentWidget() is panel
    assert not notch.findChildren(QDialog)
    assert panel.shortcut_input.text() == 'ctrl+space'
    panel.close_requested.emit()
    assert notch._content_stack.currentWidget() is notch._screens_view
    notch.close()


def test_inline_capture_errors_preserve_config_and_remain_visible(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    assert callable(getattr(notch, 'show_settings', None))
    notch.show_settings()
    panel = notch._settings_view

    def reject(shortcut, language):
        raise ValueError('Shortcut conflicts with capture controls')

    notch.on_capture_preferences_changed = reject
    panel.shortcut_input.setText('esc')
    panel._save_capture()
    assert 'conflicts' in panel.capture_status.text()
    assert settings.get_capture_shortcut() == 'ctrl+space'
    assert notch._content_stack.currentWidget() is panel
    app.processEvents()
    notch.close()


def test_general_preferences_round_trip_without_losing_capture_or_repository(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'config'))
    settings.set_project_dir(str(tmp_path))
    settings.set_capture_preferences('ctrl+shift', 'hi-IN')
    assert callable(getattr(settings, 'set_ui_preferences', None))
    settings.set_ui_preferences(clipboard_mode='combined', auto_expand_capture=False, keep_notch_open=True)
    assert settings.get_ui_preferences() == {
        'clipboard_mode': 'combined', 'auto_expand_capture': False, 'keep_notch_open': True,
    }
    assert settings.get_project_dir() == str(tmp_path)
    assert settings.get_capture_shortcut() == 'ctrl+shift'
    assert settings.get_speech_language() == 'hi-IN'


def test_agents_probe_sign_in_and_refresh_only_after_login_exits(tmp_path, monkeypatch):
    from arrow.providers import setup

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    signed_in = {'value': False}
    monkeypatch.setattr(setup, 'get_provider_setup_status', lambda name: setup.ProviderSetupStatus(
        name, True, signed_in['value'], 'Checked by CLI',
    ))
    process = SimpleNamespace(poll=lambda: None)
    logins = []
    monkeypatch.setattr(setup, 'start_provider_login', lambda name: logins.append(name) or process)
    notch = DynamicNotch()
    notch.show_settings('Agents')
    panel = notch._settings_view

    def finish_probe():
        if not panel._checking:
            return
        loop = QEventLoop()
        panel.agents_checked.connect(loop.quit)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        assert not panel._checking

    finish_probe()
    label, button = panel.agent_rows['Codex']
    assert 'Sign in required' in label.text()
    assert button.isEnabled()
    button.click()
    assert logins == ['Codex']
    assert not button.isEnabled()
    assert 'Finish sign-in' in label.text()
    panel._poll_logins()
    assert 'Connected' not in label.text()
    signed_in['value'] = True
    process.poll = lambda: 0
    panel._poll_logins()
    finish_probe()
    assert 'CLI signed in' in label.text()
    assert 'not checked' in panel.mcp_rows['Codex'][0].text()
    assert button.isEnabled()
    assert not panel._login_timer.isActive()
    app.processEvents()
    notch.close()


def test_general_notch_controls_apply_without_replacing_the_settings_page(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    notch.show_settings('General')
    panel = notch._settings_view
    panel.keep_open.setChecked(True)
    panel.auto_expand.setChecked(False)
    panel._save_general()
    assert notch._docked
    assert notch._content_stack.currentWidget() is panel
    notch.show_captures()
    notch.set_docked(False)
    notch.collapse()
    notch.set_status('Capture ready')
    assert notch._state == 'idle'
    app.processEvents()
    notch.close()


def test_login_completion_during_a_status_probe_queues_a_fresh_check(tmp_path, monkeypatch):
    from arrow.providers import setup

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    sampled, release = Event(), Event()
    signed_in = {'value': False}
    calls = []

    def probe(name):
        calls.append(name)
        status = setup.ProviderSetupStatus(name, True, signed_in['value'], 'CLI checked')
        if name == 'Claude Code' and not release.is_set():
            sampled.set()
            release.wait(2)
        return status

    monkeypatch.setattr(setup, 'get_provider_setup_status', probe)
    notch = DynamicNotch()
    notch.show_settings('Agents')
    panel = notch._settings_view
    assert sampled.wait(1)
    signed_in['value'] = True
    panel._login_processes['Codex'] = SimpleNamespace(poll=lambda: 0)
    panel._poll_logins()
    release.set()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if not panel._checking else None)
    timer.start()
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    timer.stop()
    assert calls.count('Codex') == 2
    assert 'CLI signed in' in panel.agent_rows['Codex'][0].text()
    app.processEvents()
    notch.close()


def test_one_click_mcp_setup_keeps_account_status_separate(tmp_path, monkeypatch):
    from arrow.providers import connection
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    qt = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    panel = notch._settings_view
    panel.agent_rows['Codex'][0].setText('CLI signed in')
    calls = []
    def setup(name):
        calls.append('configure')
        return connection.ProviderMCPStatus(name, True, True, None, 'Registered')
    def probe(name):
        calls.append('probe')
        return connection.ProviderMCPStatus(name, True, True, True, 'Local handshake passed')
    monkeypatch.setattr(connection, 'configure_provider_mcp', setup)
    monkeypatch.setattr(connection, 'probe_provider_mcp', probe)
    panel._check_mcp('Codex', configure=True)
    loop = QEventLoop()
    panel.mcp_checked.connect(loop.quit)
    QTimer.singleShot(1500, loop.quit)
    if panel._mcp_busy:
        loop.exec()
    qt.processEvents()
    assert calls == ['configure', 'probe']
    assert 'local protocol verified' in panel.mcp_rows['Codex'][0].text()
    assert panel.agent_rows['Codex'][0].text() == 'CLI signed in'
    notch.close()


def test_voice_download_ui_cancels_and_allows_retry(tmp_path, monkeypatch):
    from arrow.speech import offline
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    qt = QApplication.instance() or QApplication([])
    started = Event()
    def download(**kwargs):
        kwargs['progress']({'phase': 'downloading', 'downloaded_bytes': 50, 'total_bytes': 100})
        started.set()
        assert kwargs['cancel_event'].wait(2)
        raise offline.DownloadCancelled('Download cancelled. Retry is available.')
    monkeypatch.setattr(offline, 'install_voice_model', download)
    notch = DynamicNotch()
    panel = notch._settings_view
    panel._install_voice_model()
    assert started.wait(1)
    qt.processEvents()
    assert panel.voice_progress.value() == 50
    panel._cancel_voice_download()
    loop = QEventLoop()
    panel.voice_model_finished.connect(loop.quit)
    QTimer.singleShot(1500, loop.quit)
    if panel._voice_installing:
        loop.exec()
    qt.processEvents()
    assert not panel._voice_installing
    assert panel.voice_model_button.isEnabled()
    assert 'Retry' in panel.voice_model_status.text()
    notch.close()


def test_update_check_shows_notification_and_opens_no_browser_automatically(tmp_path, monkeypatch):
    from arrow.core import updates
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    qt = QApplication.instance() or QApplication([])
    monkeypatch.setattr(updates, 'check_for_update', lambda version: updates.UpdateResult('9.0.0', updates.RELEASES_URL, True))
    notch = DynamicNotch()
    panel = notch._settings_view
    panel._check_updates()
    loop = QEventLoop()
    panel.update_checked.connect(loop.quit)
    QTimer.singleShot(1500, loop.quit)
    if not panel.update_button.isEnabled():
        loop.exec()
    qt.processEvents()
    assert '9.0.0' in panel.update_status.text() and 'available' in panel.update_status.text()
    assert panel.update_button.isEnabled()
    notch.close()
