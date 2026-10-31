"""Visible, client-specific handoff. Launching a client is not task completion."""
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from arrow.context.capture_bundle import build_capture_bundle
from arrow.core.paths import application_home
from arrow.providers.runner import create_provider


@dataclass(frozen=True)
class HandoffResult:
    message: str
    prompt_text: str = ''
    status: str = 'opened'


def _registered(scheme):
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme):
            return True
    except OSError:
        return False


def available_clients():
    return {name: create_provider(name).detect() for name in ('Codex', 'Claude Code')} | {
        'Codex desktop': _registered('codex'), 'VS Code': _registered('vscode'),
    }


def mcp_server_config():
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).with_name('ArrowMCP.exe')
        if not executable.is_file():
            raise RuntimeError('ArrowMCP.exe is missing. Reinstall Arrow.')
        command, args = str(executable), ['--mcp']
    else:
        command, args = sys.executable, [str(Path(__file__).resolve().parents[2] / 'main.py'), '--mcp']
    from arrow.storage.database import DB_PATH
    return {'command': command, 'args': args, 'env': {
        'ARROW_HOME': str(application_home()), 'ARROW_DB_PATH': str(Path(DB_PATH).resolve())}}


def handoff_capture(capture_id, name, db_path=None):
    bundle = build_capture_bundle(capture_id, db_path)
    from arrow.storage.settings import get_project_dir
    repo = bundle.metadata.get('repository_path') or get_project_dir()
    if not repo or not os.path.isdir(repo):
        raise ValueError('Select an existing project repository before opening an agent.')
    config = mcp_server_config()
    if db_path:
        config['env']['ARROW_DB_PATH'] = str(Path(db_path).resolve())
    prompt = (f'Use repository {repo}. Use Arrow capture {capture_id}. Call arrow_get_capture_bundle with this capture_id via MCP. '
              f'Also read the complete capture packet at {bundle.context_path}. '
              f'Read the annotated image at {bundle.annotated_path}. '
              'Follow the current_instruction, preserve responsive behavior, and ask about blocking ambiguities.')
    if name in ('Codex', 'Claude Code'):
        provider = create_provider(name)
        if not provider.detect():
            raise RuntimeError(f'{name} CLI is not installed. Open Settings → Agents.')
        if name == 'Codex':
            command = ['codex', '--sandbox', 'workspace-write', '--cd', repo]
            for key, value in config.items():
                command.extend(['-c', f'mcp_servers.arrow.{key}={json.dumps(value, ensure_ascii=False)}'] if key != 'env'
                               else ['-c', 'mcp_servers.arrow.env=' + '{' + ','.join(
                                   f'{k}={json.dumps(v, ensure_ascii=False)}' for k, v in value.items()) + '}'])
            if bundle.annotated_path:
                command.extend(['--image', bundle.annotated_path])
        else:
            command = ['claude', '--permission-mode', 'default', '--mcp-config', json.dumps({'mcpServers': {'arrow': config}}, ensure_ascii=False),
                       '--add-dir', bundle.directory]
        command.extend(['--', prompt])
        subprocess.Popen(provider._resolve_command(command), cwd=repo, shell=False,
                         creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0) if sys.platform == 'win32' else 0)
        return HandoffResult(f'{name} interactive session opened with the capture context. Continue in its window.', status='started')
    scheme = {'Codex desktop': 'codex', 'VS Code': 'vscode'}.get(name)
    if not scheme or not _registered(scheme):
        raise RuntimeError('This client is not installed or has no supported launch protocol.')
    if name == 'VS Code':
        uri = 'vscode://agents/new?' + urlencode({'prompt': bundle.prompt_text, 'workspace': Path(repo).as_uri()})
        if len(uri) > 30000:
            uri = 'vscode://agents/new?' + urlencode({'prompt': prompt, 'workspace': Path(repo).as_uri()})
        os.startfile(uri)
        return HandoffResult('VS Code agent draft opened. Choose your model before submitting.')
    os.startfile('codex://threads/new?' + urlencode({'path': repo}))
    return HandoffResult('Codex opened. Full context copied: paste into its prompt. Automatic desktop prefill is not supported by its documented launcher.',
                         bundle.prompt_text, 'ready_to_paste')
