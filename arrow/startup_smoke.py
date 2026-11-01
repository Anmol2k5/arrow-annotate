"""Opt-in real desktop lifecycle checks, run once per fresh Windows process.

Qt signals and menu actions exercise the production handlers. This does not
claim a physical click on the Windows shell's notification-area icon.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def _imported_desktop_modules() -> list[str]:
    """These modules cache database/data paths or user token state on import."""
    return [name for name in ('arrow.storage.database', 'arrow.storage.capture_store', 'arrow.server.server')
            if name in sys.modules]


def _native_visible(widget) -> bool:
    from ctypes import wintypes

    user32 = getattr(ctypes, 'WinDLL')('user32', use_last_error=True)
    for name in ('IsWindow', 'IsWindowVisible'):
        function = getattr(user32, name)
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.BOOL
    hwnd = wintypes.HWND(int(widget.winId()))
    return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd))


class DesktopLifecycleProbe:
    """Schedule checks on the application's own Qt thread and event loop."""

    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []
        self.app: Any = None
        self.notch: Any = None
        self.tray: Any = None
        self.server: Any = None
        self.voice: Any = None
        self._timers: list[Any] = []
        self._quit_requested = False
        self._quit_observed = False
        self._cleanup_checked = False

    def fail(self, detail: str) -> None:
        self.checks.append({'name': 'lifecycle_error', 'status': 'failed', 'detail': detail})

    def _check(self, name: str, condition: bool, detail: str) -> None:
        self.checks.append({'name': name, 'status': 'passed' if condition else 'failed', 'detail': detail})
        if not condition:
            raise AssertionError(detail)

    def _schedule(self, callback, delay=150) -> None:
        from PyQt6.QtCore import QTimer

        timer = QTimer(self.app)
        timer.setSingleShot(True)

        def guarded():
            try:
                callback()
            except Exception as exc:
                self.fail(f'{type(exc).__name__}: {exc}')
                self.app.quit()

        timer.timeout.connect(guarded)
        self._timers.append(timer)
        timer.start(delay)

    def observe(self, app, notch, tray, server, voice) -> None:
        self.app, self.notch, self.tray, self.server, self.voice = app, notch, tray, server, voice
        app.aboutToQuit.connect(self._on_quit)
        self._schedule(self._timeout, 15_000)
        self._schedule(self._startup)

    def _on_quit(self) -> None:
        self._quit_observed = True
        for timer in self._timers:
            timer.stop()

    def _timeout(self) -> None:
        raise TimeoutError('Desktop lifecycle exceeded its 15 second Qt deadline')

    def _startup(self) -> None:
        from PyQt6.QtGui import QGuiApplication

        self._check('native_qt_backend', QGuiApplication.platformName().lower() == 'windows',
                    'Native Windows Qt backend is required; offscreen/minimal cannot pass')
        self._visible('startup_window')
        self._check('tray_visible', self.tray is not None and self.tray.isVisible(),
                    'Production system tray exists and is visible')
        self._check('server_started', bool(self.server._running), 'Production local agent server is running')
        self._check('microphone_idle', not self.voice._listening and not getattr(self.voice, '_active', False),
                    'Voice input remains idle; no capture or transcription requested')
        self.notch.hide()
        self._schedule(self._restore_activation)

    def _visible(self, name: str) -> None:
        self._check(name, self.notch.isVisible() and _native_visible(self.notch),
                    'Qt notch and its native HWND are visible')

    def _restore_activation(self) -> None:
        from PyQt6.QtWidgets import QSystemTrayIcon

        self._check('hide_keeps_event_loop', not self.notch.isVisible(),
                    'Event loop remains active after hiding the notch')
        self.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        self._schedule(self._close_window)

    def _close_window(self) -> None:
        self._visible('tray_activation_restore')
        self.notch.close()
        self._schedule(self._restore_action)

    def _action(self, label):
        actions = [action for action in self.tray.contextMenu().actions() if action.text() == label]
        if len(actions) != 1 or not actions[0].isEnabled():
            raise AssertionError(f'Production tray action unavailable: {label}')
        return actions[0]

    def _restore_action(self) -> None:
        self._check('close_keeps_event_loop', not self.notch.isVisible(),
                    'Event loop remains active after closing the last visible window')
        self._action('Show Arrow').trigger()
        self._schedule(self._quit)

    def _quit(self) -> None:
        self._visible('tray_show_action_restore')
        self._quit_requested = True
        self._action('Quit').trigger()

    def check_cleanup(self) -> None:
        try:
            self._check('tray_quit', self._quit_requested and self._quit_observed,
                        'Production Quit QAction ended the application event loop')
            self._check('tray_hidden_after_quit', not self.tray.isVisible(), 'Tray hidden on aboutToQuit')
            thread = getattr(self.server, '_thread', None)
            bridge = getattr(self.server, 'ws_bridge', None)
            ws_thread = getattr(bridge, '_thread', None)
            stopped = not self.server._running and not (thread and thread.is_alive())
            stopped = stopped and not (ws_thread and ws_thread.is_alive())
            self._check('server_stopped', stopped, 'HTTP and WebSocket server threads stopped')
            self._check('microphone_idle_after_quit', not self.voice._listening,
                        'Voice input idle after shutdown')
            self._cleanup_checked = True
        except Exception as exc:
            self.fail(f'Cleanup: {type(exc).__name__}: {exc}')

    @property
    def passed(self) -> bool:
        return self._cleanup_checked and not any(check['status'] == 'failed' for check in self.checks)


