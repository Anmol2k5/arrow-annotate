import queue
import sys
import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from arrow.ui.voice_input import VoiceInput


class AudioData:
    def __init__(self, frame_data, sample_rate, sample_width):
        self.frame_data = frame_data
        self.sample_rate = sample_rate
        self.sample_width = sample_width


class Source:
    CHUNK = 4
    SAMPLE_RATE = 4
    SAMPLE_WIDTH = 1

    def __init__(self):
        self.stream = self
        self.frames = queue.Queue()
        self.reading = threading.Event()
        self.closed = threading.Event()

    def read(self, chunk):
        self.reading.set()
        frame = self.frames.get(timeout=3)
        self.reading.clear()
        self.frames.task_done()
        return frame

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed.set()


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def install_speech(monkeypatch, sources, recognize=None):
    devices = iter(sources)

    class Recognizer:
        operation_timeout = None

        def recognize_google(self, audio, language):
            assert self.operation_timeout and self.operation_timeout <= 30
            if recognize:
                return recognize(audio, language)
            return audio.frame_data.decode('ascii')

    monkeypatch.setitem(sys.modules, 'speech_recognition', SimpleNamespace(
        Recognizer=Recognizer, Microphone=lambda: next(devices), AudioData=AudioData,
        UnknownValueError=ValueError, RequestError=RuntimeError))


def collect(voice):
    completed, results, errors, states = [], [], [], []
    voice.finished.connect(lambda *args: completed.append(args))
    voice.result_ready.connect(lambda *args: results.append(args))
    voice.error.connect(lambda *args: errors.append(args))
    voice.listening_changed.connect(states.append)
    return completed, results, errors, states


def join(voice, app):
    voice._thread.join(2)
    assert not voice._thread.is_alive()
    app.processEvents()


def test_hold_keeps_all_audio_including_pauses_until_release(monkeypatch, qt_app):
    source = Source()
    languages = []

    def recognize(audio, language):
        languages.append(language)
        return audio.frame_data.decode('ascii')

    install_speech(monkeypatch, [source], recognize)
    voice = VoiceInput(language='en-IN')
    completed, results, errors, states = collect(voice)
    voice.start_listening('capture')
    assert source.reading.wait(1)
    # Forty seconds of simulated audio includes long silent pauses. Recording
    # must neither segment the phrase nor stop at the previous eight-second cap.
    frames = [b'talk', b'\x00' * 4] * 20
    for frame in frames:
        source.frames.put(frame)
    source.frames.join()
    assert source.reading.wait(1)
    assert voice.is_listening
    assert not completed
    voice.finish_listening()
    # Release during a pending read must retain the final chunk.
    source.frames.put(b'last')
    join(voice, qt_app)
    assert completed == [(b''.join(frames + [b'last']).decode('ascii'), '', 'capture')]
    assert results == [(completed[0][0], 'capture')]
    assert errors == []
    assert states == [True, False]
    assert languages == ['en-IN']
    assert not voice.is_listening


def test_finish_returns_while_transcribing_and_reports_recording_stopped(monkeypatch, qt_app):
    source = Source()
    transcribing = threading.Event()
    release = threading.Event()

    def recognize(audio, language):
        transcribing.set()
        assert release.wait(3)
        return 'dictated text'

    install_speech(monkeypatch, [source], recognize)
    voice = VoiceInput()
    completed, _, _, _ = collect(voice)
    voice.start_listening('capture')
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(b'text')
    assert transcribing.wait(1)
    try:
        assert not voice.is_listening
        assert completed == []
        voice.finish_listening()
    finally:
        release.set()
        join(voice, qt_app)
    assert completed == [('dictated text', '', 'capture')]


def test_old_voice_worker_does_not_cancel_new_recording(monkeypatch, qt_app):
    old, new = Source(), Source()
    install_speech(monkeypatch, [old, new])
    voice = VoiceInput()
    completed, results, _, _ = collect(voice)
    voice.start_listening('old')
    old_thread = voice._thread
    assert old.reading.wait(1)
    voice.stop_listening()
    voice.start_listening('new')
    # A blocked old microphone must close before the new capture opens it.
    assert not new.reading.wait(0.05)
    old.frames.put(b'stale')
    old_thread.join(1)
    assert new.reading.wait(1)
    assert old.closed.is_set()
    assert voice.is_listening
    assert voice.current_capture_id == 'new'
    voice.finish_listening()
    new.frames.put(b'fresh')
    join(voice, qt_app)
    assert completed == [('fresh', '', 'new')]
    assert results == [('fresh', 'new')]


def test_cancel_during_transcription_discards_stale_result(monkeypatch, qt_app):
    old, new = Source(), Source()
    transcribing, release = threading.Event(), threading.Event()

    def recognize(audio, language):
        if audio.frame_data == b'old':
            transcribing.set()
            assert release.wait(3)
        return audio.frame_data.decode('ascii')

    install_speech(monkeypatch, [old, new], recognize)
    voice = VoiceInput()
    completed, results, _, states = collect(voice)
    voice.start_listening('old')
    old_thread = voice._thread
    assert old.reading.wait(1)
    voice.finish_listening()
    old.frames.put(b'old')
    assert transcribing.wait(1)
    voice.stop_listening()
    voice.start_listening('new')
    assert new.reading.wait(1)
    release.set()
    old_thread.join(1)
    assert voice.is_listening
    voice.finish_listening()
    new.frames.put(b'new')
    join(voice, qt_app)
    assert completed == [('new', '', 'new')]
    assert results == [('new', 'new')]
    assert states == [True, False, True, False]


@pytest.mark.parametrize('failure, expected', [
    (OSError('device'), 'No microphone found'),
    (ImportError('pyaudio'), 'Install: pip install SpeechRecognition pyaudio'),
])
def test_microphone_failure_still_completes_capture(monkeypatch, qt_app, failure, expected):
    install_speech(monkeypatch, [])

    def microphone():
        raise failure

    monkeypatch.setattr(sys.modules['speech_recognition'], 'Microphone', microphone)
    voice = VoiceInput()
    completed, results, errors, _ = collect(voice)
    voice.start_listening('capture')
    join(voice, qt_app)
    assert completed == [('', expected, 'capture')]
    assert results == []
    assert errors == [(expected, 'capture')]
    assert not voice.is_listening


def test_empty_recording_still_completes_capture(monkeypatch, qt_app):
    source = Source()
    install_speech(monkeypatch, [source])
    voice = VoiceInput()
    completed, results, errors, _ = collect(voice)
    voice.start_listening('capture')
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(b'')
    join(voice, qt_app)
    assert len(completed) == 1
    assert completed[0][0] == ''
    assert completed[0][1]
    assert completed[0][2] == 'capture'
    assert results == []
    assert errors == [(completed[0][1], 'capture')]
