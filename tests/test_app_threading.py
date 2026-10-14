import threading

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication


def test_worker_callbacks_run_on_qt_main_thread():
    import arrow.app as application
    app = QApplication.instance() or QApplication([])
    dispatcher = application.MainThreadDispatcher()
    loop = QEventLoop()
    called = []

    def callback():
        called.append(threading.get_ident())
        loop.quit()

    worker = threading.Thread(target=lambda: dispatcher.submit(callback))
    worker.start()
    worker.join()
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert called == [threading.get_ident()]
    assert app is QApplication.instance()


def test_dispatcher_logs_callback_errors_without_escaping(caplog):
    import arrow.app as application
    app = QApplication.instance() or QApplication([])
    dispatcher = application.MainThreadDispatcher()

    def fail():
        raise RuntimeError('capture failure')

    dispatcher._run(fail)
    assert 'capture failure' in caplog.text
    assert app is QApplication.instance()


def run_fake_application(monkeypatch, tmp_path, fail_screenshot=True, replace_session=False):
    from types import SimpleNamespace

    import arrow.app as application
    from arrow.capture.session import SessionManager

    class Signal:
        def __init__(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

        def emit(self, *args):
            if self.callback:
                self.callback(*args)

    notch = SimpleNamespace(show=lambda: None, set_recording=lambda *a: None,
                            set_status=lambda *a: None, refresh_screenshots=lambda: None,
                            auto_expand_briefly=lambda: None)
    overlay = SimpleNamespace(selection_complete=Signal(), show_overlay=lambda: None)
    overlay.hide_overlay = lambda: overlay.selection_complete.emit(SimpleNamespace(
        to_dict=lambda: {'x': 0, 'y': 0, 'width': 1, 'height': 1}))
    voice = SimpleNamespace(result_ready=Signal(), error=Signal(), start_listening=lambda *a: None,
                            stop_listening=lambda: None)
    manager = SessionManager()

    class FakeApp:
        aboutToQuit = Signal()

        def setApplicationName(self, *args):
            pass

        def exec(self):
            notch.on_highlight_requested()
            notch.on_highlight_requested()
            return 0

    class Timer:
        def __init__(self):
            self.timeout = Signal()

        def start(self, *args):
            pass

        @staticmethod
        def singleShot(delay, callback):
            callback()

    def fail_capture(*args):
        if replace_session:
            manager.start_session()
        raise RuntimeError('display lost')

    monkeypatch.setattr(application, 'QApplication', lambda *a: FakeApp())
    monkeypatch.setattr(application, 'QTimer', Timer)
    monkeypatch.setattr(application, 'AgentServer', lambda **k: SimpleNamespace(
        start=lambda: None, stop=lambda: None, ws_bridge=None, base_url='http://127.0.0.1:1'))
    monkeypatch.setattr(application, 'DynamicNotch', lambda **k: notch)
    monkeypatch.setattr(application, 'SelectionOverlay', lambda: overlay)
    monkeypatch.setattr(application, 'VoiceInput', lambda: voice)
    monkeypatch.setattr(application, 'SessionManager', lambda: manager)
    monkeypatch.setattr(application, 'CaptureStore', lambda: None)
    monkeypatch.setattr(application, 'ScreenshotService', lambda: SimpleNamespace(
        capture_raw=fail_capture if fail_screenshot else lambda *a: (None, None, None)))
    if not fail_screenshot:
        from arrow.storage.schemas import CaptureRecord
        record = CaptureRecord(id='c', timestamp='now', screenshot_path=str(tmp_path / 'shot.png'))
        monkeypatch.setattr(application, 'ContextOrchestrator', lambda **k: SimpleNamespace(
            set_project_dir=lambda *a: None, run=lambda **k: SimpleNamespace(error=None, record=record.to_dict())))

        class InlineThread:
            def __init__(self, target, args=(), **kwargs):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

        monkeypatch.setattr(application.threading, 'Thread', InlineThread)
        from arrow.providers import agentation

        def offline():
            raise agentation.AgentationError('Agentation offline')

        monkeypatch.setattr(agentation, 'AgentationClient', lambda: SimpleNamespace(
            health=offline, list_sessions=offline))
    monkeypatch.setattr(application.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(application.sys, 'exit', lambda *a: None)
    import keyboard
    monkeypatch.setattr(keyboard, 'add_hotkey', lambda *a: None)
    application.main()
    return manager


def test_capture_failure_is_recorded_in_session_instead_of_escaping(monkeypatch, tmp_path):
    from arrow.capture.session import CaptureState
    manager = run_fake_application(monkeypatch, tmp_path)
    assert manager.active_session.state == CaptureState.FAILED
    assert manager.active_session.error == 'display lost'


def test_capture_remains_ready_when_optional_agentation_is_offline(monkeypatch, tmp_path):
    from arrow.capture.session import CaptureState
    manager = run_fake_application(monkeypatch, tmp_path, fail_screenshot=False)
    assert manager.active_session.state == CaptureState.READY


def test_capture_error_is_visible_in_notch(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QLabel

    from arrow.storage import database
    from arrow.ui.notch import DynamicNotch
    monkeypatch.setattr(database, 'DB_PATH', str(tmp_path / 'ui.db'))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    try:
        notch.show()
        notch.set_status('Display unavailable')
        app.processEvents()
        assert any(label.text() == 'Display unavailable' and label.isVisible()
                   for label in notch.findChildren(QLabel))
        notch.update_status('Capture ready')
        app.processEvents()
        assert any(label.text() == 'Capture ready' and label.isVisible()
                   for label in notch.findChildren(QLabel))
    finally:
        notch.close()


def test_stale_screenshot_failure_does_not_escape_or_fail_new_session(monkeypatch, tmp_path):
    from arrow.capture.session import CaptureState
    manager = run_fake_application(monkeypatch, tmp_path, replace_session=True)
    assert manager.active_session.state == CaptureState.STARTING
    assert manager.active_session.error is None