def run_desktop_smoke(report_path: Path) -> int:
    """Write passed/failed/unsupported evidence; launch no agent or capture task."""
    from arrow import launcher

    report_path = Path(report_path).resolve()
    report: dict[str, Any] = {
        'status': 'failed', 'success': False, 'platform': platform.system(),
        'scope': 'Production startup and programmatic native Qt tray handlers; physical shell clicks untested',
        'checks': [],
    }

    def write_report() -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    if platform.system() != 'Windows':
        report['status'] = 'unsupported'
        report['checks'] = [{'name': 'windows_desktop', 'status': 'unsupported',
                             'detail': 'Run in a fresh process on an interactive Windows desktop'}]
        write_report()
        return 2

    if not os.environ.get('ARROW_HOME'):
        imported = _imported_desktop_modules()
        if imported:
            report['isolated_home'] = True
            report['checks'] = [{'name': 'fresh_process', 'status': 'failed',
                                 'detail': 'Isolated desktop smoke requires a fresh process before importing '
                                           f'desktop data modules: {", ".join(imported)}'}]
            write_report()
            return 1

    probe = DesktopLifecycleProbe()
    report['checks'] = probe.checks

    def hard_timeout() -> None:
        probe.fail('Desktop process exceeded its 25 second hard deadline')
        write_report()
        os._exit(1)

    watchdog = threading.Timer(25, hard_timeout)
    watchdog.daemon = True
    original_home = os.environ.get('ARROW_HOME')
    original_database = os.environ.get('ARROW_DB_PATH')
    original_stdout, original_stderr = sys.stdout, sys.stderr
    temporary_home = TemporaryDirectory(prefix='arrow-desktop-smoke-') if not original_home else None
    if temporary_home is not None:
        os.environ['ARROW_HOME'] = temporary_home.name
        # A caller's database override must not escape the isolated home.
        os.environ.pop('ARROW_DB_PATH', None)
    report['isolated_home'] = temporary_home is not None
    watchdog.start()
    try:
        code = launcher._run_desktop(startup_observer=probe.observe, error_handler=probe.fail)
        if probe.app is not None:
            probe.check_cleanup()
        if not probe.passed:
            probe.fail('Required desktop lifecycle checks did not complete')
        report['success'] = code == 0 and probe.passed
        report['status'] = 'passed' if report['success'] else 'failed'
        write_report()
        return 0 if report['success'] else 1
    except Exception as exc:
        probe.fail(f'{type(exc).__name__}: {exc}')
        write_report()
        return 1
    finally:
        watchdog.cancel()
        if temporary_home is not None:
            # Windows cannot remove the isolated home while desktop log files
            # or PyInstaller's replacement console streams are still open.
            logger = logging.getLogger()
            for handler in list(logger.handlers):
                if handler.name == 'arrow-desktop-file':
                    logger.removeHandler(handler)
                    handler.close()
            streams = {stream for stream, original in ((sys.stdout, original_stdout), (sys.stderr, original_stderr))
                       if stream is not None and stream is not original}
            sys.stdout, sys.stderr = original_stdout, original_stderr
            for stream in streams:
                stream.close()
            if original_home is None:
                os.environ.pop('ARROW_HOME', None)
            else:
                os.environ['ARROW_HOME'] = original_home
            if original_database is None:
                os.environ.pop('ARROW_DB_PATH', None)
            else:
                os.environ['ARROW_DB_PATH'] = original_database
            temporary_home.cleanup()
