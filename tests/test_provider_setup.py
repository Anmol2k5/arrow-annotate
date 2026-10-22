"""Provider account setup never starts real agent or login subprocesses in tests."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from arrow.providers import ClaudeProvider, CodexProvider, base, setup


@pytest.fixture
def probes(monkeypatch):
    calls = []
    response = SimpleNamespace(returncode=0, stdout='', stderr='')

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return response

    monkeypatch.setattr(setup.subprocess, 'run', run)
    return calls, response


def installed(monkeypatch, name='Claude Code'):
    cls = ClaudeProvider if name == 'Claude Code' else CodexProvider
    executable = '/installed with spaces/' + cls.cli_name + '.exe'
    provider = cls(which_fn=lambda command: executable if command == cls.cli_name else None)
    monkeypatch.setattr(setup, 'create_provider', lambda _: provider)
    return executable


@pytest.mark.parametrize('name', ['Claude Code', 'Codex'])
def test_missing_cli_is_not_connected_or_probed(monkeypatch, probes, name):
    cls = ClaudeProvider if name == 'Claude Code' else CodexProvider
    monkeypatch.setattr(setup, 'create_provider', lambda _: cls(which_fn=lambda _: None))
    status = setup.get_provider_setup_status(name)
    assert status.name == name
    assert status.installed is False
    assert status.authenticated is False
    assert 'install' in status.message.lower()
    assert not probes[0]


@pytest.mark.parametrize(('logged_in', 'returncode'), [(True, 0), (False, 1)])
def test_claude_authentication_uses_explicit_json_boolean(monkeypatch, probes, logged_in, returncode):
    executable = installed(monkeypatch)
    calls, response = probes
    response.returncode = returncode
    response.stdout = json.dumps({'loggedIn': logged_in, 'email': 'private@example.com'})
    status = setup.get_provider_setup_status('Claude Code')
    assert status.installed is True
    assert status.authenticated is logged_in
    assert ('connected' if logged_in else 'sign in') in status.message.lower()
    assert 'private@example.com' not in status.message
    command, options = calls[0]
    assert command == [executable, 'auth', 'status', '--json']
    assert options['timeout'] <= 10
    assert options['stdin'] == subprocess.DEVNULL
    assert options['stdout'] == subprocess.PIPE
    assert options['stderr'] == subprocess.PIPE
    assert options['shell'] is False
    assert options['cwd'] == str(Path.home())


@pytest.mark.parametrize('stdout', ['hello', '{}', '[]', '{"loggedIn": 1}', '{"loggedIn": "true"}'])
def test_claude_installed_with_unrecognized_status_is_auth_unknown(monkeypatch, probes, stdout):
    installed(monkeypatch)
    probes[1].stdout = stdout
    status = setup.get_provider_setup_status('Claude Code')
    assert status.installed is True
    assert status.authenticated is None
    assert 'not confirmed' in status.message.lower()


def test_claude_nonzero_error_cannot_look_connected_from_json(monkeypatch, probes):
    installed(monkeypatch)
    probes[1].stdout = '{"loggedIn": true}'
    probes[1].returncode = 2
    assert setup.get_provider_setup_status('Claude Code').authenticated is None


@pytest.mark.parametrize(('output', 'returncode', 'expected'), [
    ('Logged in using ChatGPT', 0, True),
    ('Logged in using an API key - private', 0, True),
    ('API key configured - private', 0, True),
    ('Not logged in', 1, False),
    ('Error checking login status: private', 1, None),
    ('some help text', 0, None),
    ('Logged in using ChatGPT', 1, None),
])
def test_codex_authentication_status(monkeypatch, probes, output, returncode, expected):
    executable = installed(monkeypatch, 'Codex')
    probes[1].stderr = output
    probes[1].returncode = returncode
    status = setup.get_provider_setup_status('Codex')
    assert probes[0][0][0] == [executable, 'login', 'status']
    assert status.installed is True
    assert status.authenticated is expected
    assert 'private' not in status.message


@pytest.mark.parametrize('name', ['Claude Code', 'Codex'])
def test_unsupported_auth_command_is_not_a_signed_in_account(monkeypatch, probes, name):
    installed(monkeypatch, name)
    probes[1].stderr = "error: unknown command 'auth'"
    probes[1].returncode = 2
    status = setup.get_provider_setup_status(name)
    assert status.installed is True
    assert status.authenticated is None
    assert 'update' in status.message.lower()


@pytest.mark.parametrize('exception', [
    subprocess.TimeoutExpired('status', 8),
    OSError('sensitive implementation detail'),
])
def test_status_probe_errors_are_bounded_and_do_not_expose_output(monkeypatch, exception):
    installed(monkeypatch)

    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(setup.subprocess, 'run', fail)
    status = setup.get_provider_setup_status('Claude Code')
    assert status.installed is True
    assert status.authenticated is None
    assert 'sensitive' not in status.message


@pytest.mark.parametrize(('name', 'args'), [('Claude Code', ['auth', 'login']), ('Codex', ['login'])])
def test_login_starts_official_command_in_new_windows_console(monkeypatch, name, args):
    executable = installed(monkeypatch, name)
    monkeypatch.setattr(setup.sys, 'platform', 'win32')
    calls = []
    process = SimpleNamespace(poll=lambda: None)

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(setup.subprocess, 'Popen', popen)
    assert setup.start_provider_login(name) is process
    command, options = calls[0]
    assert command == [executable, *args]
    assert options['shell'] is False
    assert options['creationflags'] & 0x10  # CREATE_NEW_CONSOLE
    assert options['cwd'] == str(Path.home())
    assert 'stdout' not in options and 'stderr' not in options and 'stdin' not in options


def test_windows_auth_probe_does_not_open_console(monkeypatch, probes):
    installed(monkeypatch)
    monkeypatch.setattr(setup.sys, 'platform', 'win32')
    setup.get_provider_setup_status('Claude Code')
    assert probes[0][0][1]['creationflags'] & 0x08000000  # CREATE_NO_WINDOW


def test_missing_cli_login_never_spawns(monkeypatch):
    monkeypatch.setattr(setup, 'create_provider', lambda _: ClaudeProvider(which_fn=lambda _: None))
    monkeypatch.setattr(setup.subprocess, 'Popen', lambda *a, **kw: pytest.fail('login launched'))
    with pytest.raises(RuntimeError, match='install|Install'):
        setup.start_provider_login('Claude Code')


@pytest.mark.parametrize('name', ['Claude Code', 'Codex'])
def test_install_help_links_are_official(name):
    url = setup.get_provider_install_url(name)
    assert url.startswith('https://')
    assert ('claude.com' if name == 'Claude Code' else 'openai.com') in url


def test_invalid_provider_name_is_rejected():
    for action in (setup.get_provider_setup_status, setup.start_provider_login, setup.get_provider_install_url):
        with pytest.raises(ValueError, match='Unknown provider'):
            action('not a provider')


def test_setup_bypasses_npm_shim_without_shell(monkeypatch, probes, tmp_path):
    prefix = tmp_path / 'npm folder with spaces'
    prefix.mkdir()
    shim = prefix / 'claude.cmd'
    shim.write_text('must never run')
    package = prefix / 'node_modules' / '@anthropic-ai' / 'claude-code'
    package.mkdir(parents=True)
    script = package / 'cli.js'
    script.write_text('must never run in this test')
    (package / 'package.json').write_text('{"bin":{"claude":"cli.js"}}')
    node = str(prefix / 'node.exe')
    provider = ClaudeProvider(which_fn=lambda command: str(shim) if command == 'claude' else node)
    monkeypatch.setattr(setup, 'create_provider', lambda _: provider)
    setup.get_provider_setup_status('Claude Code')
    assert probes[0][0][0] == [node, str(script), 'auth', 'status', '--json']
    assert probes[0][0][1]['shell'] is False


@pytest.mark.parametrize(('provider_cls', 'location', 'filename'), [
    (ClaudeProvider, 'native', 'claude.exe'),
    (CodexProvider, 'npm', 'codex.cmd'),
])
def test_default_windows_discovery_includes_standard_install_locations(monkeypatch, tmp_path,
                                                                      provider_cls, location, filename):
    native = tmp_path / 'profile' / '.local' / 'bin'
    npm = tmp_path / 'Roaming App Data' / 'npm'
    native.mkdir(parents=True)
    npm.mkdir(parents=True)
    target = (native if location == 'native' else npm) / filename
    target.write_bytes(b'not executed')
    monkeypatch.setattr(base.sys, 'platform', 'win32')
    monkeypatch.setattr(base.shutil, 'which', lambda _: None)
    monkeypatch.setattr(base.Path, 'home', lambda: tmp_path / 'profile')
    monkeypatch.setenv('APPDATA', str(npm.parent))
    provider = provider_cls()
    assert provider.detect() is True
    assert provider._which(provider.cli_name) == str(target)
    # Custom discovery is authoritative and must retain its old test boundary.
    assert provider_cls(which_fn=lambda _: None).detect() is False
