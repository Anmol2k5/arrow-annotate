import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_validates_real_models_qt_storage_and_resources(tmp_path):
    report = tmp_path / 'report.json'
    result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--smoke-test', str(report)],
                            env={**os.environ, 'ARROW_HOME': str(tmp_path / 'data'), 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data['success'] is True
    assert {'qt', 'ocr', 'storage', 'resources', 'capture', 'application'} <= data['checks'].keys()
    assert all(data['checks'][key]['ok'] for key in ['qt', 'ocr', 'storage', 'resources', 'capture', 'application'])
    assert not data['frozen']


def test_smoke_reports_missing_bundle_resources_as_failure(tmp_path):
    report = tmp_path / 'failed-report.json'
    script = '''
import sys
sys._MEIPASS = sys.argv[1]
from arrow.packaging_smoke import write_report
raise SystemExit(write_report(sys.argv[2]))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'missing-bundle'), str(report)],
                            env={**os.environ, 'ARROW_HOME': str(tmp_path / 'data'), 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 1, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data['success'] is False
    assert data['checks']['resources']['ok'] is False
    assert 'browser_extension' in data['checks']['resources']['error']
