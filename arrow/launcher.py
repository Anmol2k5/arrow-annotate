"""Console-safe entry point shared by source, desktop EXE, and MCP EXE."""
from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from arrow.core.paths import application_home


def app_version() -> str:
    try:
        return importlib.metadata.version('arrow-annotate')
    except importlib.metadata.PackageNotFoundError:
        return 'development'


def _show_message(message: str) -> None:
    if platform.system() == 'Windows':
        try:
            getattr(ctypes, 'windll').user32.MessageBoxW(None, message, 'Arrow Annotate', 0x40)
            return
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def _desktop_logging() -> Path:
    directory = application_home() / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.name == 'arrow-desktop-file':
            root.removeHandler(handler)
            handler.close()
    path = directory / 'ArrowAnnotate.log'
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.name = 'arrow-desktop-file'
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Windowed PyInstaller executables have no stdout/stderr. Some libraries
    # still write there; provide a real stream without opening a console.
    if sys.stdout is None or sys.stderr is None:
        stream = (directory / 'console.log').open('a', encoding='utf-8', buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    return path


def entrypoint(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Arrow Annotate desktop and agent integration')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--version', action='store_true', help='Print the application version')
    mode.add_argument('--mcp', action='store_true', help='Run the MCP stdio server (use ArrowMCP.exe when installed)')
    mode.add_argument('--smoke-test', metavar='REPORT', type=Path, help='Validate packaged dependencies and write a JSON report')
    args = parser.parse_args(argv)
    if args.version:
        if sys.stdout is not None:
            print(f'Arrow Annotate {app_version()}')
        return 0
    if args.smoke_test:
        from arrow.packaging_smoke import write_report
        return write_report(args.smoke_test)
    if args.mcp or Path(sys.executable).stem.lower() == 'arrowmcp':
        if sys.stdout is None or sys.stdin is None:
            _show_message('Use ArrowMCP.exe for agent integration. The desktop executable has no console streams.')
            return 2
        from arrow.mcp.server import main
        main()
        return 0
    if platform.system() != 'Windows':
        print(f'Arrow Annotate desktop requires Windows (detected {platform.system()}). '
              'Use --mcp for the cross-platform agent server.')
        return 1

    lock = None
    log_path = application_home() / 'logs' / 'ArrowAnnotate.log'
    try:
        log_path = _desktop_logging()
        from PyQt6.QtCore import QLockFile
        lock = QLockFile(str(application_home() / 'desktop.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            _show_message('Arrow Annotate is already running. Open it from the system tray.')
            return 0
        from arrow.app import main
        main()
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code:
            logging.getLogger(__name__).exception('Arrow Annotate stopped with exit code %s', code)
            _show_message(f'Arrow Annotate could not start. Details were saved to:\n{log_path}')
        return code
    except Exception:
        logging.getLogger(__name__).exception('Arrow Annotate could not start')
        _show_message(f'Arrow Annotate could not start. Details were saved to:\n{log_path}')
        return 1
    finally:
        if lock is not None and lock.isLocked():
            lock.unlock()
