import queue
import sys
import threading
import time
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

    def transcribe(audio, language):
        if recognize:
            return recognize(audio, language)
        return audio.frame_data.decode('ascii')
    monkeypatch.setattr('arrow.ui.voice_input.transcribe_local', transcribe)
    monkeypatch.setitem(sys.modules, 'speech_recognition', SimpleNamespace(
        Microphone=lambda: next(devices), AudioData=AudioData))


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
    phases = []
    voice.phase_changed.connect(lambda *args: phases.append(args))
    completed, _, _, _ = collect(voice)
    voice.start_listening('capture')
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(b'text')
    assert transcribing.wait(1)
    try:
        assert not voice.is_listening
        assert completed == []
        qt_app.processEvents()
        assert phases == [('opening', 'capture'), ('recording', 'capture'), ('transcribing', 'capture')]
        voice.finish_listening()
    finally:
        release.set()
        join(voice, qt_app)
    assert completed == [('dictated text', '', 'capture')]
    assert phases[-1] == ('idle', 'capture')


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
    phases = []
    voice.phase_changed.connect(lambda *args: phases.append(args))
    completed, results, _, states = collect(voice)
    voice.start_listening('old')
    old_thread = voice._thread
    assert old.reading.wait(1)
    voice.finish_listening()
    old.frames.put(b'old')
    assert transcribing.wait(1)
    qt_app.processEvents()
    voice.stop_listening()
    voice.start_listening('new')
    assert new.reading.wait(1)
    release.set()
    old_thread.join(1)
    assert voice.is_listening
    qt_app.processEvents()
    assert phases[-1] == ('recording', 'new')
    voice.finish_listening()
    new.frames.put(b'new')
    join(voice, qt_app)
    assert completed == [('new', '', 'new')]
    assert results == [('new', 'new')]
    assert states == [True, False, True, False]
    assert phases == [('opening', 'old'), ('recording', 'old'), ('transcribing', 'old'), ('idle', 'old'),
                      ('opening', 'new'), ('recording', 'new'), ('transcribing', 'new'), ('idle', 'new')]


@pytest.mark.parametrize('failure, expected', [
    (OSError('device'), 'unavailable'),
    (ImportError('pyaudio'), 'runtime'),
    (AttributeError('Could not find PyAudio; check installation'), 'runtime'),
    (PermissionError('access denied'), 'permission'),
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
    assert len(completed) == 1
    assert completed[0][0] == ''
    assert expected in completed[0][1]
    assert completed[0][2] == 'capture'
    assert results == []
    assert errors == [(completed[0][1], 'capture')]
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


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))


@pytest.mark.parametrize('explicit_default', [False, True])
def test_selection_and_language_snapshot_at_start(monkeypatch, qt_app, explicit_default):
    from arrow.storage import settings

    source = Source()
    languages = []
    install_speech(monkeypatch, [source], lambda audio, language: languages.append(language) or 'text')
    selected = {'name': 'USB Mic', 'host_api': 'MME'}
    opened = []
    resolved = []

    def resolve(selection):
        resolved.append(selection)
        return None if selection is None else 4

    def open_microphone(**kwargs):
        opened.append(kwargs)
        return source

    monkeypatch.setattr('arrow.ui.voice_input.resolve_input_device', resolve)
    monkeypatch.setattr(sys.modules['speech_recognition'], 'Microphone', open_microphone)
    voice = VoiceInput(language='hi-IN', **({'microphone_selection': None} if explicit_default else {}))
    settings.set_microphone_selection(selected)
    voice.start_listening('capture')
    voice.language = 'en-US'
    settings.set_microphone_selection(None)
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(b'text')
    join(voice, qt_app)
    assert resolved == [None if explicit_default else selected]
    assert opened == [{} if explicit_default else {'device_index': 4}]
    assert languages == ['hi-IN']


def test_digital_silence_has_helpful_error_without_inference(monkeypatch, qt_app):
    source = Source()
    source.SAMPLE_WIDTH = 2
    recognized = []
    install_speech(monkeypatch, [source], lambda audio, lang: recognized.append(audio) or 'invented words')
    voice = VoiceInput()
    completed, results, _, _ = collect(voice)
    voice.start_listening('silent')
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(b'\x00' * 8)
    join(voice, qt_app)
    assert not recognized
    assert not results
    assert len(completed) == 1
    assert 'signal' in completed[0][1]


