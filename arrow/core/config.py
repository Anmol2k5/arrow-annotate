"""Centralized, validated application configuration.

Single source of truth for runtime settings. Resolution order (last wins):

1. Built-in defaults (secure: loopback-only, standard ports).
2. A ``.env`` file in the repository/working directory (if present).
3. Real process environment variables.

Every value is validated here so no caller has to re-validate ports or hosts.
Security-enforced properties (bearer token contents, capability defaults) are
deliberately *not* configurable through the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

LOCALHOST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_ENV_KEYS = (
    "ARROW_HOME",
    "ARROW_HTTP_HOST",
    "ARROW_HTTP_PORT",
    "ARROW_WS_HOST",
    "ARROW_WS_PORT",
    "ARROW_AGENTATION_URL",
    "ARROW_LOG_LEVEL",
    "ARROW_ENABLED_CAPABILITIES",
    "ARROW_VOICE_TRANSCRIPTION",
    "ARROW_ALLOW_NON_LOOPBACK",
)


class ConfigError(ValueError):
    """Raised when configuration is invalid; message is safe to show to users."""


def load_dotenv(path: Optional[str] = None) -> Dict[str, str]:
    """Parse a ``.env`` file into a dict without overriding real env vars.

    Supports ``KEY=value`` lines, optional ``export `` prefix, ``#`` comments
    and quoted values. No new dependency is introduced for this.
    """
    path = path or os.path.join(os.getcwd(), ".env")
    values: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except (OSError, UnicodeDecodeError):
        return values

    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _parse_port(raw: Optional[str], default: int, name: str) -> int:
    if raw is None or raw == "":
        return default
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer between 1 and 65535, got {raw!r}") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"{name} must be between 1 and 65535, got {port}")
    return port


def _parse_host(raw: Optional[str], default: str, name: str, allow_non_loopback: bool) -> str:
    host = (raw or default).strip()
    if not host:
        raise ConfigError(f"{name} must not be empty")
    if host not in LOCALHOST_HOSTS and not allow_non_loopback:
        raise ConfigError(
            f"{name}={host!r} is not a loopback address. Arrow binds to loopback only "
            "by default; set ARROW_ALLOW_NON_LOOPBACK=1 to deliberately expose the "
            "local server to your network (the bearer token is then the only guard)."
        )
    return host


def _parse_log_level(raw: Optional[str], default: str = "INFO") -> str:
    level = (raw or default).strip().upper() or default
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if level not in allowed:
        raise ConfigError(f"ARROW_LOG_LEVEL must be one of {sorted(allowed)}, got {level!r}")
    return level


def _parse_bool(raw: Optional[str]) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


_VOICE_TRANSCRIPTION_MODES = ("google", "off")


def _parse_voice_transcription(raw: Optional[str]) -> str:
    value = (raw or "google").strip().lower() or "google"
    if value not in _VOICE_TRANSCRIPTION_MODES:
        raise ConfigError(
            f"ARROW_VOICE_TRANSCRIPTION must be one of "
            f"{', '.join(_VOICE_TRANSCRIPTION_MODES)}, got {raw!r}"
        )
    return value


@dataclass(frozen=True)
class AppConfig:
    """Validated runtime configuration."""

    home: str
    http_host: str
    http_port: int
    ws_host: str
    ws_port: int
    agentation_url: str
    log_level: str
    enabled_capabilities: Optional[str] = None
    voice_transcription: str = "google"
    env: Mapping[str, str] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.http_host == "localhost" else self.http_host
        return f"http://{host}:{self.http_port}"

    @property
    def ws_url(self) -> str:
        host = "127.0.0.1" if self.ws_host == "localhost" else self.ws_host
        return f"ws://{host}:{self.ws_port}"


def _merged_env(override: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """dotenv values first, real environment (and explicit override) last."""
    values = dict(load_dotenv())
    if override:
        values.update(override)
    for key in _ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def load_config(override: Optional[Mapping[str, str]] = None) -> AppConfig:
    """Load and validate configuration. Raises :class:`ConfigError` when invalid."""
    env = _merged_env(override)
    allow_non_loopback = _parse_bool(env.get("ARROW_ALLOW_NON_LOOPBACK"))

    home = env.get("ARROW_HOME") or os.path.join(os.path.expanduser("~"), ".arrow")
    home = os.path.abspath(os.path.expanduser(home))

    http_host = _parse_host(env.get("ARROW_HTTP_HOST"), "127.0.0.1", "ARROW_HTTP_HOST", allow_non_loopback)
    ws_host = _parse_host(env.get("ARROW_WS_HOST"), "127.0.0.1", "ARROW_WS_HOST", allow_non_loopback)

    return AppConfig(
        home=home,
        http_host=http_host,
        http_port=_parse_port(env.get("ARROW_HTTP_PORT"), 5001, "ARROW_HTTP_PORT"),
        ws_host=ws_host,
        ws_port=_parse_port(env.get("ARROW_WS_PORT"), 5002, "ARROW_WS_PORT"),
        agentation_url=(env.get("ARROW_AGENTATION_URL") or "http://127.0.0.1:4747").strip(),
        log_level=_parse_log_level(env.get("ARROW_LOG_LEVEL")),
        enabled_capabilities=env.get("ARROW_ENABLED_CAPABILITIES") or None,
        voice_transcription=_parse_voice_transcription(env.get("ARROW_VOICE_TRANSCRIPTION")),
        env=env,
    )


def env_value(key: str, default: str = "") -> str:
    """Uncached lookup of a single config key: real env wins over ``.env``.

    Consumers that construct objects at import time (token store, capability
    manager) cannot wait for :func:`get_config` and must still honor values
    advertised in ``.env``.
    """
    if key in os.environ:
        return os.environ[key]
    return load_dotenv().get(key, default)


def resolve_home() -> str:
    """ARROW_HOME from env/``.env`` (default ``~/.arrow``), uncached."""
    home = env_value("ARROW_HOME") or os.path.join(os.path.expanduser("~"), ".arrow")
    return os.path.abspath(os.path.expanduser(home))


_cached: Optional[AppConfig] = None


def get_config(refresh: bool = False) -> AppConfig:
    """Process-wide cached configuration."""
    global _cached
    if _cached is None or refresh:
        _cached = load_config()
    return _cached


def reset_config_cache() -> None:
    """Testing hook: drop the cached configuration."""
    global _cached
    _cached = None


def port_available(host: str, port: int) -> bool:
    """True when nothing is already listening on ``host:port``."""
    import socket

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


__all__ = [
    "AppConfig",
    "ConfigError",
    "LOCALHOST_HOSTS",
    "get_config",
    "load_config",
    "env_value",
    "load_dotenv",
    "port_available",
    "reset_config_cache",
    "resolve_home",
]
