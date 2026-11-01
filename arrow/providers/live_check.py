"""Opt-in real CLI/MCP/image checks. No credentials or raw CLI output are saved."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from arrow.providers.handoff import mcp_server_config
from arrow.providers.runner import create_provider
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord


def _create_fixture(directory):
    """The expected answers stay in runner memory; the image code is PNG-only."""
    directory = Path(directory)
    repo = directory / 'repository'
    repo.mkdir()
    (directory / 'home').mkdir()
    capture_id = 'synthetic-' + secrets.token_hex(12)
    session_nonce = secrets.token_hex(24)
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    image_code = ''.join(secrets.choice(alphabet) for _ in range(8))
    context_code = secrets.token_hex(8).upper()
    image = Image.new('RGB', (1600, 640), 'white')
    draw = ImageDraw.Draw(image)
    # Pillow's bundled scalable font avoids dependence on a platform font path.
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 180)
    except OSError:
        # Older Pillow releases have only a small bitmap default font. Render
        # that to a separate canvas and enlarge the pixels for readable output.
        font = ImageFont.load_default()
        tile = Image.new('RGB', (100, 24), 'white')
        ImageDraw.Draw(tile).text((2, 4), image_code, fill='black', font=font)
        image.paste(tile.resize((1400, 336), Image.Resampling.NEAREST), (90, 150))
    else:
        draw.text((90, 200), image_code, fill='black', font=font)
    image_path = directory / 'sample.png'
    image.save(image_path)
    # Empty raw_user_request means the production bundle takes the instruction
    # from CaptureRecord; the nonce appears only in current_instruction metadata.
    CaptureStore(str(directory / 'captures.db')).add(CaptureRecord(
        id=capture_id, timestamp=datetime.now(timezone.utc).isoformat(),
        screenshot_path=str(image_path),
        annotation_text=f'Synthetic validation context code: {context_code}',
        change_request={'capture_id': capture_id, 'raw_user_request': '',
                        'summary': 'Synthetic visual retrieval check',
                        'project': {'repository_root': str(repo)},
                        'assets': {'annotated': str(image_path)}},
    ))
    (directory / 'fixture.json').write_text(json.dumps({
        'capture_id': capture_id, 'session_nonce': session_nonce}), encoding='utf-8')
    return {'capture_id': capture_id, 'session_nonce': session_nonce,
            'image_code': image_code, 'context_code': context_code,
            'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest()}


def _toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(key) + '=' + _toml(item) for key, item in value.items()) + '}'
    return json.dumps(value, ensure_ascii=False)


def _command(provider, directory, fixture, provider_overrides=None):
    config = mcp_server_config()
    # Same executable as normal handoffs, separate deliberately restricted mode.
    config['args'] = [*config['args'][:-1], '--validation-mcp', str(directory), str(directory / 'receipt.jsonl')]
    config['env'] = {'ARROW_HOME': str(directory / 'home'), 'ARROW_DB_PATH': str(directory / 'captures.db'),
                     'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    prompt = (f'This is a synthetic Arrow retrieval validation. Call the arrow_get_capture_bundle MCP tool '
              f'with capture_id {fixture["capture_id"]}. Inspect its returned PNG and current_instruction. '
              'Read the eight-character code displayed in the image and the context code in current_instruction. '
              'Do not use any other tools or read files. Return only compact JSON with exactly these keys: '
              'image_code, context_code, capture_id. Copy the observed values exactly.')
    repo = str(directory / 'repository')
    if provider.name == 'Codex':
        command = ['codex', 'exec', '--sandbox', 'read-only', '--json', '--ephemeral',
                   '--skip-git-repo-check', '--cd', repo, '-c', 'mcp_servers=' + _toml({'arrow': config})]
        for key, value in (provider_overrides or {}).items():
            if key not in {'sqlite_home', 'log_dir'}:
                raise ValueError('Only temporary sqlite_home/log_dir provider overrides are supported')
            path = Path(value).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError('Provider state overrides must be inside the temporary fixture')
            path.mkdir(parents=True, exist_ok=True)
            command += ['-c', key + '=' + json.dumps(str(path))]
        command += ['--', prompt]
    else:
        if provider_overrides:
            raise ValueError('Provider state overrides are only supported for Codex')
        command = ['claude', '-p', '--output-format', 'json', '--permission-mode', 'default',
                   '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {'arrow': config}}),
                   '--tools', '', '--allowedTools', 'mcp__arrow__arrow_get_capture_bundle', '--', prompt]
    return provider._resolve_command(command)


def _answer(stdout, provider_name):
    final = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if provider_name == 'Codex' and event.get('type') == 'item.completed':
            item = event.get('item', {})
            if isinstance(item, dict) and item.get('type') == 'agent_message':
                final = item.get('text')
        elif provider_name == 'Claude Code' and event.get('type') == 'result' and not event.get('is_error'):
            final = event.get('result')
    try:
        value = json.loads(final) if isinstance(final, str) else None
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and set(value) == {'image_code', 'context_code', 'capture_id'} else None


def _receipt_matches(path, fixture):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        receipts = [json.loads(line) for line in lines]
    except (OSError, ValueError):
        return False
    return any(isinstance(value, dict) and value.get('capture_id') == fixture['capture_id']
               and value.get('session_nonce') == fixture['session_nonce']
               and value.get('image_sha256') == fixture['image_sha256']
               and value.get('request_id') is not None for value in receipts)


def _failure_reason(stderr):
    """Convert known CLI failures to fixed categories; never expose output."""
    message = stderr.lower()
    if 'read-only file system' in message:
        return 'provider_state_read_only'
    if any(phrase in message for phrase in ('not logged in', 'please run codex login',
                                          'please run /login', 'authentication required',
                                          'invalid api key', 'unauthorized')):
        return 'provider_authentication_failed'
    if any(phrase in message for phrase in ('unexpected argument', 'unknown option', 'unrecognized option')):
        return 'unsupported_cli_options'
    return 'provider_failed'


def _stop_process_tree(process, job=None):
    if sys.platform == 'win32':
        if job is not None:
            # This must run even when the CLI already exited: its MCP children
            # may still own pipe handles and files in the temporary fixture.
            try:
                job.close()
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


class _CheckCancelled(RuntimeError):
    pass


def _communicate_until_done(process, timeout, cancel_event):
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise _CheckCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.communicate(timeout=min(.25, remaining))
        except subprocess.TimeoutExpired:
            continue


def run_live_check(provider_name, report_path, timeout=120, *, provider_overrides=None, cancel_event=None):
    """Return 0 only for a real model answer plus matching actual MCP receipt.

    ``provider_overrides=True`` redirects Codex SQLite/log state into this run's
    temporary directory while retaining the installed CLI's existing account.
    No authentication state or user configuration is read or copied by Arrow.
    """
    if timeout <= 0:
        raise ValueError('timeout must be positive')
    report = {'schema_version': 1, 'synthetic': True, 'provider': provider_name,
              'platform': 'Windows' if sys.platform == 'win32' else 'Linux' if sys.platform.startswith('linux') else sys.platform,
              'status': 'not_run', 'reason': 'not_installed', 'model_answer_verified': False,
              'receipt_verified': False, 'image_answer_matches': False, 'context_answer_matches': False,
              'capture_id_matches': False}
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise _CheckCancelled()
        provider = create_provider(provider_name)
        if provider.detect():
            with tempfile.TemporaryDirectory(prefix='arrow-live-check-') as temporary:
                directory = Path(temporary)
                fixture = _create_fixture(directory)
                overrides = ({'sqlite_home': str(directory / 'codex-state'), 'log_dir': str(directory / 'codex-logs')}
                             if provider_overrides is True else provider_overrides)
                command = _command(provider, directory, fixture, overrides)
                options = {'cwd': directory / 'repository', 'shell': False,
                           'stdin': subprocess.DEVNULL, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
                           'text': True, 'encoding': 'utf-8', 'errors': 'replace',
                           'env': {**os.environ, 'ARROW_HOME': str(directory / 'home'),
                                   'ARROW_DB_PATH': str(directory / 'captures.db'),
                                   'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}}
                job = None
                if sys.platform == 'win32':
                    from arrow.providers._windows_job import start_job_process
                    options['creationflags'] = subprocess.CREATE_NO_WINDOW
                    process, job = start_job_process(command, **options)
                else:
                    process = subprocess.Popen(command, start_new_session=True, **options)
                try:
                    stdout, stderr = _communicate_until_done(process, timeout, cancel_event)
                except _CheckCancelled:
                    report.update(status='failed', reason='cancelled')
                except subprocess.TimeoutExpired:
                    report.update(status='failed', reason='timeout')
                else:
                    answer = _answer(stdout, provider_name)
                    receipt = _receipt_matches(directory / 'receipt.jsonl', fixture)
                    report['receipt_verified'] = receipt
                    for key, field in [('image_code', 'image_answer_matches'), ('context_code', 'context_answer_matches'),
                                       ('capture_id', 'capture_id_matches')]:
                        report[field] = answer is not None and answer.get(key) == fixture[key]
                    passed = process.returncode == 0 and receipt and all(report[key] for key in (
                        'image_answer_matches', 'context_answer_matches', 'capture_id_matches'))
                    report.update(status='passed' if passed else 'failed',
                                  reason='verified' if passed else _failure_reason(stderr) if process.returncode else 'unverified_answer',
                                  model_answer_verified=passed)
                finally:
                    _stop_process_tree(process, job)
                    # Pipes may still have buffered provider output; never persist it.
                    if process.stdout:
                        process.stdout.close()
                    if process.stderr:
                        process.stderr.close()
    except _CheckCancelled:
        report.update(status='failed', reason='cancelled')
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        report.update(status='failed', reason='startup_or_cleanup_failed', model_answer_verified=False)
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1
