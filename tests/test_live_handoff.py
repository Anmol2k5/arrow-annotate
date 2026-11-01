"""Protocol/validation tests use fake replies; they do not certify a live model."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from arrow.providers import _windows_job as windows_job
from arrow.providers import live_check


def _protocol_run(directory, requests):
    env = {**os.environ, 'ARROW_HOME': str(directory / 'home'),
           'ARROW_DB_PATH': str(directory / 'captures.db')}
    completed = subprocess.run(
        [sys.executable, '-m', 'arrow.mcp.validation', str(directory), str(directory / 'receipt.jsonl')],
        input=''.join(json.dumps(request) + '\n' for request in requests),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, timeout=15, check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines()]


def _request(method, params=None, request_id=1):
    return {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}}


def test_real_mcp_subprocess_returns_exact_saved_png_and_receipt(tmp_path):
    fixture = live_check._create_fixture(tmp_path)
    requests = [_request('initialize', {'protocolVersion': '2025-11-25'}), _request('tools/list'),
                _request('tools/call', {'name': 'arrow_get_capture_bundle',
                                        'arguments': {'capture_id': fixture['capture_id']}}, 3)]
    replies = _protocol_run(tmp_path, requests)
    assert replies[0]['result']['capabilities'] == {'tools': {}}
    assert [tool['name'] for tool in replies[1]['result']['tools']] == ['arrow_get_capture_bundle']
    content = replies[2]['result']['content']
    image = next(part for part in content if part['type'] == 'image')
    assert base64.b64decode(image['data']) == (tmp_path / 'sample.png').read_bytes()
    packet = json.loads(next(part['text'] for part in content if part['type'] == 'text'))
    assert packet['metadata']['capture_id'] == fixture['capture_id']
    assert fixture['context_code'] in packet['metadata']['current_instruction']
    assert fixture['image_code'] not in json.dumps(packet)
    assert fixture['context_code'] not in json.dumps(packet['metadata']['change_request'])
    receipt = (tmp_path / 'receipt.jsonl').read_text()
    assert fixture['image_code'] not in receipt and fixture['context_code'] not in receipt
    assert live_check._receipt_matches(tmp_path / 'receipt.jsonl', fixture)


@pytest.mark.parametrize('method,params', [
    ('tools/call', {'name': 'arrow_get_capture_bundle', 'arguments': {'capture_id': 'other'}}),
    ('tools/call', {'name': 'arrow_get_capture_bundle', 'arguments': {}}),
    ('tools/call', {'name': 'arrow_get_capture_bundle', 'arguments': {'capture_id': 'other', 'extra': True}}),
    ('tools/call', {'name': 'arrow_look', 'arguments': {}}),
    ('tools/call', {'name': 'arrow_list_captures', 'arguments': {}}),
    ('resources/list', {}),
    ('resources/read', {'uri': 'file:///etc/passwd'}),
])
def test_scoped_mcp_rejects_other_capture_tools_and_resources(tmp_path, method, params):
    live_check._create_fixture(tmp_path)
    reply = _protocol_run(tmp_path, [_request(method, params)])[0]
    assert 'error' in reply
    assert not (tmp_path / 'receipt.jsonl').exists()


def test_scoped_mcp_malformed_input_remains_available(tmp_path):
    live_check._create_fixture(tmp_path)
    replies = _protocol_run(tmp_path, [[], _request('ping')])
    assert replies[0]['error']['code'] == -32600
    assert replies[1]['result'] == {}


def test_receipt_rejects_wrong_hash_capture_and_session(tmp_path):
    fixture = live_check._create_fixture(tmp_path)
    path = tmp_path / 'receipt.jsonl'
    good = {key: fixture[key] for key in ('capture_id', 'session_nonce', 'image_sha256')}
    good['request_id'] = 4
    assert not live_check._receipt_matches(path, fixture)
    for key in ('capture_id', 'session_nonce', 'image_sha256', 'request_id'):
        path.write_text(json.dumps({**good, key: None}))
        assert not live_check._receipt_matches(path, fixture)
    path.write_text(json.dumps(good))
    assert live_check._receipt_matches(path, fixture)


@pytest.mark.parametrize('provider', ['Codex', 'Claude Code'])
def test_final_answer_parsing_requires_final_provider_message(provider):
    answer = {'image_code': 'ABC12345', 'context_code': 'CTX', 'capture_id': 'cap'}
    if provider == 'Codex':
        event = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}}
    else:
        event = {'type': 'result', 'is_error': False, 'result': json.dumps(answer)}
    assert live_check._answer(json.dumps(event), provider) == answer
    assert live_check._answer(json.dumps(answer), provider) is None
    assert live_check._answer('not JSON', provider) is None
    if provider == 'Claude Code':
        assert live_check._answer(json.dumps({**event, 'is_error': True}), provider) is None


class FakeProvider:
    """A protocol boundary stand-in; never a live agent certification."""
    name = 'Codex'

    def __init__(self, script, installed=True):
        self.script = script
        self.installed = installed

    def detect(self):
        return self.installed

    def _resolve_command(self, command):
        self.command = command
        return [sys.executable, '-c', self.script]


def test_correct_fake_answer_without_actual_receipt_is_failure(tmp_path, monkeypatch):
    fixture = {}
    create_fixture = live_check._create_fixture

    def create(directory):
        fixture.update(create_fixture(directory))
        return fixture

    provider = FakeProvider('print("fake boundary stdout: credential-secret")')
    monkeypatch.setattr(live_check, '_create_fixture', create)
    monkeypatch.setattr(live_check, 'create_provider', lambda name: provider)
    monkeypatch.setattr(live_check, '_answer', lambda output, name: {
        key: fixture[key] for key in ('image_code', 'context_code', 'capture_id')})
    report_path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', report_path) == 1
    text = report_path.read_text()
    report = json.loads(text)
    assert report['status'] == 'failed'
    assert not report['receipt_verified'] and not report['model_answer_verified']
    assert report['image_answer_matches'] and report['context_answer_matches']
    assert 'credential-secret' not in text and fixture['image_code'] not in text
    assert fixture['context_code'] not in text and str(tmp_path) not in text
    prompt = provider.command[-1]
    assert fixture['image_code'] not in prompt and fixture['context_code'] not in prompt
    assert '--sandbox' in provider.command and 'read-only' in provider.command
    assert '--image' not in provider.command


def test_unavailable_cli_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider('', installed=False))
    report_path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', report_path) == 1
    report = json.loads(report_path.read_text())
    assert report['status'] == 'not_run' and report['reason'] == 'not_installed'
    assert report['synthetic'] and report['platform']


def test_timeout_is_bounded_and_report_does_not_claim_success(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider('import time; time.sleep(60)'))
    started = time.monotonic()
    report_path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', report_path, timeout=.1) == 1
    assert time.monotonic() - started < 10
    report = json.loads(report_path.read_text())
    assert report['reason'] == 'timeout' and not report['model_answer_verified']


def test_nonzero_provider_exit_cannot_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider('raise SystemExit(2)'))
    report_path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', report_path) == 1
    report = json.loads(report_path.read_text())
    assert report['reason'] == 'provider_failed' and not report['model_answer_verified']


def test_receipt_without_correct_fake_reply_cannot_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider('print("fake protocol reply")'))
    monkeypatch.setattr(live_check, '_receipt_matches', lambda path, fixture: True)
    monkeypatch.setattr(live_check, '_answer', lambda output, name: {
        'image_code': 'WRONG', 'context_code': 'WRONG', 'capture_id': 'WRONG'})
    report_path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', report_path) == 1
    report = json.loads(report_path.read_text())
    assert report['receipt_verified'] and not report['model_answer_verified']
    assert not report['image_answer_matches'] and not report['context_answer_matches']
    assert not report['capture_id_matches']


@pytest.mark.parametrize('stderr,reason', [
    ('Error: failed to initialize: Read-only file system (os error 30)', 'provider_state_read_only'),
    ('Please run codex login. secret-value', 'provider_authentication_failed'),
    ('error: unexpected argument --ephemeral', 'unsupported_cli_options'),
    ('Something failed: secret-value', 'provider_failed'),
])
def test_provider_errors_become_fixed_safe_categories(stderr, reason):
    assert live_check._failure_reason(stderr) == reason


def test_read_only_provider_state_failure_report_is_safe(tmp_path, monkeypatch):
    script = ('import sys; print("failed to initialize in-process app-server: '
              'Read-only file system: credential-secret", file=sys.stderr); raise SystemExit(1)')
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider(script))
    path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', path) == 1
    assert json.loads(path.read_text())['reason'] == 'provider_state_read_only'
    assert 'credential-secret' not in path.read_text()


def test_codex_state_override_stays_in_synthetic_home(tmp_path):
    fixture = live_check._create_fixture(tmp_path)
    provider = FakeProvider('')
    with pytest.raises(ValueError, match='inside the temporary fixture'):
        live_check._command(provider, tmp_path, fixture, {'sqlite_home': str(tmp_path.parent)})
    live_check._command(provider, tmp_path, fixture, {'sqlite_home': str(tmp_path / 'state')})
    assert str(tmp_path / 'state') in ' '.join(provider.command)
    assert hashlib.sha256((tmp_path / 'sample.png').read_bytes()).hexdigest() == fixture['image_sha256']


@pytest.mark.parametrize('failure', [None, 'assign', 'resume'])
def test_windows_child_is_assigned_before_running_and_failure_cleans_up(monkeypatch, failure):
    events = []

    class FakeJob:
        def __init__(self):
            events.append('job-created')

        def assign(self, process):
            events.append('assigned')
            if failure == 'assign':
                raise OSError('assignment failed')

        def resume(self, process):
            events.append('resumed')
            if failure == 'resume':
                raise OSError('resumption failed')

        def close(self):
            events.append('job-closed')

    class Process:
        stdout = stderr = None

        def poll(self):
            return None

        def kill(self):
            events.append('child-killed')

        def wait(self, timeout):
            events.append('child-reaped')

    def popen(command, **options):
        assert options['creationflags'] & windows_job.CREATE_SUSPENDED
        events.append('spawned-suspended')
        return Process()

    monkeypatch.setattr(windows_job, 'WindowsJob', FakeJob)
    monkeypatch.setattr(windows_job.subprocess, 'Popen', popen)
    if failure:
        with pytest.raises(OSError):
            windows_job.start_job_process(['fake-cli'])
        assert events[-3:] == ['child-killed', 'child-reaped', 'job-closed']
    else:
        _process, job = windows_job.start_job_process(['fake-cli'])
        assert events == ['job-created', 'spawned-suspended', 'assigned', 'resumed']
        job.close()


def test_windows_cleanup_closes_job_even_after_cli_exit(monkeypatch):
    events = []

    class ExitedProcess:
        def poll(self):
            return 0

        def wait(self, timeout):
            events.append('reaped')

    class Job:
        def close(self):
            events.append('job-closed')

    monkeypatch.setattr(live_check.sys, 'platform', 'win32')
    live_check._stop_process_tree(ExitedProcess(), Job())
    assert events[0] == 'job-closed' and 'reaped' in events


def test_windows_job_waits_for_all_descendants_before_closing_handle(monkeypatch):
    events = []
    active = iter([1, 1, 0])

    class Kernel:
        def TerminateJobObject(self, handle, code):
            events.append('terminated')
            return True

        def QueryInformationJobObject(self, handle, kind, accounting, size, returned):
            accounting._obj.ActiveProcesses = next(active)
            events.append('active-' + str(accounting._obj.ActiveProcesses))
            return True

        def CloseHandle(self, handle):
            events.append('closed')
            return True

    job = windows_job.WindowsJob.__new__(windows_job.WindowsJob)
    job.kernel, job.handle = Kernel(), 123
    monkeypatch.setattr(windows_job.time, 'sleep', lambda seconds: None)
    job.close()
    assert events == ['terminated', 'active-1', 'active-1', 'active-0', 'closed']
    assert job.handle is None


def test_windows_job_cleanup_deadline_closes_handle_and_reports_failure(monkeypatch):
    closed = []

    class Kernel:
        def TerminateJobObject(self, handle, code):
            return True

        def QueryInformationJobObject(self, handle, kind, accounting, size, returned):
            accounting._obj.ActiveProcesses = 1
            return True

        def CloseHandle(self, handle):
            closed.append(handle)
            return True

    clock = iter([0, 6])
    monkeypatch.setattr(windows_job.time, 'monotonic', lambda: next(clock))
    job = windows_job.WindowsJob.__new__(windows_job.WindowsJob)
    job.kernel, job.handle = Kernel(), 123
    with pytest.raises(TimeoutError, match='cleanup deadline'):
        job.close()
    assert closed == [123] and job.handle is None


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows Job Objects')
def test_native_windows_job_kills_descendant_and_releases_file_after_parent_exits(tmp_path):
    import ctypes
    from ctypes import wintypes

    # The CLI exits successfully while its MCP-like descendant remains alive.
    held_file = tmp_path / 'mcp-held-file.txt'
    child_code = ('import time; stream=open(' + repr(str(held_file)) + ',"w"); '
                  'print("ready",flush=True); time.sleep(60)')
    script = ('import subprocess,sys; child=subprocess.Popen('
              '[sys.executable,"-c",' + repr(child_code) + '],'
              'stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True); '
              'assert child.stdout.readline().strip()=="ready"; print(child.pid,flush=True)')
    process, job = windows_job.start_job_process(
        [sys.executable, '-c', script], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = None
    try:
        stdout, _stderr = process.communicate(timeout=15)
        assert process.returncode == 0
        handle = kernel.OpenProcess(0x00100000, False, int(stdout.strip()))  # SYNCHRONIZE
        assert handle
        assert kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        assert held_file.is_file()
        live_check._stop_process_tree(process, job)
        # No wait outside production cleanup: it must already have drained the
        # job and released the descendant's open file before returning.
        assert kernel.WaitForSingleObject(handle, 0) == 0  # WAIT_OBJECT_0
        held_file.unlink()
    finally:
        job.close()
        if handle:
            kernel.CloseHandle(handle)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def test_cancellation_stops_running_check_and_removes_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: FakeProvider('import time; time.sleep(60)'))
    directory = []
    create_fixture = live_check._create_fixture

    def create(path):
        directory.append(path)
        return create_fixture(path)

    monkeypatch.setattr(live_check, '_create_fixture', create)
    cancel = threading.Event()
    timer = threading.Timer(.3, cancel.set)
    timer.start()
    path = tmp_path / 'report.json'
    started = time.monotonic()
    try:
        assert live_check.run_live_check('Codex', path, timeout=30, cancel_event=cancel) == 1
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5
    assert directory and not directory[0].exists()
    report = json.loads(path.read_text())
    assert report['reason'] == 'cancelled' and not report['model_answer_verified']


def test_already_cancelled_check_never_starts_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(live_check, 'create_provider', lambda name: pytest.fail('cancelled check started a provider'))
    cancel = threading.Event()
    cancel.set()
    path = tmp_path / 'report.json'
    assert live_check.run_live_check('Codex', path, cancel_event=cancel) == 1
    assert json.loads(path.read_text())['reason'] == 'cancelled'
