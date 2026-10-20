"""Exercise the installed runtime without recording audio or controlling the desktop."""
from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

from arrow.core.paths import data_dir, resource_dir
from arrow.launcher import app_version


def _run_checks() -> dict:
    checks = {}
    context = {}

    def check(name, callback):
        try:
            detail = callback()
            checks[name] = {'ok': True, 'detail': detail}
        except Exception as exc:
            checks[name] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

    def resources():
        root = resource_dir()
        for relative in ('browser_extension/manifest.json', 'browser_extension/content.js',
                         'browser_extension/background.js', 'browser_extension/popup.html',
                         'browser_extension/popup.js', 'arrow/ui/assets/arrow.png'):
            if not (root / relative).is_file():
                raise RuntimeError(f'Missing bundled resource: {relative}')
        return str(root)

    def qt():
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtGui import QImage, QPixmap
        from PyQt6.QtWidgets import QApplication
        context['app'] = QApplication.instance() or QApplication([])
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(0xFF60A5FA)
        if QPixmap.fromImage(image).isNull():
            raise RuntimeError('Qt image plugin could not create a pixmap')
        return 'Qt platform plugin and image rendering loaded'

    def storage():
        from arrow.storage.database import get_db_connection, init_db
        init_db()
        with get_db_connection() as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'sessions', 'assets', 'contexts'} <= names:
            raise RuntimeError('Database migrations are incomplete')
        return str(data_dir())

    def capture():
        from PIL import Image, ImageChops

        from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
        from arrow.capture.screenshot_service import ScreenshotService
        from arrow.capture.session import Annotation
        raw = Image.new('RGB', (128, 128), 'white')
        mapper = CoordinateMapper([ScreenInfo('smoke', (0, 0, 128, 128), 1)])
        annotation = Annotation(id='smoke', type='freehand', role='source',
                                geometry={'x': 20, 'y': 20, 'width': 70, 'height': 70,
                                          'points': [{'x': 20, 'y': 20}, {'x': 90, 'y': 90}]})
        image = ScreenshotService().render_annotations(raw, [annotation], mapper)
        if ImageChops.difference(raw, image.convert('RGB')).getbbox() is None:
            raise RuntimeError('Annotated screenshot contains no visible stroke')
        with tempfile.TemporaryDirectory(dir=data_dir(), prefix='smoke-') as directory:
            image.save(Path(directory) / 'annotated.png')
            with Image.open(Path(directory) / 'annotated.png') as saved:
                saved.load()
                if saved.size != raw.size:
                    raise RuntimeError('PNG round trip failed')
        return 'Annotation rendering and PNG saving work'

    def ocr():
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        engine(np.zeros((64, 64, 3), dtype=np.uint8))
        return 'Offline ONNX models loaded and executed'

    def application():
        if 'app' not in context:
            raise RuntimeError('Qt application is unavailable')
        from arrow.ui.notch import DynamicNotch
        from arrow.ui.overlay import SelectionOverlay
        from arrow.ui.voice_input import VoiceInput
        notch = DynamicNotch()
        overlay = SelectionOverlay()
        voice = VoiceInput()
        voice.stop_listening()
        overlay.close()
        notch.close()
        return 'Notch, overlay, and voice classes construct without opening a microphone'

    def native():
        for name in ('keyboard', 'speech_recognition', 'mss', 'flask', 'websockets', 'requests', 'pydantic'):
            importlib.import_module(name)
        if platform.system() == 'Windows':
            import pyaudio
            import uiautomation  # noqa: F401 - imports load the packaged native UIA library
            return pyaudio.get_portaudio_version_text()
        return 'Cross-platform dependencies loaded; Windows native DLL checks require Windows'

    for name, callback in [('resources', resources), ('qt', qt), ('storage', storage),
                           ('capture', capture), ('ocr', ocr), ('application', application), ('native', native)]:
        check(name, callback)
    return {'success': all(result['ok'] for result in checks.values()), 'checks': checks,
            'version': app_version(), 'frozen': bool(getattr(sys, 'frozen', False)), 'platform': platform.system()}


def write_report(path: str | Path) -> int:
    """Use a disposable home unless the build runner supplied its own sandbox."""
    report_path = Path(path).resolve()
    previous_home = os.environ.get('ARROW_HOME')
    with tempfile.TemporaryDirectory(prefix='arrow-smoke-') as temporary:
        if not previous_home:
            os.environ['ARROW_HOME'] = temporary
        try:
            report = _run_checks()
        finally:
            if previous_home is None:
                os.environ.pop('ARROW_HOME', None)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
