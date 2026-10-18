from types import SimpleNamespace

from PyQt6.QtCore import QObject, pyqtSignal

from arrow.capture.coordinator import CaptureCoordinator
from arrow.capture.session import CaptureState, SessionManager


class Voice(QObject):
    finished = pyqtSignal(str, str, str)

    def __init__(self):
        super().__init__()
        self.started = []
        self.released = 0
        self.cancelled = 0

    def start_listening(self, capture_id):
        self.started.append(capture_id)

    def finish_listening(self):
        self.released += 1

    def stop_listening(self):
        self.cancelled += 1


class Overlay(QObject):
    selection_complete = pyqtSignal(object)
    finish_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def show_overlay(self):
        pass

    def hide_overlay(self):
        self.selection_complete.emit({'annotations': [{'geometry': {'points': [1, 2]}}]})

    def hide(self):
        pass


def setup_capture():
    manager, voice, overlay = SessionManager(), Voice(), Overlay()
    events = []
    notch = SimpleNamespace(set_recording=lambda value: events.append(('recording', value)),
                            set_status=lambda value: events.append(('status', value)))
    coordinator = CaptureCoordinator(manager, overlay, voice, notch,
                                     snapshot=lambda selection: events.append(('snapshot', selection)) or selection,
                                     on_ready=lambda *args: events.append(('ready', args)))
    return coordinator, manager, voice, overlay, events


def test_release_snapshots_immediately_but_waits_for_complete_transcript():
    coordinator, manager, voice, _, events = setup_capture()
    coordinator.start()
    capture_id = manager.active_session.capture_id
    coordinator.start()  # auto-repeat cannot replace the session
    coordinator.finish()
    coordinator.finish()
    assert voice.started == [capture_id]
    assert voice.released == 1
    assert voice.cancelled == 0
    assert manager.active_session.state == CaptureState.COLLECTING_CONTEXT
    assert any(event[0] == 'snapshot' for event in events)
    assert not any(event[0] == 'ready' for event in events)
    voice.finished.emit('complete instruction after a pause', '', capture_id)
    ready = [event[1] for event in events if event[0] == 'ready']
    assert len(ready) == 1
    assert ready[0][1]['annotations'][0]['geometry']['points'] == [1, 2]
    assert ready[0][2] == 'complete instruction after a pause'


def test_microphone_error_does_not_end_drawing_before_release():
    coordinator, manager, voice, _, events = setup_capture()
    coordinator.start()
    voice.finished.emit('', 'No microphone found', manager.active_session.capture_id)
    assert manager.active_session.state == CaptureState.ANNOTATING
    assert not any(event[0] == 'snapshot' for event in events)
    coordinator.finish()
    assert len([event for event in events if event[0] == 'ready']) == 1


def test_cancel_ignores_stale_transcription_and_releases_recording():
    coordinator, manager, voice, overlay, events = setup_capture()
    coordinator.start()
    old_id = manager.active_session.capture_id
    overlay.cancel_requested.emit()
    assert manager.active_session.state == CaptureState.CANCELLED
    assert voice.cancelled == 1
    coordinator.start()
    voice.finished.emit('stale', '', old_id)
    coordinator.finish()
    assert not any(event[0] == 'ready' for event in events)
    voice.finished.emit('new', '', manager.active_session.capture_id)
    assert [event[1][2] for event in events if event[0] == 'ready'] == ['new']


def test_snapshot_failure_does_not_wait_forever_for_transcription():
    coordinator, manager, voice, _, events = setup_capture()
    def fail(_):
        raise RuntimeError('display lost')
    coordinator.snapshot = fail
    coordinator.start()
    coordinator.finish()
    assert manager.active_session.state == CaptureState.FAILED
    assert voice.cancelled == 1
    assert not coordinator.busy
    assert any('display lost' in str(event) for event in events)


def test_pipeline_setup_failure_is_visible_and_allows_retry():
    coordinator, manager, voice, _, events = setup_capture()
    def fail(*_):
        raise RuntimeError('invalid annotation')
    coordinator.on_ready = fail
    coordinator.start()
    coordinator.finish()
    voice.finished.emit('instruction', '', manager.active_session.capture_id)
    assert manager.active_session.state == CaptureState.FAILED
    assert not coordinator.busy
    assert any('invalid annotation' in str(event) for event in events)
