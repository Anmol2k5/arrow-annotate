import json
from types import SimpleNamespace

import pytest


def _windows(monkeypatch):
    from arrow import diagnostics as d
    monkeypatch.setattr(d.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(d, '_qt_screens', lambda: [
        {'x': -1280, 'y': 0, 'width': 1280, 'height': 720, 'device_pixel_ratio': 1.5},
        {'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'device_pixel_ratio': 1.0},
    ])
    monkeypatch.setattr(d, '_mss_monitors', lambda: [
        {'left': -1920, 'top': 0, 'width': 1920, 'height': 1080},
        {'left': 0, 'top': 0, 'width': 1920, 'height': 1080},
    ])
    monkeypatch.setattr(d, '_microphone_devices', lambda: [
        {'index': 1, 'input_channels': 2, 'default_sample_rate': 48000.0, 'default': True},
    ])
    monkeypatch.setattr(d, '_model_state', lambda: {'model_ready': True, 'runtime_available': True})
    monkeypatch.setattr(d, '_runtime_state', lambda: {'settings_present': True, 'desktop_lock_present': True})
    monkeypatch.setattr(d, '_provider_status', lambda name: (
        SimpleNamespace(installed=True, authenticated=True),
        SimpleNamespace(registered=True, protocol_verified=True),
    ))
    return d


def test_non_windows_never_claims_hardware_pass(monkeypatch, tmp_path):
    from arrow import diagnostics as d
    monkeypatch.setattr(d.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(d, '_microphone_devices', lambda: pytest.fail('must not probe unsupported host'))
    path = tmp_path / 'report.json'
    assert d.write_report(path) == 2
    report = json.loads(path.read_text())
    assert report['overall'] == 'unsupported'
    assert all(check['status'] != 'passed' for check in report['checks'].values())


def test_inventory_pass_does_not_pass_real_capture_or_agent_sessions(monkeypatch):
    d = _windows(monkeypatch)
    report = d.collect_diagnostics()
    assert report['overall'] == 'needs_manual_validation'
    assert report['checks']['monitor_dimensions']['status'] == 'passed'
    assert report['checks']['microphone_devices']['status'] == 'passed'
    assert report['checks']['codex_authentication']['status'] == 'passed'
    for key in d.MANUAL_CHECKS:
        assert report['checks'][key]['status'] == 'manual_required'
    assert report['checks']['screen_inventory']['details']['screens'][0]['x'] == -1280


def test_missing_devices_and_unknown_authentication_are_never_passed(monkeypatch):
    d = _windows(monkeypatch)
    monkeypatch.setattr(d, '_microphone_devices', lambda: [])
    monkeypatch.setattr(d, '_provider_status', lambda name: (
        SimpleNamespace(installed=True, authenticated=None),
        SimpleNamespace(registered=None, protocol_verified=False),
    ))
    report = d.collect_diagnostics()
    assert report['overall'] == 'failed'
    assert report['checks']['microphone_devices']['status'] == 'failed'
    assert report['checks']['codex_authentication']['status'] == 'not_run'
    assert report['checks']['codex_mcp_registration']['status'] == 'not_run'
    assert report['checks']['codex_mcp_protocol']['status'] == 'failed'


def test_errors_device_names_and_screen_names_cannot_leak_into_report(monkeypatch):
    d = _windows(monkeypatch)
    secret = r'C:\Users\PrivatePerson\secret-token-account@example.com'

    def broken():
        raise OSError(secret)

    monkeypatch.setattr(d, '_microphone_devices', broken)
    monkeypatch.setattr(d, '_provider_status', lambda name: (_ for _ in ()).throw(RuntimeError(secret)))
    screens = [{'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'device_pixel_ratio': 1, 'name': secret}]
    report = d.collect_diagnostics(screens=screens)
    assert secret not in json.dumps(report)
    assert report['checks']['microphone_devices']['status'] == 'failed'
    assert report['checks']['codex_authentication']['status'] != 'passed'


def test_empty_or_mismatched_monitors_fail(monkeypatch):
    d = _windows(monkeypatch)
    assert d.collect_diagnostics(screens=[])['checks']['screen_inventory']['status'] == 'failed'
    report = d.collect_diagnostics(screens=[
        {'x': 0, 'y': 0, 'width': 123, 'height': 456, 'device_pixel_ratio': 1},
    ])
    assert report['checks']['monitor_dimensions']['status'] == 'failed'


def test_interactive_unavailable_stdin_keeps_manual_checks_unrun(monkeypatch):
    d = _windows(monkeypatch)
    monkeypatch.setattr(d.sys, 'stdin', None)
    report = d.collect_diagnostics(interactive=True)
    assert report['checks']['interactive_review']['status'] == 'not_run'
    assert all(report['checks'][key]['status'] == 'manual_required' for key in d.MANUAL_CHECKS)


def test_interactive_requires_explicit_confirmation_and_stores_no_notes(monkeypatch):
    d = _windows(monkeypatch)
    monkeypatch.setattr(d.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    answers = iter(['p', 'f', 'n', 'anything private', 'n', 'n', 'n', 'n'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    report = d.collect_diagnostics(interactive=True)
    keys = list(d.MANUAL_CHECKS)
    assert report['checks'][keys[0]]['status'] == 'passed'
    assert report['checks'][keys[0]]['evidence'] == 'user_confirmation'
    assert report['checks'][keys[1]]['status'] == 'failed'
    assert report['checks'][keys[2]]['status'] == 'not_run'
    assert report['checks'][keys[3]]['status'] == 'not_run'
    assert 'anything private' not in json.dumps(report)


def test_offscreen_qt_is_not_accepted_as_real_monitor_inventory(monkeypatch):
    from arrow import diagnostics as d
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    with pytest.raises(RuntimeError, match='interactive desktop'):
        d._qt_screens()
