"""CLI installation and account setup, separate from running an agent task.

Call status checks on a background thread: the CLI may consult its OS credential
store. Arrow consumes only its sign-in status and never reads or saves tokens,
account details, or API keys. Login is an explicit user action and is delegated
to the provider's official browser/console flow.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from arrow.providers.runner import create_provider

_PROBE_TIMEOUT = 8
_COMMANDS = {
    "Claude Code": (
        ("auth", "status", "--json"),
        ("auth", "login"),
        "https://code.claude.com/docs/en/setup",
    ),
    "Codex": (
        ("login", "status"),
        ("login",),
        "https://developers.openai.com/codex/cli/",
    ),
}


@dataclass(frozen=True)
class ProviderSetupStatus:
    name: str
    installed: bool
    authenticated: bool | None
    message: str


def _details(name: str) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    try:
        return _COMMANDS[name]
    except KeyError:
        raise ValueError(f"Unknown provider: {name}") from None


def get_provider_install_url(name: str) -> str:
    """Return installation instructions; this never installs software."""
    return _details(name)[2]


def get_provider_setup_status(name: str) -> ProviderSetupStatus:
    """Probe documented auth status with a timeout, without starting an agent.

    ``authenticated=None`` means installed but sign-in could not be confirmed.
    Raw subprocess output is deliberately never logged or returned to the UI.
    """
    status_args, _, _ = _details(name)
    provider = create_provider(name)
    if not provider.detect():
        return ProviderSetupStatus(name, False, False, f"Install {name} to connect.")
    unknown = ProviderSetupStatus(name, True, None, "Installed. Sign-in not confirmed; try Connect or update the CLI.")
    try:
        command = provider._resolve_command([provider.cli_name, *status_args])
        result = subprocess.run(
            command,
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired:
        return ProviderSetupStatus(name, True, None, "Sign-in check timed out. Try again or choose Connect.")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return unknown

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if any(marker in output.lower() for marker in (
        "unknown command", "unrecognized subcommand", "unknown option", "unrecognized option", "unexpected argument",
    )):
        return ProviderSetupStatus(name, True, None, "Update the CLI to check sign-in, or use Connect.")
    authenticated = None
    if name == "Claude Code":
        try:
            parsed = json.loads(result.stdout)
        except (ValueError, TypeError):
            return unknown
        if isinstance(parsed, dict) and type(parsed.get("loggedIn")) is bool:
            if result.returncode == 0:
                authenticated = parsed["loggedIn"]
            elif result.returncode == 1 and parsed["loggedIn"] is False:
                authenticated = False
    else:
        lines = [line.strip() for line in output.splitlines()]
        if result.returncode == 0 and any(line.startswith(("Logged in using ", "API key configured -")) for line in lines):
            authenticated = True
        elif result.returncode == 1 and "Not logged in" in lines:
            authenticated = False
    if authenticated is None:
        return unknown
    message = "Connected." if authenticated else "Installed. Sign in to connect."
    return ProviderSetupStatus(name, True, authenticated, message)


def start_provider_login(name: str) -> subprocess.Popen:
    """Start the official login flow, with a visible console on Windows.

    The caller can poll the returned process, then refresh setup status. Process
    launch and process exit alone do not establish successful authentication.
    """
    _, login_args, _ = _details(name)
    provider = create_provider(name)
    if not provider.detect():
        raise RuntimeError(f"Install {name} before connecting.")
    try:
        command = provider._resolve_command([provider.cli_name, *login_args])
        return subprocess.Popen(
            command,
            cwd=str(Path.home()),
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10) if sys.platform == "win32" else 0,
        )
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"Could not start {name} sign-in. Repair or update the CLI and try again.") from exc


__all__ = [
    "ProviderSetupStatus",
    "get_provider_setup_status",
    "start_provider_login",
    "get_provider_install_url",
]
