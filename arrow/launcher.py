"""Console-safe entry point shared by source, desktop EXE, and MCP EXE."""
from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import logging
import platform
import sys
from collections.abc import Callable
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
    mode.add_argument('--desktop-smoke', metavar='REPORT', type=Path,
                      help='Launch the real Windows desktop, exercise tray handlers and quit; write a JSON report')
    mode.add_argument('--diagnostics', metavar='REPORT', type=Path, help='Check Windows readiness and write a report without saving screen/audio content')
    mode.add_argument('--speech-smoke', nargs=2, metavar=('WAV', 'REPORT'), type=Path,
                      help='Transcribe a synthetic WAV locally in English/auto modes; save diagnostic transcripts')
    mode.add_argument('--verify-agent', nargs=2, metavar=('CLIENT', 'REPORT'),
                      help='Use an installed Codex or Claude Code account to verify synthetic MCP image/context retrieval')
    mode.add_argument('--validation-mcp', nargs=2, type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--interactive', action='store_true', help='Confirm observed Windows checks during --diagnostics (requires console input)')
    args = parser.parse_args(argv)
    if args.interactive and not args.diagnostics:
        parser.error('--interactive requires --diagnostics REPORT')
    if args.validation_mcp:
        from arrow.mcp.validation import serve_validation
        serve_validation(*args.validation_mcp)
        return 0
    if args.verify_agent:
        name, report = args.verify_agent
        if name not in ('Codex', 'Claude Code'):
            parser.error('--verify-agent CLIENT must be Codex or "Claude Code"')
        from arrow.providers.live_check import run_live_check
        return run_live_check(name, Path(report))
    if args.speech_smoke:
        from arrow.speech.smoke import write_speech_report
        return write_speech_report(*args.speech_smoke)
    if args.desktop_smoke:
        from arrow.startup_smoke import run_desktop_smoke
        return run_desktop_smoke(args.desktop_smoke)
    if args.diagnostics:
        from arrow.diagnostics import write_report as write_diagnostics_report
        return write_diagnostics_report(args.diagnostics, interactive=args.interactive)
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

    return _run_desktop()


def _run_desktop(*, startup_observer=None, error_handler: Callable[[str], None] | None = None) -> int:
    """One production startup path; explicit smoke mode replaces modal errors."""
    show_error = error_handler if error_handler is not None else _show_message
    lock = None
    log_path = application_home() / 'logs' / 'ArrowAnnotate.log'
    try:
        log_path = _desktop_logging()
        from PyQt6.QtCore import QLockFile
        lock = QLockFile(str(application_home() / 'desktop.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            show_error('Arrow Annotate is already running. Open it from the system tray.')
            return 1 if error_handler is not None else 0
        from arrow.app import main
        if startup_observer is None:
            main()
        else:
            main(startup_observer=startup_observer)
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code:
            logging.getLogger(__name__).exception('Arrow Annotate stopped with exit code %s', code)
            show_error(f'Arrow Annotate could not start. Details were saved to:\n{log_path}')
        return code
    except Exception:
        logging.getLogger(__name__).exception('Arrow Annotate could not start')
        show_error(f'Arrow Annotate could not start. Details were saved to:\n{log_path}')
        return 1
    finally:
        if lock is not None and lock.isLocked():
            lock.unlock()
