"""MCP readiness is verified without account credentials or agent sessions."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arrow.providers import ClaudeProvider, CodexProvider, connection


@pytest.fixture
def config(tmp_path):
    return {
        'command': 'C:\\Program Files\\Arrow\\ArrowMCP.exe', 'args': ['--mcp'],
        'env': {'ARROW_HOME': str(tmp_path / 'Arrow Home'), 'ARROW_DB_PATH': str(tmp_path / 'Arrow Home' / 'arrow.db')},
    }


def install(monkeypatch, config, name='Codex'):
    cls = CodexProvider if name == 'Codex' else ClaudeProvider
    executable = 'C:\\Program Files\\Client\\' + cls.cli_name + '.exe'
    monkeypatch.setattr(connection, 'create_provider', lambda _: cls(which_fn=lambda _: executable))
    monkeypatch.setattr(connection, 'mcp_server_config', lambda: config)
    return executable


def registry_entry(config, **changes):
    result = {'name': 'arrow', 'enabled': True, 'transport': {'type': 'stdio', **config}}
    result.update(changes)
    return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')


def responses(monkeypatch, entries):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        result = entries.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(connection.subprocess, 'run', run)
    return calls


@pytest.mark.parametrize('name', ['Codex', 'Claude Code'])
def test_missing_client_never_configures_or_probes(monkeypatch, name):
    cls = CodexProvider if name == 'Codex' else ClaudeProvider
    monkeypatch.setattr(connection, 'create_provider', lambda _: cls(which_fn=lambda _: None))
    monkeypatch.setattr(connection.subprocess, 'Popen', lambda *a, **kw: pytest.fail('spawned'))
    monkeypatch.setattr(connection.subprocess, 'run', lambda *a, **kw: pytest.fail('spawned'))
    for action in (connection.configure_provider_mcp, connection.probe_provider_mcp):
        status = action(name)
        assert not status.installed and not status.registered
        assert status.protocol_verified is None


def test_codex_configure_adds_only_absent_arrow_and_verifies_registry(monkeypatch, config):
    executable = install(monkeypatch, config)
    missing = SimpleNamespace(returncode=1, stdout='', stderr="Error: No MCP server named 'arrow' found.")
    calls = responses(monkeypatch, [missing, SimpleNamespace(returncode=0), registry_entry(config)])
    status = connection.configure_provider_mcp('Codex')
    assert status.registered is True and status.protocol_verified is None and not status.conflict
    expected = [executable, 'mcp', 'add']
    for key, value in config['env'].items():
        expected += ['--env', f'{key}={value}']
    assert calls[1][0] == [*expected, 'arrow', '--', config['command'], '--mcp']
    assert calls[0][0] == calls[2][0] == [executable, 'mcp', 'get', 'arrow', '--json']
    for _, options in calls:
        assert options['shell'] is False
        assert options['timeout'] <= 10
        assert options['stdin'] == subprocess.DEVNULL
        assert options['cwd'] == str(Path.home())


def test_existing_correct_entry_is_never_rewritten(monkeypatch, config):
    install(monkeypatch, config)
    calls = responses(monkeypatch, [registry_entry(config)])
    assert connection.configure_provider_mcp('Codex').registered is True
    assert len(calls) == 1


@pytest.mark.parametrize('change', [
    {'command': 'different.exe'}, {'args': ['different']}, {'env': {'ARROW_DB_PATH': 'different'}},
    {'env': {}}, {'type': 'http'}, {'env_vars': ['ARROW_DB_PATH']}, {'cwd': '/elsewhere'},
])
def test_conflicting_entry_never_overwritten(monkeypatch, config, change):
    install(monkeypatch, config)
    entry = registry_entry(config)
    parsed = json.loads(entry.stdout)
    parsed['transport'].update(change)
    entry.stdout = json.dumps(parsed)
    calls = responses(monkeypatch, [entry])
    status = connection.configure_provider_mcp('Codex')
    assert status.conflict and status.registered is False
    assert len(calls) == 1


@pytest.mark.parametrize('entry', [
    SimpleNamespace(returncode=0, stdout='banner\n{}', stderr=''),
    SimpleNamespace(returncode=0, stdout='[]', stderr=''),
    SimpleNamespace(returncode=0, stdout='{}', stderr=''),
    SimpleNamespace(returncode=1, stdout='', stderr='invalid configuration'),
    subprocess.TimeoutExpired('codex', 8), OSError('sensitive diagnostic'),
])
def test_unrecognized_or_failed_registry_never_adds(monkeypatch, config, entry):
    install(monkeypatch, config)
    calls = responses(monkeypatch, [entry])
    status = connection.configure_provider_mcp('Codex')
    assert status.registered is None and not status.conflict
    assert len(calls) == 1
    assert 'sensitive' not in status.message


def claude_entry(config):
    return SimpleNamespace(returncode=0, stdout=(
        'arrow:\n  Scope: User config (available in all your projects)\n'
        '  Status: ✓ Connected\n  Type: stdio\n'
        f"  Command: {config['command']}\n  Args: {' '.join(config['args'])}\n"
        '  Environment:\n' + ''.join(f'    {key}={value}\n' for key, value in config['env'].items())
    ), stderr='')


def test_claude_uses_global_scope_and_preserves_spaced_paths(monkeypatch, config):
    config['args'] = ['C:\\Program Files\\Arrow\\main.py', '--mcp']
    executable = install(monkeypatch, config, 'Claude Code')
    entries = [SimpleNamespace(returncode=1, stdout='', stderr='No MCP server found with name: arrow'),
               SimpleNamespace(returncode=0), claude_entry(config)]
    calls = responses(monkeypatch, entries)
    status = connection.configure_provider_mcp('Claude Code')
    assert status.registered is True
    assert calls[0][0] == [executable, 'mcp', 'get', 'arrow']
    assert calls[1][0][2:7] == ['add', '--scope', 'user', '--transport', 'stdio']
    assert calls[1][0][-3:] == [config['command'], *config['args']]


def test_claude_connected_label_cannot_replace_registration_fields(monkeypatch, config):
    install(monkeypatch, config, 'Claude Code')
    responses(monkeypatch, [SimpleNamespace(returncode=0, stdout='Status: Connected', stderr='')])
    assert connection.configure_provider_mcp('Claude Code').registered is None


def test_probe_registry_conflict_does_not_become_client_connection(monkeypatch, config):
    install(monkeypatch, config)
    responses(monkeypatch, [registry_entry({**config, 'command': 'elsewhere'})])
    monkeypatch.setattr(connection, '_probe_local_protocol', lambda _: (True, 'Local MCP verified.'))
    status = connection.probe_provider_mcp('Codex')
    assert status.protocol_verified is True and status.registered is False and status.conflict
    assert 'differs' in status.message and 'connected' not in status.message.lower()


def test_registry_failure_still_runs_local_protocol_check(monkeypatch, config):
    install(monkeypatch, config)
    responses(monkeypatch, [subprocess.TimeoutExpired('codex', 8)])
    monkeypatch.setattr(connection, '_probe_local_protocol', lambda _: (True, 'Local MCP verified.'))
    status = connection.probe_provider_mcp('Codex')
    assert status.registered is None and status.protocol_verified is True
    assert 'could not be verified' in status.message


@pytest.fixture
def synthetic_server(tmp_path):
    def make(mode):
        script = tmp_path / 'server with spaces.py'
        script.write_text('''import json, os, sys, time
mode = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        if mode == 'timeout':
            time.sleep(5)
        if mode == 'banner':
            print('Startup banner', flush=True)
        if mode == 'malformed':
            print('{bad json', flush=True)
            continue
        result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'arrow-mcp'}}
        if mode == 'wrong-server':
            result['serverInfo']['name'] = 'other-server'
        if mode == 'invalid-info':
            result['serverInfo'] = []
    elif request.get('method') == 'tools/list':
        result = {'tools': [{'name': 'arrow_get_capture_bundle', 'inputSchema': {'type': 'object'}}]}
        if mode == 'no-tool':
            result['tools'] = []
        if mode == 'wrong-db' and os.environ.get('ARROW_DB_PATH') != sys.argv[2]:
            result['tools'] = []
    else:
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
    if mode == 'trailing-banner' and request.get('method') == 'tools/list':
        print('Trailing banner', flush=True)
''')
        database = str(tmp_path / 'database with spaces.db')
        return {'command': sys.executable, 'args': [str(script), mode, database],
                'env': {'ARROW_DB_PATH': database}}
    return make


@pytest.mark.parametrize('mode', ['banner', 'malformed', 'wrong-server', 'invalid-info', 'no-tool', 'timeout', 'trailing-banner'])
def test_local_probe_rejects_invalid_protocol_and_cleans_child(monkeypatch, synthetic_server, mode):
    monkeypatch.setattr(connection, '_PROTOCOL_TIMEOUT', 0.25)
    original = subprocess.Popen
    children = []

    def popen(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(connection.subprocess, 'Popen', popen)
    verified, message = connection._probe_local_protocol(synthetic_server(mode))
    assert verified is False
    assert children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stdin.closed
    assert ('timed out' if mode == 'timeout' else 'failed') in message


def test_local_probe_passes_database_environment_and_spaces_without_shell(monkeypatch, synthetic_server):
    original = subprocess.Popen
    calls = []

    def popen(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(connection.subprocess, 'Popen', popen)
    config = synthetic_server('wrong-db')
    assert connection._probe_local_protocol(config)[0] is True
    assert calls[0][0][0] == [config['command'], *config['args']]
    assert calls[0][1]['shell'] is False
    assert calls[0][1]['env']['ARROW_DB_PATH'] == config['env']['ARROW_DB_PATH']
    assert calls[0][1]['stderr'] == subprocess.DEVNULL


def test_real_arrow_mcp_exchanges_initialize_and_capture_tool_list(tmp_path):
    project = Path(__file__).resolve().parents[1]
    config = {'command': sys.executable, 'args': [str(project / 'main.py'), '--mcp'],
              'env': {'ARROW_HOME': str(tmp_path), 'ARROW_DB_PATH': str(tmp_path / 'arrow.db')}}
    assert connection._probe_local_protocol(config)[0] is True
    assert (tmp_path / 'arrow.db').is_file()


@pytest.mark.parametrize('action', [connection.configure_provider_mcp, connection.probe_provider_mcp])
def test_unknown_client_rejected(action):
    with pytest.raises(ValueError, match='Unknown provider'):
        action('unknown')


def test_configuration_bypasses_windows_npm_shim_with_spaced_paths(monkeypatch, config, tmp_path):
    prefix = tmp_path / 'Npm installation with spaces'
    prefix.mkdir()
    shim = prefix / 'codex.cmd'
    shim.write_text('must never execute this shell wrapper')
    package = prefix / 'node_modules' / '@openai' / 'codex'
    package.mkdir(parents=True)
    script = package / 'bin' / 'codex.js'
    script.parent.mkdir()
    script.write_text('not executed by test')
    (package / 'package.json').write_text('{"bin":{"codex":"bin/codex.js"}}')
    node = str(prefix / 'node.exe')
    provider = CodexProvider(which_fn=lambda command: str(shim) if command == 'codex' else node)
    monkeypatch.setattr(connection, 'create_provider', lambda _: provider)
    monkeypatch.setattr(connection, 'mcp_server_config', lambda: config)
    calls = responses(monkeypatch, [registry_entry(config)])
    assert connection.configure_provider_mcp('Codex').registered is True
    assert calls[0][0] == [node, str(script), 'mcp', 'get', 'arrow', '--json']
    assert calls[0][1]['shell'] is False


@pytest.mark.parametrize('change', [{'enabled': False}, {'enabled_tools': []}, {'disabled_tools': ['arrow_get_capture_bundle']}])
def test_disabled_registration_is_a_conflict(monkeypatch, config, change):
    install(monkeypatch, config)
    calls = responses(monkeypatch, [registry_entry(config, **change)])
    assert connection.configure_provider_mcp('Codex').conflict is True
    assert len(calls) == 1
