"""
Local server security (Phase 14).

Provides the primitives to lock down Arrow's local HTTP surface:

  * a random per-install bearer token,
  * localhost-only binding helpers,
  * origin validation,
  * a capability model where sensitive capabilities are disabled by default,
  * request-size limits.

No user-provided string is ever passed to a shell; command execution as a
general capability is disabled by default and not exposed as an endpoint.

Sensitive capabilities stay disabled unless the user explicitly opts in by
setting ``ARROW_ENABLED_CAPABILITIES`` (comma-separated capability names, e.g.
``control_native``) in the environment before starting the server.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
from enum import Enum
from typing import Iterable, Optional

log = logging.getLogger("arrow.server.security")

MAX_REQUEST_BYTES = 8 * 1024 * 1024  # 8 MiB
LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _config_dir() -> str:
    base = os.environ.get("ARROW_HOME") or os.path.join(
        os.path.expanduser("~"), ".arrow"
    )
    os.makedirs(base, exist_ok=True)
    return base


class Capability(str, Enum):
    READ_SCREENSHOT = "read_screenshot"
    READ_CAPTURE_CONTEXT = "read_capture_context"
    READ_REPO_CONTEXT = "read_repo_context"
    RUN_PROVIDER = "run_provider"
    CONTROL_NATIVE = "control_native"
    EXECUTE_COMMAND = "execute_command"
    MODIFY_FILES = "modify_files"


# Only read capabilities are enabled by default. Everything that can mutate the
# machine is opt-in.
DEFAULT_ENABLED: frozenset[Capability] = frozenset({
    Capability.READ_SCREENSHOT,
    Capability.READ_CAPTURE_CONTEXT,
    Capability.READ_REPO_CONTEXT,
})

SENSITIVE_CAPABILITIES: frozenset[Capability] = frozenset({
    Capability.RUN_PROVIDER,
    Capability.CONTROL_NATIVE,
    Capability.EXECUTE_COMMAND,
    Capability.MODIFY_FILES,
})


class TokenManager:
    """Manages a random per-install bearer token persisted to the config dir."""

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(_config_dir(), "token")
        self._token: Optional[str] = None
        # Flask runs threaded; the first-ever request may race to create the
        # token. Without a lock two tokens could be generated, leaving the
        # in-memory token out of sync with the file and rejecting valid tokens.
        self._lock = threading.Lock()

    def get_or_create(self) -> str:
        with self._lock:
            if self._token:
                return self._token
            if os.path.isfile(self._path):
                with open(self._path, encoding="utf-8") as f:
                    token = f.read().strip()
                if token:
                    self._token = token
                    return token
            token = secrets.token_urlsafe(32)
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(token)
            try:
                os.chmod(self._path, 0o600)
                import platform
                if platform.system() == "Windows":
                    import subprocess
                    username = os.environ.get("USERNAME")
                    if username:
                        subprocess.run(
                            ["icacls", self._path, "/inheritance:r", "/grant", f"{username}:F"],
                            check=True,
                            capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        )
            except OSError:  # pragma: no cover - platform dependent
                pass
            except Exception as e:
                log.warning("Failed to set Windows ACLs on token file: %s", e)
            self._token = token
            return token

    def verify(self, presented: Optional[str]) -> bool:
        if not presented or not isinstance(presented, str):
            return False
        expected = self.get_or_create()
        return hmac.compare_digest(presented, expected)


def parse_bearer(header_value: Optional[str]) -> Optional[str]:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def is_localhost_origin(origin: Optional[str]) -> bool:
    """Validate that an Origin header (if present) is localhost.

    A missing Origin (e.g. non-browser client) is allowed; a present, non-local
    Origin is rejected.
    """
    if not origin:
        return True
    from urllib.parse import urlparse

    host = urlparse(origin).hostname
    return host in LOCALHOST_HOSTS


class CapabilityManager:
    """Tracks which capabilities are enabled; sensitive ones default off.

    Opt-in happens via the ``ARROW_ENABLED_CAPABILITIES`` environment variable
    (comma-separated capability names, e.g. ``control_native``) so that the
    user explicitly consents before mutating capabilities work.
    """

    def __init__(self, enabled: Optional[Iterable[Capability]] = None):
        if enabled is not None:
            self._enabled: set[Capability] = set(enabled)
        else:
            self._enabled = set(DEFAULT_ENABLED)
            raw = os.environ.get("ARROW_ENABLED_CAPABILITIES", "")
            for name in (part.strip() for part in raw.split(",") if part.strip()):
                try:
                    self._enabled.add(Capability(name))
                except ValueError:
                    log.warning("Ignoring unknown ARROW_ENABLED_CAPABILITIES entry: %s", name)

    def is_enabled(self, capability: Capability) -> bool:
        return capability in self._enabled

    def enable(self, capability: Capability) -> None:
        log.info("Enabling capability: %s", capability.value)
        self._enabled.add(capability)

    def disable(self, capability: Capability) -> None:
        self._enabled.discard(capability)

    def enabled_set(self) -> set[Capability]:
        return set(self._enabled)


__all__ = [
    "MAX_REQUEST_BYTES",
    "LOCALHOST_HOSTS",
    "Capability",
    "DEFAULT_ENABLED",
    "SENSITIVE_CAPABILITIES",
    "TokenManager",
    "CapabilityManager",
    "parse_bearer",
    "is_localhost_origin",
]
