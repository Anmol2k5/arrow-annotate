"""Configuration loading and validation tests."""

from __future__ import annotations

import os

import pytest

from arrow.core.config import (
    ConfigError,
    env_value,
    load_config,
    load_dotenv,
    reset_config_cache,
    resolve_home,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Isolate each test from the developer's real environment and .env file."""
    for key in list(os.environ):
        if key.startswith("ARROW_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    reset_config_cache()
    yield
    reset_config_cache()


def test_defaults_are_loopback_and_standard_ports():
    cfg = load_config({})
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 5001
    assert cfg.ws_host == "127.0.0.1"
    assert cfg.ws_port == 5002
    assert cfg.agentation_url == "http://127.0.0.1:4747"
    assert cfg.log_level == "INFO"
    assert cfg.base_url == "http://127.0.0.1:5001"
    assert cfg.ws_url == "ws://127.0.0.1:5002"


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("ARROW_HTTP_PORT", "7001")
    monkeypatch.setenv("ARROW_WS_PORT", "7002")
    monkeypatch.setenv("ARROW_LOG_LEVEL", "debug")
    cfg = load_config()
    assert cfg.http_port == 7001
    assert cfg.ws_port == 7002
    assert cfg.log_level == "DEBUG"


def test_real_environment_beats_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ARROW_HTTP_PORT=8111\nARROW_WS_PORT=8112\n", encoding="utf-8")
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    monkeypatch.setenv("ARROW_HTTP_PORT", "9111")
    cfg = load_config()
    assert cfg.http_port == 9111   # real env wins
    assert cfg.ws_port == 8112     # dotenv fills the gap


@pytest.mark.parametrize("bad", ["0", "70000", "-1", "notaport", "65536"])
def test_invalid_ports_rejected(bad, monkeypatch):
    monkeypatch.setenv("ARROW_HTTP_PORT", bad)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ARROW_HTTP_PORT" in str(exc.value)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_non_loopback_hosts_rejected_by_default(host, monkeypatch):
    monkeypatch.setenv("ARROW_HTTP_HOST", host)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "loopback" in str(exc.value)


def test_non_loopback_allowed_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ARROW_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("ARROW_ALLOW_NON_LOOPBACK", "1")
    cfg = load_config()
    assert cfg.http_host == "0.0.0.0"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_accepted(host, monkeypatch):
    monkeypatch.setenv("ARROW_HTTP_HOST", host)
    assert load_config().http_host == host


def test_invalid_log_level_rejected(monkeypatch):
    monkeypatch.setenv("ARROW_LOG_LEVEL", "chatty")
    with pytest.raises(ConfigError):
        load_config()


def test_voice_transcription_defaults_to_google():
    cfg = load_config({})
    assert cfg.voice_transcription == "google"


def test_voice_transcription_off_accepted(monkeypatch):
    monkeypatch.setenv("ARROW_VOICE_TRANSCRIPTION", "off")
    assert load_config().voice_transcription == "off"


def test_invalid_voice_transcription_rejected(monkeypatch):
    monkeypatch.setenv("ARROW_VOICE_TRANSCRIPTION", "whisper-cloud")
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ARROW_VOICE_TRANSCRIPTION" in str(exc.value)


def test_load_dotenv_parses_quotes_comments_and_export(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export ARROW_HOME='/some/path'\n"
        'ARROW_LOG_LEVEL="warning"\n'
        "EMPTY=\n"
        "NO_EQUALS\n"
        "ARROW_HTTP_PORT=5005\n",
        encoding="utf-8",
    )
    values = load_dotenv(str(env_file))
    assert values["ARROW_HOME"] == "/some/path"
    assert values["ARROW_LOG_LEVEL"] == "warning"
    assert values["ARROW_HTTP_PORT"] == "5005"
    assert "NO_EQUALS" not in values


def test_load_dotenv_missing_file_is_empty(tmp_path):
    assert load_dotenv(str(tmp_path / "nope.env")) == {}


# ---------------------------------------------------------------------------
# env_value / resolve_home (uncached helpers for import-time consumers)
# ---------------------------------------------------------------------------


def test_env_value_prefers_real_env(monkeypatch):
    monkeypatch.setenv("ARROW_AGENTATION_URL", "http://127.0.0.1:9999")
    assert env_value("ARROW_AGENTATION_URL") == "http://127.0.0.1:9999"


def test_env_value_reads_dotenv_when_env_absent(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ARROW_AGENTATION_URL=http://127.0.0.1:8888\n", encoding="utf-8")
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    assert env_value("ARROW_AGENTATION_URL") == "http://127.0.0.1:8888"


def test_env_value_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    assert env_value("ARROW_NO_SUCH_KEY", "fallback") == "fallback"


def test_resolve_home_defaults_to_dot_arrow():
    assert resolve_home() == os.path.abspath(os.path.expanduser("~/.arrow"))


def test_resolve_home_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "data"))
    assert resolve_home() == str(tmp_path / "data")


def test_resolve_home_honors_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"ARROW_HOME={tmp_path / 'from-dotenv'}\n", encoding="utf-8")
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    assert resolve_home() == str(tmp_path / "from-dotenv")
