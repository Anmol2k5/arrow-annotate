"""Launch Windows npm CLI installations without executing a shell wrapper."""

import json
import shutil
import subprocess

import pytest

from arrow.providers import ClaudeProvider, CodexProvider, ProviderStatus, RunRequest
from arrow.providers.runner import run_provider_sync


def npm_install(tmp_path, provider_cls):
    name, package, entry = {
        ClaudeProvider: ('claude', '@anthropic-ai/claude-code', 'cli.js'),
        CodexProvider: ('codex', '@openai/codex', 'bin/codex.js'),
    }[provider_cls]
    prefix = tmp_path / 'npm installation with spaces'
    prefix.mkdir()
    shim = prefix / (name + '.cmd')
    # This wrapper must never be executed by cmd.exe or a shell.
    shim.write_text('THIS IS NOT A VALID EXECUTABLE OR SHELL SCRIPT')
    script = prefix / 'node_modules' / package / entry
    script.parent.mkdir(parents=True)
    package_dir = prefix / 'node_modules' / package
    (package_dir / 'package.json').write_text(json.dumps({'name': package, 'bin': {name: entry}}))
    script.write_text(
        "const fs = require('node:fs'); let input = ''; "
        "process.stdin.setEncoding('utf8'); "
        "process.stdin.on('data', chunk => input += chunk); "
        "process.stdin.on('end', () => { "
        "fs.writeFileSync('received.json', JSON.stringify({args:process.argv.slice(2), input})); "
        "console.log('received'); });"
    )
    return name, shim, script


@pytest.mark.parametrize('provider_cls', [ClaudeProvider, CodexProvider])
def test_npm_cmd_shim_runs_known_node_entrypoint_without_shell(tmp_path, provider_cls):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js not installed')
    name, shim, script = npm_install(tmp_path, provider_cls)
    def which(executable):
        return str(shim) if executable == name else node if executable == 'node' else None

    def local_popen(command, **kwargs):
        # A failing regression must never fall through to an installed agent.
        assert command[:2] == [node, str(script)]
        assert not kwargs.get('shell')
        return subprocess.Popen(command, **kwargs)

    provider = provider_cls(which_fn=which, popen_fn=local_popen)
    prompt = 'Fix the label & echo UNWANTED > unintended.txt\n$(touch unintended.txt)'
    request = RunRequest(capture_id='npm', repository_path=str(tmp_path), prompt=prompt)
    final = run_provider_sync(provider, request)
    assert final.type == 'done', final.message
    received = json.loads((tmp_path / 'received.json').read_text())
    if provider_cls is ClaudeProvider:
        assert json.loads(received['input'])['message']['content'][0]['text'] == prompt
    else:
        assert received['args'][-2:] == ['--', prompt]
    assert not (tmp_path / 'unintended.txt').exists()


@pytest.mark.parametrize('provider_cls', [ClaudeProvider, CodexProvider])
def test_incomplete_npm_installation_fails_without_spawning_wrapper(tmp_path, provider_cls):
    name, shim, script = npm_install(tmp_path, provider_cls)
    script.unlink()
    calls = []
    provider = provider_cls(which_fn=lambda _: str(shim), popen_fn=lambda *a, **kw: calls.append(a))
    request = RunRequest(capture_id='npm', repository_path=str(tmp_path), prompt='fix')
    final = run_provider_sync(provider, request)
    assert final.type == 'error'
    assert 'npm' in final.message.lower()
    assert not calls
    assert provider.get_status() == ProviderStatus.FAILED


def test_npm_installation_requires_node_without_spawning_wrapper(tmp_path):
    name, shim, _ = npm_install(tmp_path, ClaudeProvider)
    calls = []
    provider = ClaudeProvider(which_fn=lambda executable: str(shim) if executable == name else None,
                              popen_fn=lambda *a, **kw: calls.append(a))
    request = RunRequest(capture_id='npm', repository_path=str(tmp_path), prompt='fix')
    final = run_provider_sync(provider, request)
    assert final.type == 'error'
    assert 'node' in final.message.lower()
    assert not calls


@pytest.mark.parametrize('provider_cls', [ClaudeProvider, CodexProvider])
def test_npm_native_executable_is_launched_directly(tmp_path, provider_cls):
    import io

    name, shim, script = npm_install(tmp_path, provider_cls)
    manifest_path = next((shim.parent / 'node_modules').glob('@*/*/package.json'))
    manifest = json.loads(manifest_path.read_text())
    native = manifest_path.parent / 'bin' / (name + '.exe')
    native.parent.mkdir(exist_ok=True)
    native.write_bytes(b'MZ')
    manifest['bin'][name] = 'bin/' + native.name
    manifest_path.write_text(json.dumps(manifest))
    calls = []

    class Process:
        stdin = io.StringIO()
        stdout = iter([])

        def poll(self):
            return None

        def wait(self):
            return 0

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    provider = provider_cls(which_fn=lambda executable: str(shim) if executable == name else None,
                            popen_fn=popen)
    final = run_provider_sync(provider, RunRequest(capture_id='native', repository_path=str(tmp_path), prompt='go'))
    assert final.type == 'done'
    assert calls[0][0][0] == str(native)
    assert not calls[0][1].get('shell')


@pytest.mark.parametrize('entry', ['../outside.js', 'unsafe.cmd'])
def test_npm_package_cannot_redirect_launch_to_shell_or_outside_package(tmp_path, entry):
    name, shim, _ = npm_install(tmp_path, ClaudeProvider)
    manifest_path = next((shim.parent / 'node_modules').glob('@*/*/package.json'))
    manifest = json.loads(manifest_path.read_text())
    target = manifest_path.parent / entry
    target.write_text('do not execute')
    manifest['bin'][name] = entry
    manifest_path.write_text(json.dumps(manifest))
    calls = []
    provider = ClaudeProvider(which_fn=lambda _: str(shim), popen_fn=lambda *a, **kw: calls.append(a))
    final = run_provider_sync(provider, RunRequest(capture_id='unsafe', repository_path=str(tmp_path), prompt='go'))
    assert final.type == 'error'
    assert not calls
