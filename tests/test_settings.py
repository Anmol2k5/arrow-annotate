"""Tests for persisted application settings (arrow.storage.settings)."""

import os

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


def test_config_dir_honors_dotenv(tmp_path, monkeypatch):
    """ARROW_HOME in .env must reach settings, not just the real environment."""
    (tmp_path / ".env").write_text(f"ARROW_HOME={tmp_path / 'home-from-dotenv'}\n", encoding="utf-8")
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    monkeypatch.delenv("ARROW_HOME", raising=False)
    assert settings.config_dir() == str(tmp_path / "home-from-dotenv")
