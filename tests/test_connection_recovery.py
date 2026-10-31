from threading import Event

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from arrow.providers import setup
from arrow.ui.settings_panel import SettingsPanel


def wait_for_probe(panel):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if panel.refresh_agents_button.isEnabled() else None)
    timer.start()
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    timer.stop()


def test_failed_connection_probe_keeps_other_clients_usable_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    failed = Event()

    def probe(name):
        if name == 'Codex' and not failed.is_set():
            failed.set()
            raise PermissionError('private auth-store details must not appear in the UI')
        return setup.ProviderSetupStatus(name, True, True, 'Connected.')

    monkeypatch.setattr(setup, 'get_provider_setup_status', probe)
    thread_errors = []
    monkeypatch.setattr('threading.excepthook', lambda args: thread_errors.append(args.exc_type))
    panel = SettingsPanel(lambda *_: None)
    try:
        panel.select_tab('Agents')
        wait_for_probe(panel)
        assert panel.refresh_agents_button.isEnabled()
        assert not thread_errors
        assert 'CLI signed in' in panel.agent_rows['Claude Code'][0].text()
        assert panel.agent_rows['Claude Code'][1].isEnabled()
        error = panel.agent_rows['Codex'][0].text()
        assert 'retry' in error.lower() or 'refresh' in error.lower()
        assert 'private auth-store' not in error
        assert 'CLI not installed' not in error

        panel.refresh_agents_button.click()
        wait_for_probe(panel)
        assert 'CLI signed in' in panel.agent_rows['Codex'][0].text()
        assert panel.agent_rows['Codex'][1].isEnabled()
    finally:
        panel.close()
        app.processEvents()
