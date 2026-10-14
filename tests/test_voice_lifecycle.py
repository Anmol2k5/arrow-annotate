import sys
import threading
from types import SimpleNamespace

from arrow.ui.voice_input import VoiceInput


def test_old_voice_worker_does_not_cancel_new_recording(monkeypatch):
    started = {name: threading.Event() for name in ('old', 'new')}
    release = {name: threading.Event() for name in ('old', 'new')}
    sequence = iter(('old', 'new'))

    class Recognizer:
        def __init__(self):
            self.name = next(sequence)

        def adjust_for_ambient_noise(self, source, duration):
            pass

        def listen(self, source, timeout, phrase_time_limit):
            started[self.name].set()
            assert release[self.name].wait(3)
            return self.name

        def recognize_google(self, audio):
            return audio

    class Microphone:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(sys.modules, 'speech_recognition', SimpleNamespace(
        Recognizer=Recognizer, Microphone=Microphone,
        UnknownValueError=ValueError, RequestError=RuntimeError))
    voice = VoiceInput()
    try:
        voice.start_listening('old')
        old_thread = voice._thread
        assert started['old'].wait(1)
        voice.stop_listening()
        voice.start_listening('new')
        assert started['new'].wait(1)
        release['old'].set()
        old_thread.join(1)
        assert voice.is_listening is True
        assert voice.current_capture_id == 'new'
    finally:
        release['old'].set()
        release['new'].set()
        voice.stop_listening()
        if voice._thread:
            voice._thread.join(1)
