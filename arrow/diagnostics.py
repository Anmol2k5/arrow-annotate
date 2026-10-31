"""Read-only Windows inventory and explicit, human-observed desktop validation.

Device enumeration, account status and a local MCP handshake cannot prove that
speech, capture alignment or a real agent session worked. Those checks require
an interactive reviewer. No audio, captures, credentials, subprocess output,
device names, free-form notes or local paths are included in the report.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANUAL_CHECKS = {
    'microphone_live_capture': (
        'In Arrow, hold your capture shortcut, speak "Move the blue button below the heading", '
        'release, and confirm the saved instruction contains your words. Did real microphone capture work?'
    ),
    'ptt_pauses': (
        'Hold the shortcut throughout: say "Move the blue button", pause silently for 3 seconds, '
        'then say "below the heading", then release. Did capture continue through the pause and include both parts?'
    ),
    'hinglish_recognition': (
        'Select Auto Hindi/English, then capture: "Is blue button ko heading ke neeche move karo, '
        'aur spacing sixteen pixels rakho." Did the instruction preserve both the Hindi/English meaning '
        'and sixteen-pixel requirement? Devanagari or Latin Hindi is acceptable.'
    ),
    'per_monitor_alignment': (
        'On EVERY connected monitor, capture a synthetic window and mark its four corners and center. '
        'Review each saved image at full size. Were all five markers aligned on every monitor, '
        'including any screen left of or above the primary? Choose not run if only one screen is connected.'
    ),
    'mixed_dpi_alignment': (
        'Use two monitors with DIFFERENT Windows scaling (for example 100% and 150%). '
        'Move the synthetic window between them and repeat corner/center annotations. '
        'Did every saved marker remain aligned? Choose not run unless different scales were actually tested.'
    ),
    'desktop_tray_startup': (
        'Launch installed ArrowAnnotate.exe from the Start menu, capture, close/reopen using the tray, '
        'then Quit and relaunch. Did startup, tray recovery, capture and shutdown all work? '
        'This checks launching the desktop app, not automatic launch at Windows sign-in.'
    ),
    'codex_real_session': (
        'Run the synthetic Codex task in docs/windows-interactive-testing.md in a disposable project. '
        'Confirm the client ACTUALLY called arrow_get_capture_bundle and its reply identified marker 1 '
        'and the sixteen-pixel request. Did the real Codex session complete? '
        'Authentication, registration or tools/list alone do not qualify.'
    ),
    'claude_real_session': (
        'Run the synthetic Claude Code task in docs/windows-interactive-testing.md in a disposable project. '
        'Confirm the client ACTUALLY called arrow_get_capture_bundle and its reply identified marker 1 '
        'and the sixteen-pixel request. Did the real Claude session complete? '
        'Authentication, registration or tools/list alone do not qualify.'
    ),
}


def _check(status: str, message: str, **details) -> dict[str, Any]:
    result: dict[str, Any] = {'status': status, 'message': message, 'evidence': 'automated_observation'}
    if details:
        result['details'] = details
    return result


def _qt_screens() -> list[dict]:
    # Qt screen access must remain on the GUI thread. UI callers can collect
    # numeric screen data there, then inject it into a diagnostic worker.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Collect screen geometry on the main thread first')
    if os.environ.get('QT_QPA_PLATFORM', '').lower() in ('offscreen', 'minimal'):
        raise RuntimeError('Use an interactive desktop, not an offscreen Qt platform')
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    return [dict(x=s.geometry().x(), y=s.geometry().y(), width=s.geometry().width(),
                 height=s.geometry().height(), device_pixel_ratio=s.devicePixelRatio())
            for s in QApplication.screens()]


def _mss_monitors() -> list[dict]:
    import mss
    with mss.mss() as capture:
        # Entry zero is the virtual desktop union, not a physical monitor.
        return [dict(monitor) for monitor in capture.monitors[1:]]


def _microphone_devices() -> list[dict]:
    import pyaudio
    audio = pyaudio.PyAudio()
    try:
        try:
            default = int(audio.get_default_input_device_info()['index'])
        except (OSError, KeyError):
            default = None
        devices = []
        for index in range(audio.get_device_count()):
            item = audio.get_device_info_by_index(index)
            if int(item.get('maxInputChannels', 0)) > 0:
                devices.append({'index': index, 'input_channels': int(item['maxInputChannels']),
                                'default_sample_rate': float(item['defaultSampleRate']),
                                'default': index == default})
        return devices
    finally:
        audio.terminate()


def _model_state() -> dict:
    from arrow.speech.offline import voice_model_ready
    return {'model_ready': voice_model_ready(), 'runtime_available': importlib.util.find_spec('faster_whisper') is not None}


def _runtime_state() -> dict:
    from arrow.core.paths import application_home, resource_dir
    home = application_home()
    return {'settings_present': (home / 'config.json').is_file(),
            'desktop_lock_present': (home / 'desktop.lock').is_file(),
            'bundled_icon_present': (resource_dir() / 'arrow' / 'ui' / 'assets' / 'arrow.ico').is_file()}


def _provider_status(name: str):
    from arrow.providers.connection import probe_provider_mcp
    from arrow.providers.setup import get_provider_setup_status
    return get_provider_setup_status(name), probe_provider_mcp(name)


def _screen_inventory(screens: list[dict]) -> list[dict]:
    clean = []
    for item in screens:
        screen: dict[str, Any] = {key: int(item[key]) for key in ('x', 'y', 'width', 'height')}
        screen['device_pixel_ratio'] = float(item['device_pixel_ratio'])
        if (screen['width'] <= 0 or screen['height'] <= 0
                or not math.isfinite(screen['device_pixel_ratio']) or screen['device_pixel_ratio'] <= 0):
            raise ValueError('Invalid screen dimensions')
        clean.append(screen)
    return clean


def _dimension_match(screens: list[dict], monitors: list[dict]) -> bool:
    remaining = [(monitor['width'], monitor['height']) for monitor in monitors]
    if not screens or len(screens) != len(remaining):
        return False
    for screen in screens:
        width = screen['width'] * screen['device_pixel_ratio']
        height = screen['height'] * screen['device_pixel_ratio']
        candidate = next((i for i, (w, h) in enumerate(remaining)
                          if abs(w - width) <= 2 and abs(h - height) <= 2), None)
        if candidate is None:
            return False
        remaining.pop(candidate)
    return True


def _manual_review(checks: dict) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        checks['interactive_review'] = _check('not_run', 'A console with interactive stdin is required. Use ArrowMCP.exe.')
        return
    print('Run each real test before answering. p = observed pass; f = observed failure; n = not run.')
    print('Only these choices are stored. Do not enter transcripts, account information or notes.')
    for key, instruction in MANUAL_CHECKS.items():
        try:
            answer = input(f'\n{instruction}\n[p/f/n]: ').strip().lower()
        except (EOFError, OSError, KeyboardInterrupt):
            checks['interactive_review'] = _check('not_run', 'Interactive review stopped; remaining checks are unverified.')
            return
        status = {'p': 'passed', 'f': 'failed'}.get(answer, 'not_run')
        checks[key] = {'status': status, 'message': instruction, 'evidence': 'user_confirmation'}
    checks['interactive_review'] = _check('passed', 'Reviewer recorded manual outcomes; inspect each individual result.')


def collect_diagnostics(*, screens: list[dict] | None = None, interactive: bool = False) -> dict[str, Any]:
    """Collect sanitized observations; never record audio or start an agent task.

    Pass QScreen numeric dictionaries from the GUI thread when using a worker.
    Otherwise call on the main thread. Interactive mode needs a real console.
    """
    supported = platform.system() == 'Windows'
    checks: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                              'platform': 'Windows' if supported else 'unsupported',
                              'python': f'{sys.version_info.major}.{sys.version_info.minor}',
                              'frozen': bool(getattr(sys, 'frozen', False)), 'checks': checks}
    for key, instruction in MANUAL_CHECKS.items():
        checks[key] = {'status': 'manual_required', 'message': instruction, 'evidence': 'none'}
    if not supported:
        checks['windows_desktop'] = _check('not_run', 'Unsupported host. Run this harness on the target Windows desktop.')
        report['overall'] = 'unsupported'
        return report

    qt, monitors = [], []
    try:
        qt = _screen_inventory(_qt_screens() if screens is None else screens)
        checks['screen_inventory'] = _check('passed' if qt else 'failed', 'Qt logical screen geometry and scaling.', screens=qt)
    except Exception:
        checks['screen_inventory'] = _check('failed', 'Could not enumerate Qt screens. Run on the interactive main desktop thread.')
    try:
        monitors = [{key: int(item[key]) for key in ('left', 'top', 'width', 'height')} for item in _mss_monitors()]
        if any(item['width'] <= 0 or item['height'] <= 0 for item in monitors):
            raise ValueError('Invalid monitor bounds')
        checks['mss_inventory'] = _check('passed' if monitors else 'failed', 'MSS physical monitor bounds.', monitors=monitors)
    except Exception:
        checks['mss_inventory'] = _check('failed', 'Could not enumerate MSS monitor bounds.')
    checks['monitor_dimensions'] = _check(
        'passed' if _dimension_match(qt, monitors) else 'failed',
        'Compares counts and Qt size multiplied by DPR against MSS sizes (two-pixel rounding tolerance). '
        'This does not verify monitor origins, ordering, capture pixels or annotation alignment.')
    try:
        devices = [{key: item[key] for key in ('index', 'input_channels', 'default_sample_rate', 'default')}
                   for item in _microphone_devices()]
        checks['microphone_devices'] = _check('passed' if devices else 'failed',
                                             'Input device inventory only; no audio was recorded.', devices=devices)
    except Exception:
        checks['microphone_devices'] = _check('failed', 'Microphone enumeration failed. Check PyAudio, device access and Windows privacy settings.')
    try:
        state = _model_state()
        checks['offline_model'] = _check('passed' if state.get('model_ready') is True and state.get('runtime_available') is True else 'failed',
                                         'Offline weights and runtime availability only; recognition still needs a real test.',
                                         model_ready=state.get('model_ready') is True,
                                         runtime_available=state.get('runtime_available') is True)
    except Exception:
        checks['offline_model'] = _check('failed', 'Could not inspect the offline speech installation.')
    try:
        state = _runtime_state()
        checks['runtime_inventory'] = _check('passed', 'File presence only; a lock file does not prove the desktop is running.',
                                            **{key: state.get(key) is True for key in (
                                                'settings_present', 'desktop_lock_present', 'bundled_icon_present')})
    except Exception:
        checks['runtime_inventory'] = _check('failed', 'Could not inspect runtime files.')
    for provider, prefix in (('Codex', 'codex'), ('Claude Code', 'claude')):
        try:
            auth, mcp = _provider_status(provider)
            observations = {'authentication': auth.authenticated, 'mcp_registration': mcp.registered,
                            'mcp_protocol': mcp.protocol_verified}
            for suffix, value in observations.items():
                status = 'passed' if value is True else ('failed' if value is False else 'not_run')
                checks[f'{prefix}_{suffix}'] = _check(status, f'{provider} {suffix.replace("_", " ")} check only; no agent session was started.',
                                                     installed=auth.installed is True)
        except Exception:
            for suffix in ('authentication', 'mcp_registration', 'mcp_protocol'):
                checks[f'{prefix}_{suffix}'] = _check('failed', f'{provider} read-only status probe failed; no agent session was started.')
    if interactive:
        _manual_review(checks)
    states = [item['status'] for item in checks.values()]
    report['overall'] = ('failed' if 'failed' in states else
                         'needs_manual_validation' if any(state != 'passed' for state in states) else 'passed')
    return report


def write_report(path: Path, *, interactive: bool = False) -> int:
    """Write a local report. Exit zero can still mean manual validation is pending."""
    report = collect_diagnostics(interactive=interactive)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if sys.stdout is not None:
        print(f'Windows diagnostics: {report["overall"]}. Review individual check statuses in the report.')
    return {'unsupported': 2, 'failed': 1}.get(report['overall'], 0)
