"""Persisted application settings.

Currently stores the user-selected project directory so the orchestrator can
collect repository context (branch, commit, framework) and one-click provider
runs stay confined to the right repository. Backed by a small JSON file under
``~/.arrow`` (override with ``ARROW_HOME``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger("arrow.storage.settings")


def config_dir() -> str:
    base = os.environ.get("ARROW_HOME") or os.path.join(os.path.expanduser("~"), ".arrow")
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
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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


__all__ = ["config_dir", "config_path", "get_project_dir", "set_project_dir"]
