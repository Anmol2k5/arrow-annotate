"""Tests for arrow.capture.context_file (latest context mirror)."""

import os

from arrow.capture import context_file


def test_latest_dir_defaults_under_dot_arrow(monkeypatch):
    monkeypatch.delenv("ARROW_HOME", raising=False)
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: "C:\\nonexistent-dir-for-tests")
    expected = os.path.abspath(os.path.join(os.path.expanduser("~"), ".arrow", "latest"))
    assert context_file.latest_dir() == expected


def test_latest_dir_honors_arrow_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "arrow-home"))
    assert context_file.latest_dir() == str(tmp_path / "arrow-home" / "latest")


def test_latest_dir_honors_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"ARROW_HOME={tmp_path / 'dotenv-home'}\n", encoding="utf-8")
    monkeypatch.setattr("arrow.core.config.os.getcwd", lambda: str(tmp_path))
    monkeypatch.delenv("ARROW_HOME", raising=False)
    assert context_file.latest_dir() == str(tmp_path / "dotenv-home" / "latest")


def test_mirror_latest_writes_context_under_latest_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "home"))
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png-bytes")
    dst = context_file.mirror_latest(str(shot), "# context\n", "cap-1")
    assert dst == str(tmp_path / "home" / "latest")
    with open(os.path.join(dst, "context.md"), encoding="utf-8") as f:
        assert f.read() == "# context\n"
    assert os.path.isfile(os.path.join(dst, "capture.png"))
