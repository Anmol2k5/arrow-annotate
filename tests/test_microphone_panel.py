import json

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def panel(tmp_path, monkeypatch):
    from arrow.ui import microphone_panel
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    qt = QApplication.instance() or QApplication([])

    class Voice(QObject):
        phase_changed = pyqtSignal(str, str)
        audio_level = pyqtSignal(float, str)
        finished = pyqtSignal(str, str, str)

        def __init__(self, language, *, microphone_selection, max_recording_seconds):
            super().__init__()
            self.language, self.selection = language, microphone_selection
            self.limit = max_recording_seconds
            self.stopped, self.released = False, False

        def start_listening(self, capture_id):
            self.capture_id = capture_id

        def finish_listening(self):
            self.released = True

        def stop_listening(self):
            self.stopped = True

    monkeypatch.setattr(microphone_panel, 'VoiceInput', Voice)
    widget = microphone_panel.MicrophonePanel(language=lambda: 'auto')
    widget.show()
    qt.processEvents()
    yield widget, qt
    widget.cancel_test()
    widget.close()


def test_selection_persists_descriptor_without_volatile_index(panel, tmp_path):
    widget, qt = panel
    widget._apply_devices([{'name': 'USB mic', 'host_api': 'WASAPI', 'index': 19, 'ambiguous': False}], '')
    widget.device_combo.setCurrentIndex(1)
    widget.save_button.click()
    data = json.loads((tmp_path / 'config.json').read_text())
    assert data['microphone_selection'] == {'name': 'USB mic', 'host_api': 'WASAPI'}
    assert 'index' not in data['microphone_selection']


def test_explicit_test_uses_production_voice_events_and_plain_transcript(panel, tmp_path):
    widget, qt = panel
    assert widget._voice is None
    widget.test_button.click()
    voice = widget._voice
    assert voice.language == 'auto' and voice.selection is None and voice.limit == 10
    assert widget._state == 'opening'
    voice.phase_changed.emit('recording', voice.capture_id)
    assert widget._record_timer.isActive()
    voice.audio_level.emit(.42, voice.capture_id)
    assert widget.level_meter.value() == 42
    widget.stop_button.click()
    assert voice.released and not voice.stopped
    voice.phase_changed.emit('transcribing', voice.capture_id)
    assert 'locally' in widget.status_label.text()
    words = '<b>blue button नीचे रखो</b>'
    voice.finished.emit(words, '', voice.capture_id)
    assert widget.transcript_view.toPlainText() == words
    assert widget._state == 'idle'
    assert not list(tmp_path.iterdir()), 'Testing must not create a capture, audio file or preferences'


def test_cancel_ignores_old_results_after_a_new_test(panel):
    widget, qt = panel
    widget.test_button.click()
    old = widget._voice
    widget.cancel_button.click()
    assert old.stopped
    widget.test_button.click()
    current = widget._voice
    old.finished.emit('old words', '', old.capture_id)
    old.audio_level.emit(1., old.capture_id)
    assert widget._voice is current and widget._state == 'opening'
    assert not widget.transcript_view.toPlainText() and widget.level_meter.value() == 0


def test_normal_capture_blocks_testing_and_hiding_cancels_it(panel):
    widget, qt = panel
    widget.can_start_test = lambda: False
    widget.test_button.click()
    assert widget._voice is None and 'capture' in widget.status_label.text()
    widget.can_start_test = lambda: True
    widget.test_button.click()
    voice = widget._voice
    widget.hide()
    qt.processEvents()
    assert voice.stopped and widget._state == 'idle'


def test_recording_deadline_releases_and_quit_cancels(panel):
    widget, qt = panel
    widget.test_button.click()
    voice = widget._voice
    voice.phase_changed.emit('recording', voice.capture_id)
    assert widget._record_timer.interval() == 10_000
    widget._record_timer.timeout.emit()
    assert voice.released
    qt.aboutToQuit.emit()
    assert voice.stopped and widget._state == 'idle'


def test_saved_unavailable_device_is_preserved_and_duplicates_cannot_be_selected(panel):
    widget, qt = panel
    widget.device_combo.addItem('Saved USB', {'name': 'Saved USB', 'host_api': 'MME'})
    widget.device_combo.setCurrentIndex(1)
    widget._apply_devices([{'name': 'Duplicate', 'host_api': 'MME', 'index': 1, 'ambiguous': True}], '')
    assert widget.device_combo.currentData() == {'name': 'Saved USB', 'host_api': 'MME'}
    assert not widget.device_combo.model().item(1).isEnabled()


def test_device_refresh_is_inventory_only_and_keeps_unsaved_choice(panel, monkeypatch, tmp_path):
    from PyQt6.QtCore import QEventLoop, QTimer

    from arrow.ui import microphone_panel
    widget, qt = panel
    devices = [{'name': 'USB', 'host_api': 'WASAPI', 'index': 14, 'ambiguous': False}]
    monkeypatch.setattr(microphone_panel, 'list_input_devices', lambda: devices)
    widget.device_combo.addItem('Chosen', {'name': 'USB', 'host_api': 'WASAPI'})
    widget.device_combo.setCurrentIndex(1)
    loop = QEventLoop()
    widget.devices_loaded.connect(loop.quit)
    widget.refresh_button.click()
    QTimer.singleShot(1500, loop.quit)
    if widget._refreshing:
        loop.exec()
    qt.processEvents()
    assert not widget._refreshing
    assert widget.device_combo.currentData() == {'name': 'USB', 'host_api': 'WASAPI'}
    assert widget._voice is None and not list(tmp_path.iterdir())


def test_opening_timeout_cancels_and_ignores_late_recording(panel):
    widget, qt = panel
    widget.test_button.click()
    voice = widget._voice
    widget._opening_timer.timeout.emit()
    assert voice.stopped and widget._state == 'idle'
    assert 'did not open' in widget.status_label.text()
    voice.phase_changed.emit('recording', voice.capture_id)
    assert not widget._record_timer.isActive()


def test_navigation_away_from_capture_settings_cancels_test(panel):
    from arrow.ui.notch import DynamicNotch
    widget, qt = panel
    notch = DynamicNotch()
    notch.show_settings('Capture')
    qt.processEvents()
    microphone = notch._settings_view.microphone_panel
    microphone.test_button.click()
    voice = microphone._voice
    notch._settings_view.refresh_agents = lambda: None
    notch._settings_view.select_tab('Agents')
    qt.processEvents()
    assert voice.stopped and microphone._state == 'idle'
    notch.close()