@pytest.mark.parametrize('frame', [b'\x01\x00' * 4, b'\xff\x7f' * 4])
def test_real_pcm_levels_and_quiet_nonzero_audio_reaches_recognizer(monkeypatch, qt_app, frame):
    source = Source()
    source.SAMPLE_WIDTH = 2
    install_speech(monkeypatch, [source], lambda audio, lang: 'spoken words')
    voice = VoiceInput()
    levels = []
    voice.audio_level.connect(lambda *args: levels.append(args))
    completed, _, _, _ = collect(voice)
    voice.start_listening('capture')
    assert source.reading.wait(1)
    source.frames.put(frame)
    source.frames.join()
    assert source.reading.wait(1)
    voice.finish_listening()
    source.frames.put(frame)
    join(voice, qt_app)
    assert completed == [('spoken words', '', 'capture')]
    assert levels
    assert all(0 < value <= 1 and capture_id == 'capture' for value, capture_id in levels)
    if frame == b'\x01\x00' * 4:
        assert levels[0][0] == pytest.approx(1 / 32768)
    else:
        assert levels[0][0] > 0.99


def test_audio_levels_are_throttled_and_cancelled_reads_cannot_publish(monkeypatch, qt_app):
    source = Source()
    source.SAMPLE_WIDTH = 2
    install_speech(monkeypatch, [source], lambda audio, lang: 'text')
    voice = VoiceInput()
    levels = []
    voice.audio_level.connect(lambda *args: levels.append(args))
    voice.start_listening('capture')
    assert source.reading.wait(1)
    started = time.monotonic()
    for _ in range(30):
        source.frames.put(b'\x00\x40' * 4)
    source.frames.join()
    elapsed = time.monotonic() - started
    qt_app.processEvents()
    assert 1 <= len(levels) <= int(elapsed / 0.1) + 1
    before_cancel = list(levels)
    voice.stop_listening()
    source.frames.put(b'\xff\x7f' * 4)
    join(voice, qt_app)
    assert levels == before_cancel


def test_different_voice_instances_share_device_and_cancel_wait_promptly(monkeypatch, qt_app):
    old, waiting = Source(), Source()
    install_speech(monkeypatch, [old, waiting])
    first, second = VoiceInput(), VoiceInput()
    second_events = []
    second.finished.connect(lambda *args: second_events.append(args))
    first.start_listening('old')
    assert old.reading.wait(1)
    second.start_listening('waiting')
    try:
        assert not waiting.reading.wait(0.1)
        second.stop_listening()
        second._thread.join(0.5)
        assert not second._thread.is_alive()
        assert not waiting.closed.is_set()
    finally:
        first.finish_listening()
        old.frames.put(b'old')
        join(first, qt_app)
    assert second_events == []


def test_device_wait_is_bounded_and_reports_busy(monkeypatch, qt_app):
    import arrow.ui.voice_input as module

    install_speech(monkeypatch, [])
    monkeypatch.setattr(module, '_DEVICE_WAIT_SECONDS', 0.1)
    with module._MICROPHONE_LOCK:
        voice = VoiceInput()
        completed, _, _, _ = collect(voice)
        voice.start_listening('waiting')
        join(voice, qt_app)
    assert len(completed) == 1
    assert 'busy' in completed[0][1]


def test_stream_failure_reports_interruption_without_transcribing_partial_audio(monkeypatch, qt_app):
    source = Source()
    recognized = []
    install_speech(monkeypatch, [source], lambda audio, lang: recognized.append(audio) or 'text')

    def read(chunk):
        raise OSError('input overflow')

    source.read = read
    voice = VoiceInput()
    completed, results, _, _ = collect(voice)
    voice.start_listening('capture')
    join(voice, qt_app)
    assert not recognized
    assert not results
    assert 'stream' in completed[0][1]
    assert source.closed.is_set()


@pytest.mark.parametrize('failure, expected', [
    (PermissionError('desktop microphone access denied'), 'permission'),
    (OSError('device disconnected'), 'unavailable'),
])
def test_real_speech_recognition_stream_open_keeps_original_error(monkeypatch, qt_app, failure, expected):
    import speech_recognition as sr

    terminated = []

    class PortAudio:
        def get_device_count(self):
            return 1

        def get_default_input_device_info(self):
            return {'defaultSampleRate': 16000}

        def open(self, **kwargs):
            raise failure

        def terminate(self):
            terminated.append(True)

    monkeypatch.setattr(sr.Microphone, 'get_pyaudio', staticmethod(lambda: SimpleNamespace(
        PyAudio=PortAudio, paInt16=8, get_sample_size=lambda format: 2)))
    voice = VoiceInput(microphone_selection=None)
    completed, results, _, states = collect(voice)
    voice.start_listening('capture')
    join(voice, qt_app)
    assert expected in completed[0][1]
    assert results == []
    assert states == []
    assert terminated == [True, True]


