"""Separate bundled read-only resources from each user's writable data."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def application_home() -> Path:
    """Settings, tokens, logs, and installed-app data (keeps existing ~/.arrow)."""
    override = os.environ.get('ARROW_HOME')
    return Path(override).expanduser().resolve() if override else Path.home() / '.arrow'


def data_dir() -> Path:
    """Source checkouts retain their original data; installed apps never write to the bundle."""
    if os.environ.get('ARROW_HOME') or getattr(sys, 'frozen', False):
        return application_home()
    return PROJECT_ROOT


def resource_dir() -> Path:
    """PyInstaller's shared _internal directory, or the source checkout."""
    return Path(getattr(sys, '_MEIPASS', PROJECT_ROOT))
