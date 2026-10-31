"""Tests for persisted application settings (arrow.storage.settings)."""

import json
import os

import pytest

from arrow.storage import settings


def test_project_dir_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / ".arrow"))
    project = tmp_path / "proj"
    project.mkdir()

    settings.set_project_dir(str(project))
    assert settings.get_project_dir() == os.path.abspath(str(project))


def test_invalid_dir_is_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / ".arrow"))
    settings.set_project_dir(str(tmp_path / "does-not-exist"))
    assert settings.get_project_dir() is None


def test_get_project_dir_returns_none_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / ".arrow"))
    assert settings.get_project_dir() is None


def test_config_dir_is_created(tmp_path, monkeypatch):
    home = str(tmp_path / "home")
    monkeypatch.setenv("ARROW_HOME", home)
    assert os.path.isdir(settings.config_dir())


@pytest.mark.parametrize('value', [['unexpected'], {'path': 'unexpected'}])
def test_invalid_saved_project_types_are_ignored_without_rewriting_config(tmp_path, monkeypatch, value):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    config = tmp_path / 'config.json'
    contents = json.dumps({'selected_project_dir': value, 'speech_language': 'hi-IN'})
    config.write_text(contents, encoding='utf-8')

    assert settings.get_project_dir() is None
    assert settings.get_speech_language() == 'hi-IN'
    assert config.read_text(encoding='utf-8') == contents


def test_unreadable_config_encoding_uses_defaults_without_destroying_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    config = tmp_path / 'config.json'
    contents = b'\xff\xfe{invalid settings encoding}'
    config.write_bytes(contents)

    assert settings.get_capture_shortcut() == 'ctrl+space'
    assert settings.get_speech_language() == 'en-IN'
    assert settings.get_project_dir() is None
    assert config.read_bytes() == contents
