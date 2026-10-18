"""Image handoff regression tests; no installed agent or authentication needed."""

import base64
import json
import sys
import threading

import pytest
from PIL import Image

from arrow.providers import ClaudeProvider, CodexProvider, ProviderStatus, RunRequest
from arrow.providers.runner import run_provider_sync


def request_for(tmp_path, assets=None, prompt='--dangerously-skip-permissions\nUnicode: café'):
    return RunRequest(capture_id='image-capture', repository_path=str(tmp_path),
                      prompt=prompt, assets=assets or {})


def save_image(path, color='red', format='PNG'):
    Image.new('RGB', (3, 2), color).save(path, format=format)
    return str(path)


def test_claude_uses_stream_json_flags_and_keeps_prompt_out_of_argv(tmp_path):
    request = request_for(tmp_path)
    command = ClaudeProvider(permission_mode='acceptEdits').build_command(request)
    assert command[command.index('--input-format') + 1] == 'stream-json'
    assert command[command.index('--output-format') + 1] == 'stream-json'
    assert '--verbose' in command
    assert '-p' in command
    assert command[command.index('--permission-mode') + 1] == 'acceptEdits'
    assert request.prompt not in command


@pytest.mark.parametrize(('suffix', 'format', 'mime'), [
    ('.png', 'PNG', 'image/png'),
    ('.jpg', 'JPEG', 'image/jpeg'),
    ('.webp', 'WEBP', 'image/webp'),
    ('.gif', 'GIF', 'image/gif'),
])
def test_claude_stdin_contains_actual_image_and_text(tmp_path, suffix, format, mime):
    image = tmp_path / ('annotated screenshot' + suffix)
    save_image(image, format=format)
    request = request_for(tmp_path, {'annotated': str(image)})
    payload = ClaudeProvider().build_stdin(request)
    assert payload.endswith('\n')
    message = json.loads(payload)
    assert message['type'] == 'user'
    assert message['message']['role'] == 'user'
    content = message['message']['content']
    assert content[0] == {'type': 'text', 'text': request.prompt}
    assert content[1]['type'] == 'image'
    source = content[1]['source']
    assert source['type'] == 'base64'
    assert source['media_type'] == mime
    assert base64.b64decode(source['data'], validate=True) == image.read_bytes()


@pytest.mark.parametrize('provider_cls', [ClaudeProvider, CodexProvider])
def test_provider_prefers_agent_annotation_and_falls_back_when_missing(tmp_path, provider_cls):
    annotated = save_image(tmp_path / 'annotated.png')
    agent = save_image(tmp_path / 'agent annotated.png', color='blue')
    provider = provider_cls()
    request = request_for(tmp_path, {'annotated': annotated, 'agent-annotated': agent})
    if provider_cls is ClaudeProvider:
        source = json.loads(provider.build_stdin(request))['message']['content'][1]['source']
        assert base64.b64decode(source['data']) == (tmp_path / 'agent annotated.png').read_bytes()
    else:
        command = provider.build_command(request)
        assert command[command.index('--image') + 1] == agent
        assert command[-2:] == ['--', request.prompt]
    (tmp_path / 'agent annotated.png').unlink()
    if provider_cls is ClaudeProvider:
        source = json.loads(provider.build_stdin(request))['message']['content'][1]['source']
        assert base64.b64decode(source['data']) == (tmp_path / 'annotated.png').read_bytes()
    else:
        command = provider.build_command(request)
        assert command[command.index('--image') + 1] == annotated


def test_claude_text_only_payload_when_screenshot_is_unavailable(tmp_path):
    request = request_for(tmp_path, {'annotated': str(tmp_path / 'missing.png')})
    content = json.loads(ClaudeProvider().build_stdin(request))['message']['content']
    assert content == [{'type': 'text', 'text': request.prompt}]


def test_codex_does_not_supply_stdin_payload(tmp_path):
    assert CodexProvider().build_stdin(request_for(tmp_path)) is None


class LocalClaude(ClaudeProvider):
    """Exercise the real subprocess transport with a local, inert child."""

    def __init__(self, script):
        super().__init__(which_fn=lambda _: sys.executable)
        self.script = script

    def build_command(self, request):
        return [sys.executable, '-u', '-c', self.script]


def test_runner_delivers_claude_image_over_stdin_and_closes_input(tmp_path):
    image = save_image(tmp_path / 'image.png')
    request = request_for(tmp_path, {'annotated': image})
    provider = LocalClaude(
        "import sys, json, base64; from pathlib import Path; "
        "message=json.loads(sys.stdin.read()); "
        "source=message['message']['content'][1]['source']; "
        "Path('received.png').write_bytes(base64.b64decode(source['data'])); "
        "print(message['message']['content'][0]['text'])"
    )
    final = run_provider_sync(provider, request)
    assert final.type == 'done'
    assert provider.get_status() == ProviderStatus.COMPLETED
    assert (tmp_path / 'received.png').read_bytes() == (tmp_path / 'image.png').read_bytes()


def test_stdin_write_does_not_deadlock_when_child_outputs_before_reading(tmp_path):
    # Both sides exceed pipe capacity: stdout must drain while stdin is written.
    provider = LocalClaude(
        "import sys, json; print('x'*262144, flush=True); "
        "message=json.loads(sys.stdin.read()); print(len(message['message']['content'][0]['text']))"
    )
    request = request_for(tmp_path, prompt='p' * 524288)
    result = []
    worker = threading.Thread(target=lambda: result.append(run_provider_sync(provider, request)), daemon=True)
    worker.start()
    worker.join(timeout=8)
    if worker.is_alive():
        provider.cancel_run()
        worker.join(timeout=3)
        pytest.fail('stdin write blocked stdout draining')
    assert result[0].type == 'done'


def test_cancelling_blocked_stdin_write_still_finishes_cancelled(tmp_path):
    provider = LocalClaude("import time; time.sleep(30)")
    request = request_for(tmp_path, prompt='p' * 524288)
    # start_run must not write a pipe-sized payload while holding the cancel lock.
    provider.start_run(request)
    events = []
    worker = threading.Thread(target=lambda: events.extend(provider.stream_events()), daemon=True)
    worker.start()
    provider.cancel_run()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert provider.get_status() == ProviderStatus.CANCELLED
    assert events[-1].type == 'done'
    assert events[-1].message == 'Cancelled'


def test_child_rejecting_stdin_surfaces_exit_error(tmp_path):
    provider = LocalClaude("import sys; print('input rejected'); sys.exit(3)")
    final = run_provider_sync(provider, request_for(tmp_path, prompt='p' * 524288))
    assert final.type == 'error'
    assert '3' in final.message
    assert provider.get_status() == ProviderStatus.FAILED


def test_stdin_write_error_cannot_be_reported_as_success(tmp_path):
    class RejectingInput:
        def write(self, text):
            raise BrokenPipeError('stdin closed')

        def close(self):
            pass

    class Process:
        stdin = RejectingInput()
        stdout = iter([])

        def poll(self):
            return None

        def wait(self):
            return 0

    provider = ClaudeProvider(which_fn=lambda _: sys.executable, popen_fn=lambda *a, **kw: Process())
    final = run_provider_sync(provider, request_for(tmp_path))
    assert final.type == 'error'
    assert 'stdin' in final.message.lower()
    assert provider.get_status() == ProviderStatus.FAILED