def test_real_speech_recognition_stream_closes_before_local_decode(monkeypatch, qt_app):
    import speech_recognition as sr

    reading, release, closed = threading.Event(), threading.Event(), threading.Event()
    terminated = []

    class NativeStream:
        def read(self, size, *, exception_on_overflow):
            assert exception_on_overflow is False
            reading.set()
            assert release.wait(2)
            return b'\x01\x00' * 4

        def is_stopped(self):
            return False

        def stop_stream(self):
            pass

        def close(self):
            closed.set()

    class PortAudio:
        def get_device_count(self):
            return 1

        def get_default_input_device_info(self):
            return {'defaultSampleRate': 16000}

        def open(self, **kwargs):
            assert not voice.is_listening
            assert kwargs == dict(input_device_index=None, channels=1, format=8,
                                  rate=16000, frames_per_buffer=1024, input=True)
            return NativeStream()

        def terminate(self):
            terminated.append(True)

    def decode(audio, language):
        assert closed.is_set()
        assert terminated == [True, True]
        assert audio.frame_data == b'\x01\x00' * 4
        return 'spoken words'

    monkeypatch.setattr(sr.Microphone, 'get_pyaudio', staticmethod(lambda: SimpleNamespace(
        PyAudio=PortAudio, paInt16=8, get_sample_size=lambda format: 2)))
    monkeypatch.setattr('arrow.ui.voice_input.transcribe_local', decode)
    voice = VoiceInput(microphone_selection=None)
    completed, _, _, states = collect(voice)
    voice.start_listening('capture')
    assert reading.wait(1)
    voice.finish_listening()
    release.set()
    join(voice, qt_app)
    assert completed == [('spoken words', '', 'capture')]
    assert states == [True, False]


def test_microphone_test_recording_limit_finishes_without_gui_timer(monkeypatch, qt_app):
    import time
    class Continuous(Source):
        SAMPLE_WIDTH = 2
        SAMPLE_RATE = 16000
        def read(self, chunk):
            time.sleep(.002)  # Simulated device I/O, not an assertion timing delay.
            return b'\x01\x00' * chunk
    source = Continuous()
    install_speech(monkeypatch, [source], recognize=lambda audio, language: 'test words')
    voice = VoiceInput(max_recording_seconds=.02)
    completed, _, errors, _ = collect(voice)
    voice.start_listening('limited')
    join(voice, qt_app)
    assert completed == [('test words', '', 'limited')]
    assert not errors and source.closed.is_set()


@pytest.mark.parametrize('reordered', [False, True])
def test_unplug_during_setup_cannot_open_a_different_microphone(monkeypatch, qt_app, reordered):
    import speech_recognition as sr
    opened, terminated = [], []
    current = ['Default', 'Private input', 'Selected USB'] if reordered else ['Default', 'Private input']
    snapshots = iter([
        ['Default', 'Selected USB', 'Private input'],
        current,
        current,
    ])
    class PortAudio:
        def __init__(self):
            self.names = next(snapshots)
        def get_device_count(self):
            return len(self.names)
        def get_device_info_by_index(self, index):
            return {'name': self.names[index], 'hostApi': 0, 'maxInputChannels': 1,
                    'defaultSampleRate': 44100 if self.names[index] == 'Selected USB' else 16000}
        def get_host_api_info_by_index(self, index):
            return {'name': 'WASAPI'}
        def open(self, **kwargs):
            opened.append(self.names[kwargs['input_device_index']])
            if reordered:
                assert kwargs['rate'] == 44100
            raise OSError('wrong input was opened')
        def terminate(self):
            terminated.append(True)
    module = SimpleNamespace(PyAudio=PortAudio, paInt16=8, get_sample_size=lambda format: 2)
    monkeypatch.setitem(sys.modules, 'pyaudio', module)
    monkeypatch.setattr(sr.Microphone, 'get_pyaudio', staticmethod(lambda: module))
    voice = VoiceInput(microphone_selection={'name': 'Selected USB', 'host_api': 'WASAPI'})
    completed, _, _, _ = collect(voice)
    voice.start_listening('hotplug')
    join(voice, qt_app)
    assert opened == (['Selected USB'] if reordered else []), 'Never open a different input after hotplug'
    if not reordered:
        assert 'Selected microphone is unavailable' in completed[0][1]
    assert terminated == [True, True, True]


def test_native_portaudio_host_error_explains_windows_privacy_recovery(monkeypatch, qt_app):
    install_speech(monkeypatch, [])
    def denied():
        raise OSError(-9999, 'Unanticipated host error')
    monkeypatch.setattr(sys.modules['speech_recognition'], 'Microphone', denied)
    voice = VoiceInput(microphone_selection=None)
    completed, _, _, _ = collect(voice)
    voice.start_listening('host-error')
    join(voice, qt_app)
    assert 'Privacy & security' in completed[0][1] and 'desktop' in completed[0][1]
    assert 'permission was denied' not in completed[0][1]
