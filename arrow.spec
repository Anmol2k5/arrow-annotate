# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows desktop build.

Produces a single-folder ``dist/ArrowAnnotate/ArrowAnnotate.exe`` with no
console window. A one-file build was rejected on purpose: it unpacks to a
temp directory on every launch, which is slow for a tray-style app that
starts on login, and it breaks the ``mss``/``uiautomation`` native probing
that Arrow relies on.

User data never lives next to the executable: everything resolves through
``ARROW_HOME`` (default ``~/.arrow``). That is what makes it safe to run
from Program Files.
"""

import os

block_cipher = None

# uiautomation is imported lazily by the resolvers but must ship.
hidden = [
    "uiautomation",
    "mss",
    "mss.windows",
    "PIL._tkinter_finder",
    "speech_recognition",
]

datas = []

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Our own package plus the desktop stack only; the dev/test tooling is
    # excluded so the build stays small and leaks no test surface.
    excludes=[
        "pytest", "mypy", "ruff", "tkinter", "IPython", "notebook",
        "matplotlib", "pandas", "scipy", "setuptools._distutils",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ArrowAnnotate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A tray/overlay app must never spawn a console window.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No icon asset is bundled yet; Windows falls back to the default.
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ArrowAnnotate",
)