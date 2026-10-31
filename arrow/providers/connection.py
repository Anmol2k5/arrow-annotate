"""Register Arrow with official client CLIs and verify its local stdio protocol.

Registration, a working local MCP server, and account authentication are separate
facts. These checks never start an agent session or read account credentials.
Call them from a worker thread, since client commands and the probe are bounded
but may take several seconds. Unknown CLI output is never treated as absence.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from arrow.providers.handoff import mcp_server_config
from arrow.providers.runner import create_provider

_CLI_TIMEOUT = 8
_PROTOCOL_TIMEOUT = 8
_MAX_RESPONSE = 1024 * 1024
_NAMES = {'Codex', 'Claude Code'}


@dataclass(frozen=True)
class ProviderMCPStatus:
    name: str
    installed: bool
    registered: bool | None
    protocol_verified: bool | None
    message: str
    conflict: bool = False


def _provider(name):
    if name not in _NAMES:
        raise ValueError(f'Unknown provider: {name}')
    return create_provider(name)


def _flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if sys.platform == 'win32' else 0


def _run(provider, args):
    return subprocess.run(
        provider._resolve_command([provider.cli_name, 'mcp', *args]),
        cwd=str(Path.home()), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', timeout=_CLI_TIMEOUT,
        shell=False, check=False, creationflags=_flags(),
    )


def _registration(name, provider, expected):
    """Return (matches, conflict). None means we cannot safely determine absence."""
    args = ['get', 'arrow', '--json'] if name == 'Codex' else ['get', 'arrow']
    result = _run(provider, args)
    if result.returncode:
        # Only the documented missing-entry diagnostic permits an add. A
        # timeout, broken config or old CLI must never cause an overwrite.
        missing = ("No MCP server named 'arrow' found." if name == 'Codex'
                   else 'No MCP server found with name: arrow')
        lines = ((result.stdout or '') + '\n' + (result.stderr or '')).splitlines()
        if any(line.strip().removeprefix('Error: ') == missing for line in lines):
            return False, False
        return None, False
    if name == 'Codex':
        try:
            entry = json.loads(result.stdout)
        except (ValueError, TypeError):
            return None, False
        if not isinstance(entry, dict) or entry.get('name') != 'arrow':
            return None, False
        transport = entry.get('transport')
        if not isinstance(transport, dict):
            return None, False
        matches = (
            entry.get('enabled', True) is True
            and transport.get('type') == 'stdio'
            and all(transport.get(key, {} if key == 'env' else []) == value
                    for key, value in expected.items())
            and not transport.get('env_vars')
            and not transport.get('cwd')
            and entry.get('enabled_tools') is None
            and not entry.get('disabled_tools')
        )
        return matches, not matches
    # Claude's documented `mcp get` prints labeled text rather than JSON. Match
    # complete fields; never split a command/path on spaces or trust its status
    # line (which can report client connectivity independently of this probe).
    fields = {}
    environment = {}
    in_environment = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped == 'Environment:':
            in_environment = True
            continue
        if in_environment and '=' in stripped and line.startswith('    '):
            key, value = stripped.split('=', 1)
            environment[key] = value
            continue
        in_environment = False
        for key in ('Type', 'Command', 'Args'):
            if stripped.startswith(key + ':'):
                if key in fields:
                    return None, False
                fields[key] = stripped[len(key) + 1:].strip()
    if fields.get('Type') not in (None, 'stdio'):
        return False, True
    if not {'Type', 'Command', 'Args'} <= fields.keys():
        return None, False
    matches = (fields['Type'] == 'stdio' and fields['Command'] == expected['command']
               and fields['Args'] == ' '.join(expected['args']) and environment == expected['env'])
    return matches, not matches


def configure_provider_mcp(name: str) -> ProviderMCPStatus:
    """Register only Arrow if absent; preserve existing and unrelated entries.

    A conflicting Arrow entry is reported for the user to review in the client.
    This function deliberately has no implicit replacement/remove operation.
    """
    provider = _provider(name)
    if not provider.detect():
        return ProviderMCPStatus(name, False, False, None, f'Install {name} before configuring Arrow MCP.')
    try:
        expected = mcp_server_config()
        registered, conflict = _registration(name, provider, expected)
        if conflict:
            return ProviderMCPStatus(name, True, False, None,
                                     'An existing arrow MCP entry differs. Review it in the client before configuring.', True)
        if registered is None:
            return ProviderMCPStatus(name, True, None, None,
                                     'Could not verify the client MCP configuration. Update or repair the CLI and retry.')
        if not registered:
            args = ['add']
            if name == 'Claude Code':
                args += ['--scope', 'user', '--transport', 'stdio']
            for key, value in expected['env'].items():
                args += ['--env', f'{key}={value}']
            args += ['arrow', '--', expected['command'], *expected['args']]
            result = _run(provider, args)
            if result.returncode:
                return ProviderMCPStatus(name, True, None, None,
                                         'The client could not register Arrow MCP. Review its configuration and retry.')
            registered, conflict = _registration(name, provider, expected)
        if registered:
            return ProviderMCPStatus(name, True, True, None,
                                     'Arrow MCP registered in the client. Test connection to verify the local server.')
        return ProviderMCPStatus(name, True, registered, None,
                                 'The client registration could not be verified. Review its arrow MCP entry.', conflict)
    except subprocess.TimeoutExpired:
        return ProviderMCPStatus(name, True, None, None, 'MCP configuration check timed out. Retry when the client is ready.')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ProviderMCPStatus(name, True, None, None, 'Could not configure Arrow MCP. Repair the installation and retry.')


def _probe_local_protocol(config):
    """Exchange initialize, initialized and tools/list without touching captures."""
    process = None
    reader = None
    responses = queue.Queue(maxsize=4)
    overflow = threading.Event()
    deadline = time.monotonic() + _PROTOCOL_TIMEOUT
    try:
        process = subprocess.Popen(
            [config['command'], *config['args']], cwd=str(Path.home()),
            env={**os.environ, **config['env'], 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='strict', bufsize=1,
            shell=False, creationflags=_flags(),
        )

        def read_responses():
            try:
                while True:
                    line = process.stdout.readline(_MAX_RESPONSE + 1)
                    if not line:
                        break
                    if len(line) > _MAX_RESPONSE:
                        raise ValueError('MCP response exceeded limit')
                    responses.put_nowait(json.loads(line))
            except (ValueError, OSError, queue.Full):
                overflow.set()
            finally:
                try:
                    responses.put_nowait(None)
                except queue.Full:
                    overflow.set()

        reader = threading.Thread(target=read_responses, daemon=True)
        reader.start()

        def send(payload):
            process.stdin.write(json.dumps(payload) + '\n')
            process.stdin.flush()

        def receive(request_id):
            response = responses.get(timeout=max(0, deadline - time.monotonic()))
            if (overflow.is_set() or not isinstance(response, dict)
                    or response.get('jsonrpc') != '2.0'
                    or type(response.get('id')) is not int or response['id'] != request_id
                    or 'error' in response or not isinstance(response.get('result'), dict)):
                raise ValueError('Invalid MCP response')
            return response['result']

        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'arrow-connection-check', 'version': '1.0'},
        }})
        initialized = receive(1)
        if (initialized.get('protocolVersion') != '2024-11-05'
                or not isinstance(initialized.get('capabilities'), dict)
                or not isinstance(initialized.get('capabilities', {}).get('tools'), dict)
                or initialized.get('serverInfo', {}).get('name') != 'arrow-mcp'):
            raise ValueError('Unexpected MCP initialization')
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        tools = receive(2).get('tools')
        if not isinstance(tools, list) or not tools or any(not isinstance(tool, dict) for tool in tools):
            raise ValueError('Invalid tools list')
        bundle_tools = [tool for tool in tools if tool.get('name') == 'arrow_get_capture_bundle']
        if not bundle_tools or not isinstance(bundle_tools[0].get('inputSchema'), dict):
            raise ValueError('Arrow capture tool missing')
        # EOF lets Arrow exit cleanly and lets the reader validate all stdout,
        # including anything printed after tools/list (startup banners are not
        # allowed anywhere on a stdio MCP protocol stream).
        process.stdin.close()
        process.wait(timeout=max(0, deadline - time.monotonic()))
        reader.join(timeout=max(0, deadline - time.monotonic()))
        if reader.is_alive() or overflow.is_set() or process.returncode != 0:
            raise ValueError('Unexpected MCP stdout or exit')
        if responses.get_nowait() is not None or not responses.empty():
            raise ValueError('Unexpected MCP stdout')
        return True, 'Local MCP initialize and tools/list verified.'
    except (queue.Empty, subprocess.TimeoutExpired):
        return False, 'Local MCP test timed out. Repair the Arrow installation and retry.'
    except (ValueError, TypeError, AttributeError, OSError, RuntimeError, subprocess.SubprocessError):
        return False, 'Local MCP protocol test failed. Repair the Arrow installation and retry.'
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=1)
                    except (OSError, subprocess.SubprocessError):
                        pass
                except OSError:
                    pass
            if reader is not None:
                reader.join(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass


def probe_provider_mcp(name: str) -> ProviderMCPStatus:
    """Verify registry and local protocol separately; never claim an agent session."""
    provider = _provider(name)
    installed = provider.detect()
    if not installed:
        return ProviderMCPStatus(name, False, False, None, f'Install {name} before testing Arrow MCP.')
    registered, conflict = None, False
    try:
        config = mcp_server_config()
    except (OSError, RuntimeError):
        return ProviderMCPStatus(name, True, None, False, 'Arrow MCP executable is missing. Repair the installation.')
    try:
        registered, conflict = _registration(name, provider, config)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    verified, message = _probe_local_protocol(config)
    if conflict:
        message = 'Client arrow MCP entry differs from this installation. ' + message
    elif registered is None:
        message = 'Client registration could not be verified. ' + message
    elif not registered:
        message = 'Arrow MCP is not registered in the client. ' + message
    else:
        message = 'Client registration verified. ' + message
    return ProviderMCPStatus(name, True, registered, verified, message, conflict)


__all__ = ['ProviderMCPStatus', 'configure_provider_mcp', 'probe_provider_mcp']
