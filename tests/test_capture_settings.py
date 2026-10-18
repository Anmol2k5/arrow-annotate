import json

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from arrow.storage import settings
from arrow.ui.settings_dialog import CaptureSettingsDialog


def test_capture_preferences_default_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    assert settings.get_capture_shortcut() == 'ctrl+space'
    assert settings.get_speech_language() == 'en-IN'


def test_capture_preferences_round_trip_preserves_selected_project(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'settings'))
    settings.set_project_dir(str(tmp_path))
    settings.set_capture_preferences('ctrl+shift', 'hi-IN')
    assert settings.get_capture_shortcut() == 'ctrl+shift'
    assert settings.get_speech_language() == 'hi-IN'
    assert settings.get_project_dir() == str(tmp_path)
    settings.set_project_dir(str(tmp_path.parent))
    assert settings.get_capture_shortcut() == 'ctrl+shift'
    assert settings.get_speech_language() == 'hi-IN'


def test_invalid_persisted_capture_values_use_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    (tmp_path / 'config.json').write_text(json.dumps({'capture_shortcut': [], 'speech_language': None}))
    assert settings.get_capture_shortcut() == 'ctrl+space'
    assert settings.get_speech_language() == 'en-IN'


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_dialog_edits_modifier_only_shortcut_and_language(qt_app):
    dialog = CaptureSettingsDialog('ctrl+shift', 'hi-IN')
    assert dialog.values() == ('ctrl+shift', 'hi-IN')
    dialog.shortcut_input.setText('alt+a')
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData('en-US'))
    assert dialog.values() == ('alt+a', 'en-US')
    instructions = ' '.join(label.text() for label in dialog.findChildren(QLabel)).lower()
    assert 'hold' in instructions and 'release' in instructions and 'fn' in instructions
    dialog.close()


def test_dialog_restores_defaults(qt_app):
    dialog = CaptureSettingsDialog('alt+a', 'hi-IN')
    restore = next(button for button in dialog.findChildren(QPushButton) if 'default' in button.text().lower())
    restore.click()
    assert dialog.values() == ('ctrl+space', 'en-IN')
    dialog.close()


def test_failed_settings_write_preserves_valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    settings.set_capture_preferences('ctrl+space', 'en-IN')
    path = tmp_path / 'config.json'
    original = path.read_text()

    def fail_write(data, stream, **kwargs):
        stream.write('{partial')
        raise OSError('Disk full')

    monkeypatch.setattr(settings.json, 'dump', fail_write)
    with pytest.raises(OSError, match='Disk full'):
        settings.set_capture_preferences('ctrl+shift', 'hi-IN')
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]
