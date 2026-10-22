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

import base64
import hmac
import json
import logging
import os
import secrets
import threading
import time
from enum import Enum
from typing import Iterable, Optional

log = logging.getLogger("arrow.server.security")

# Config rationale (audit §7):
#   * 8 MiB request cap — bounds Flask's in-memory buffer for the local API;
#     actual image uploads are further limited by size, dimension, and pixel
#     count in arrow/server/screenshots.py before any decoding.
#   * Loopback-only hosts / origin allow-list — this is a single-user desktop
#     tool, so the trust boundary is the machine itself; keeping the server
#     off the network (and rejecting non-local browser origins) blocks remote
#     callers and DNS-rebinding/CSRF-style access from web pages.
MAX_REQUEST_BYTES = 8 * 1024 * 1024  # 8 MiB
LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Share tokens are short-lived by design: long enough for a consumer to fetch
# an image, short enough that a leaked URL stops working quickly.
DEFAULT_SHARE_TTL_SECONDS = 15 * 60


def _config_dir() -> str:
    from arrow.core.config import resolve_home

    base = resolve_home()
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


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def is_safe_filename(filename: str) -> bool:
    """Reject path traversal, separators and other unsafe upload names."""
    if not filename or not isinstance(filename, str):
        return False
    if len(filename) > 255:
        return False
    if filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename or "\x00" in filename:
        return False
    # No absolute paths or Windows drive letters.
    if filename[0] in "/\\" or (len(filename) > 1 and filename[1] == ":"):
        return False
    return True


class ShareTokenManagerMintError(Exception):
    """Raised when a share token cannot be minted."""


class ShareTokenManager:
    """Mints and verifies short-lived, single-file scoped access tokens.

    A share token authorizes exactly one screenshot filename for a bounded
    time. It lets an approved consumer (Agentation, a copied link) fetch a
    shared capture without holding the long-lived per-install bearer token.

    Format: ``<payload-b64url>.<hmac-b64url>`` where the payload is
    ``{"f": filename, "n": nonce, "e": expiry_epoch}`` and the MAC is derived
    from the per-install bearer token so the share key never leaves the host.
    """

    def __init__(self, token_manager: "TokenManager", ttl_seconds: int = DEFAULT_SHARE_TTL_SECONDS,
                 clock=time.time):
        self._token_manager = token_manager
        self._ttl = max(1, int(ttl_seconds))
        self._clock = clock

    def _signing_key(self) -> bytes:
        return ("arrow-share:" + self._token_manager.get_or_create()).encode("utf-8")

    def mint(self, filename: str, ttl_seconds: Optional[int] = None) -> str:
        if not is_safe_filename(filename):
            raise ShareTokenManagerMintError(f"Refusing to share unsafe filename: {filename!r}")
        ttl = self._ttl if ttl_seconds is None else max(1, int(ttl_seconds))
        payload = {
            "f": filename,
            "n": secrets.token_urlsafe(8),
            "e": int(self._clock()) + ttl,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        body = _b64url_encode(raw)
        mac = hmac.new(self._signing_key(), body.encode("ascii"), "sha256").digest()
        return f"{body}.{_b64url_encode(mac)}"

    def verify(self, token: Optional[str], filename: str) -> bool:
        """True only when the token is well-formed, unexpired and scoped to *filename*."""
        if not token or not isinstance(token, str) or "." not in token:
            return False
        body, _, mac_part = token.partition(".")
        if not body or not mac_part:
            return False
        try:
            expected = hmac.new(self._signing_key(), body.encode("ascii"), "sha256").digest()
            presented = _b64url_decode(mac_part)
        except (ValueError, TypeError):
            return False
        if not hmac.compare_digest(expected, presented):
            return False
        try:
            payload = json.loads(_b64url_decode(body))
        except (ValueError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("f") != filename:
            return False
        expiry = payload.get("e")
        if not isinstance(expiry, int) or expiry < int(self._clock()):
            return False
        return True

    def share_url(self, base_url: str, filename: str, ttl_seconds: Optional[int] = None) -> str:
        token = self.mint(filename, ttl_seconds=ttl_seconds)
        return f"{base_url}/screenshots/{filename}?t={token}"

    def extract(self, args, headers) -> Optional[str]:
        """Pull a share token from the query string or ``X-Arrow-Share`` header."""
        token = None
        try:
            token = args.get("t")
        except Exception:  # pragma: no cover - defensive
            token = None
        if not token:
            try:
                token = headers.get("X-Arrow-Share")
            except Exception:  # pragma: no cover - defensive
                token = None
        if isinstance(token, (list, tuple)):
            token = token[0] if token else None
        return token or None


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
            from arrow.core.config import env_value

            raw = env_value("ARROW_ENABLED_CAPABILITIES")
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
    "DEFAULT_SHARE_TTL_SECONDS",
    "Capability",
    "DEFAULT_ENABLED",
    "SENSITIVE_CAPABILITIES",
    "TokenManager",
    "CapabilityManager",
    "ShareTokenManager",
    "ShareTokenManagerMintError",
    "is_safe_filename",
    "parse_bearer",
    "is_localhost_origin",
]
