import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_launcher(tmp_path, *args, input=None):
    return subprocess.run([sys.executable, str(ROOT / 'main.py'), *args], input=input,
                          env={**os.environ, 'ARROW_HOME': str(tmp_path / 'data')},
                          capture_output=True, text=True, timeout=20)


def test_entrypoint_import_is_safe_without_starting_desktop(tmp_path):
    result = subprocess.run([sys.executable, '-c', 'import main; print("imported")'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'imported'


def test_version_works_without_starting_desktop(tmp_path):
    result = run_launcher(tmp_path, '--version')
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('Arrow Annotate ')
    assert 'requires Windows' not in result.stdout


def test_console_mcp_mode_preserves_json_rpc_stdout(tmp_path):
    request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}) + '\n'
    result = run_launcher(tmp_path, '--mcp', input=request)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 1
    assert responses[0]['id'] == 1
    assert responses[0]['result']['serverInfo']['name'] == 'arrow-mcp'


def test_relaunch_does_not_start_a_second_desktop(monkeypatch, tmp_path):
    from PyQt6.QtCore import QLockFile

    from arrow import launcher
    home = tmp_path / 'data'
    home.mkdir()
    lock = QLockFile(str(home / 'desktop.lock'))
    assert lock.tryLock()
    monkeypatch.setenv('ARROW_HOME', str(home))
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    messages = []
    monkeypatch.setattr(launcher, '_show_message', lambda message: messages.append(message))
    try:
        assert launcher.entrypoint([]) == 0
        assert any('already running' in message.lower() for message in messages)
    finally:
        lock.unlock()


def test_startup_error_gets_a_log_and_visible_message(monkeypatch, tmp_path):
    import arrow.app
    from arrow import launcher
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    def fail():
        raise RuntimeError('missing packaged library')
    monkeypatch.setattr(arrow.app, 'main', fail)
    messages = []
    monkeypatch.setattr(launcher, '_show_message', lambda message: messages.append(message))
    assert launcher.entrypoint([]) == 1
    log = (tmp_path / 'logs' / 'ArrowAnnotate.log').read_text(encoding='utf-8')
    assert 'missing packaged library' in log
    assert any('ArrowAnnotate.log' in message for message in messages)
    assert not (tmp_path / 'desktop.lock').exists()


def test_nonzero_startup_exit_is_logged_and_shown(monkeypatch, tmp_path):
    import arrow.app
    from arrow import launcher
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Windows')
    def fail():
        raise SystemExit(1)
    monkeypatch.setattr(arrow.app, 'main', fail)
    messages = []
    monkeypatch.setattr(launcher, '_show_message', lambda message: messages.append(message))
    assert launcher.entrypoint([]) == 1
    assert any('ArrowAnnotate.log' in message for message in messages)
    assert 'exit code 1' in (tmp_path / 'logs' / 'ArrowAnnotate.log').read_text()
