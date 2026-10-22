from threading import Event
from types import SimpleNamespace

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from arrow.storage import settings
from arrow.ui.notch import DynamicNotch


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
    assert 'Connected' in label.text()
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
    assert 'Connected' in panel.agent_rows['Codex'][0].text()
    app.processEvents()
    notch.close()
