"""Persisted application settings.

Stores capture preferences and the user-selected project directory so the orchestrator can
collect repository context (branch, commit, framework) and one-click provider
runs stay confined to the right repository. Backed by a small JSON file under
``~/.arrow`` (override with ``ARROW_HOME``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from arrow.core.paths import application_home

log = logging.getLogger("arrow.storage.settings")


def config_dir() -> str:
    base = str(application_home())
    os.makedirs(base, exist_ok=True)
    return base


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def _load() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    temporary_path = None
    try:
        # Replace from the same directory so a failed write cannot truncate
        # the user's previous project or capture preferences.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_dir(), prefix="config.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = stream.name
            json.dump(data, stream, indent=2)
        os.replace(temporary_path, config_path())
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def get_project_dir() -> Optional[str]:
    """The last selected project directory, or None when unset/invalid."""
    path = _load().get("selected_project_dir")
    if path and os.path.isdir(path):
        return path
    return None


def set_project_dir(path: str) -> None:
    """Persist the selected project directory (validated to exist)."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        log.warning("Not persisting project dir: %s is not a directory", path)
        return
    data = _load()
    data["selected_project_dir"] = path
    _save(data)


DEFAULT_CAPTURE_SHORTCUT = "ctrl+space"
DEFAULT_SPEECH_LANGUAGE = "en-IN"
SPEECH_LANGUAGES = ("en-IN", "hi-IN", "en-US")


def get_capture_shortcut() -> str:
    """The held capture shortcut, defaulting to Ctrl+Space."""
    value = _load().get("capture_shortcut")
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_CAPTURE_SHORTCUT


def get_speech_language() -> str:
    """The preferred recognition language, defaulting to Indian English."""
    value = _load().get("speech_language")
    return value if value in SPEECH_LANGUAGES else DEFAULT_SPEECH_LANGUAGE


def set_capture_preferences(shortcut: str, language: str) -> None:
    """Persist preferences after the caller validates/registers the shortcut."""
    data = _load()
    data["capture_shortcut"] = shortcut.strip()
    data["speech_language"] = language
    _save(data)


__all__ = [
    "config_dir", "config_path", "get_project_dir", "set_project_dir",
    "get_capture_shortcut", "get_speech_language", "set_capture_preferences",
]
