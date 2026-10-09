"""G9: voice capture uses generation-based cancellation; a stopped session
cannot clobber the next session.

The speech backend is replaced with a controllable fake so microphone
blocking, recognition and failure modes are deterministic.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from arrow.ui.voice_input import VoiceInput

_APP = None


def _qapp():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _wait_until(predicate, timeout=5.0):
    app = _qapp()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return predicate()


class FakeSpeechModule(types.ModuleType):
    """Deterministic stand-in for speech_recognition.

    Each ``listen()`` call blocks on its own gate (mic_gates[i]) and each
    ``recognize_google()`` blocks on recognize_gates[i], so tests control
    exactly when a session progresses through its lifecycle.
    """

    def __init__(self):
        super().__init__("speech_recognition")
        self._lock = threading.Lock()
        self.mic_gates: list[threading.Event] = []
        self.recognize_gates: list[threading.Event] = []
        self.mic_entered = threading.Event()
        self.listen_started: list[threading.Event] = []
        self.recognize_started: list[threading.Event] = []
        self.mic_open_count = 0
        self.mic_should_fail = False
        self.recognize_text = "hello world"
        self.recognize_error: type[Exception] | None = None
        self.listen_error: type[Exception] | None = None
        self._listen_calls = 0
        self._recognize_calls = 0

        outer = self

        class UnknownValueError(Exception):
            pass

        class RequestError(Exception):
            pass

        class WaitTimeoutError(Exception):
            pass

        class Microphone:
            def __init__(self):
                with outer._lock:
                    idx = outer.mic_open_count
                    outer.mic_open_count += 1
                if outer.mic_should_fail:
                    raise OSError("No microphone found")
                self._idx = idx

            def __enter__(self):
                with outer._lock:
                    while len(outer.listen_started) <= self._idx:
                        outer.listen_started.append(threading.Event())
                    ev = outer.listen_started[self._idx]
                ev.set()
                outer.mic_entered.set()
                return self

            def __exit__(self, *exc):
                return False

        class Recognizer:
            def adjust_for_ambient_noise(self, source, duration=None):
                pass

            def listen(self, source, timeout=None, phrase_time_limit=None):
                with outer._lock:
                    idx = outer._listen_calls
                    outer._listen_calls += 1
                    while len(outer.mic_gates) <= idx:
                        outer.mic_gates.append(threading.Event())
                    gate = outer.mic_gates[idx]
                gate.wait(timeout=5.0)
                if outer.listen_error is not None:
                    raise outer.listen_error("no speech")
                return f"AUDIO-{idx}"

            def recognize_google(self, audio):
                with outer._lock:
                    idx = outer._recognize_calls
                    outer._recognize_calls += 1
                    while len(outer.recognize_gates) <= idx:
                        outer.recognize_gates.append(threading.Event())
                    gate = outer.recognize_gates[idx]
                    while len(outer.recognize_started) <= idx:
                        outer.recognize_started.append(threading.Event())
                    started = outer.recognize_started[idx]
                started.set()
                gate.wait(timeout=5.0)
                if outer.recognize_error is not None:
                    raise outer.recognize_error("boom")
                return outer.recognize_text

        self.UnknownValueError = UnknownValueError
        self.RequestError = RequestError
        self.WaitTimeoutError = WaitTimeoutError
        self.Microphone = Microphone
        self.Recognizer = Recognizer

    # -- helpers ---------------------------------------------------------
    def release_listen(self, idx: int) -> None:
        with self._lock:
            while len(self.mic_gates) <= idx:
                self.mic_gates.append(threading.Event())
            gate = self.mic_gates[idx]
        gate.set()

    def release_recognize(self, idx: int) -> None:
        with self._lock:
            while len(self.recognize_gates) <= idx:
                self.recognize_gates.append(threading.Event())
            gate = self.recognize_gates[idx]
        gate.set()

    def wait_for_listen_call(self, idx: int, timeout=5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                started = [e.is_set() for e in self.listen_started]
            if len(started) > idx and started[idx]:
                return True
            time.sleep(0.005)
        return False


@pytest.fixture()
def fake_sr(monkeypatch):
    fake = FakeSpeechModule()
    monkeypatch.setitem(sys.modules, "speech_recognition", fake)
    yield fake


def _make_voice():
    _qapp()
    voice = VoiceInput()
    events = {"results": [], "errors": [], "listening": []}
    voice.result_ready.connect(lambda text, cid: events["results"].append((text, cid)))
    voice.error.connect(lambda msg, cid: events["errors"].append((msg, cid)))
    voice.listening_changed.connect(lambda on: events["listening"].append(on))
    return voice, events


# ---------------------------------------------------------------------------
# The audit's core race: finally clobbering a newer session
# ---------------------------------------------------------------------------


def test_stale_session_finally_cannot_clobber_new_session(fake_sr):
    voice, events = _make_voice()

    # Session 1: reaches the microphone, then captures audio (recognize phase).
    voice.start_listening("cap1")
    assert fake_sr.wait_for_listen_call(0)
    fake_sr.release_listen(0)
    # Wait until session 1 is past the microphone (recognize phase).
    assert _wait_until(lambda: voice.phase == "recognize")

    # Stop, then start session 2 — this spawns a fresh thread (session 1 is
    # already past the mic so it cannot be reassigned).
    voice.stop_listening()
    voice.start_listening("cap2")
    assert voice.is_listening is True
    assert fake_sr.wait_for_listen_call(1)

    # Let session 1 finish now (it must NOT clobber session 2's state).
    fake_sr.release_recognize(0)
    assert _wait_until(lambda: voice.phase == "mic")
    time.sleep(0.1)
    _qapp().processEvents()

    assert voice.is_listening is True, "stale session clobbered the new session"
    assert voice.generation >= 2

    # Session 2 completes normally and delivers under its own capture id.
    fake_sr.release_listen(1)
    fake_sr.release_recognize(1)
    assert _wait_until(lambda: events["results"])
    assert events["results"][-1] == ("hello world", "cap2")

    # Session 1's result (if any) must never appear for cap1.
    assert all(cid != "cap1" for _, cid in events["results"])
    assert all(cid != "cap1" for _, cid in events["errors"])


def test_stop_invalidates_in_flight_result(fake_sr):
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert fake_sr.wait_for_listen_call(0)
    fake_sr.release_listen(0)
    assert _wait_until(lambda: voice.phase == "recognize")

    voice.stop_listening()  # invalidate before recognition finishes
    fake_sr.release_recognize(0)

    time.sleep(0.1)
    _qapp().processEvents()
    assert events["results"] == [], "result delivered for a stopped session"
    assert events["errors"] == []
    assert voice.is_listening is False


def test_reassign_mic_session_to_new_capture_without_second_mic(fake_sr):
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert fake_sr.wait_for_listen_call(0)

    # Retarget while the microphone is held: no second Microphone() is opened
    # (two simultaneous mic handles fail on Windows).
    voice.start_listening("cap2")
    assert voice.is_listening is True

    fake_sr.release_listen(0)
    fake_sr.release_recognize(0)
    assert _wait_until(lambda: events["results"])
    assert events["results"][-1] == ("hello world", "cap2")
    assert fake_sr.mic_open_count == 1, "retarget must reuse the live mic session"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_no_microphone_reports_error(fake_sr):
    fake_sr.mic_should_fail = True
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert _wait_until(lambda: events["errors"])
    assert events["errors"][0][0] == "No microphone found"
    assert events["errors"][0][1] == "cap1"
    assert voice.is_listening is False


def test_unknown_value_error_reports_and_stops(fake_sr):
    fake_sr.recognize_error = fake_sr.UnknownValueError
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert fake_sr.wait_for_listen_call(0)
    fake_sr.release_listen(0)
    assert _wait_until(lambda: voice.phase == "recognize")
    fake_sr.release_recognize(0)

    assert _wait_until(lambda: events["errors"])
    assert events["errors"][0][0] == "Could not understand audio"
    assert events["errors"][0][1] == "cap1"
    assert voice.is_listening is False
    assert events["results"] == []


def test_wait_timeout_is_benign_and_does_not_cancel(fake_sr):
    """No speech within listen()'s timeout must stop the voice session
    quietly — no error signal (the app cancels the capture on voice errors),
    no result, clean state for the next session."""
    fake_sr.listen_error = fake_sr.WaitTimeoutError
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert fake_sr.wait_for_listen_call(0)
    fake_sr.release_listen(0)

    assert _wait_until(lambda: voice.is_listening is False)
    _qapp().processEvents()
    assert events["errors"] == [], "WaitTimeoutError must not surface as a voice error"
    assert events["results"] == []
    assert events["listening"] == [True, False]

    # The next session still works. (Its recognize call is index 0 — the
    # timed-out first session never reached recognition.)
    fake_sr.listen_error = None
    voice.start_listening("cap2")
    assert voice.is_listening is True
    assert fake_sr.wait_for_listen_call(1)
    fake_sr.release_listen(1)
    fake_sr.release_recognize(0)
    assert _wait_until(lambda: events["results"])
    assert events["results"][-1] == ("hello world", "cap2")


def test_import_error_reports_install_hint(monkeypatch):
    voice, events = _make_voice()
    monkeypatch.setitem(sys.modules, "speech_recognition", None)  # ImportError

    voice.start_listening("cap1")
    assert _wait_until(lambda: events["errors"])
    assert "pip install SpeechRecognition" in events["errors"][0][0]
    assert voice.is_listening is False


# ---------------------------------------------------------------------------
# Listening state bookkeeping
# ---------------------------------------------------------------------------


def test_listening_changed_emits_true_then_false(fake_sr):
    voice, events = _make_voice()

    voice.start_listening("cap1")
    assert voice.is_listening is True
    assert events["listening"] == [True]

    assert fake_sr.wait_for_listen_call(0)
    fake_sr.release_listen(0)
    fake_sr.release_recognize(0)
    assert _wait_until(lambda: events["listening"] == [True, False])
    assert voice.is_listening is False


def test_stop_without_start_is_noop_for_signals(fake_sr):
    voice, events = _make_voice()
    voice.stop_listening()
    assert events["listening"] == []
    assert voice.is_listening is False


def test_generation_advances_on_start_and_stop(fake_sr):
    voice, _ = _make_voice()
    assert voice.generation == 0
    voice.start_listening("cap1")
    g1 = voice.generation
    voice.stop_listening()
    assert voice.generation > g1
    voice.start_listening("cap2")
    assert voice.generation >= g1
