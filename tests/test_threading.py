"""G10: background workers never touch Qt widgets directly; stale callbacks
are discarded; screenshot failure cannot wedge the session."""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from arrow.capture.session import CaptureState, SessionManager
from arrow.core.threads import UiBridge

_APP = None


def _qapp():
    # Keep a module-level reference: a QApplication that is garbage-collected
    # destroys the Qt application and hard-crashes widget construction.
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _wait_until(predicate, timeout=5.0):
    """Run the Qt event loop until predicate() is true or timeout expires."""
    app = _qapp()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return predicate()


# ---------------------------------------------------------------------------
# UiBridge: worker → main thread marshalling
# ---------------------------------------------------------------------------


def test_worker_callback_runs_on_main_thread():
    _qapp()
    bridge = UiBridge()
    result = {}

    def cb():
        result["on_main"] = QThread.currentThread() == _qapp().thread()
        result["done"] = True

    t = threading.Thread(target=lambda: bridge.post(cb))
    t.start()
    t.join()

    assert _wait_until(lambda: result.get("done")), "callback never ran"
    assert result["on_main"] is True, "worker callback ran off the main thread"


def test_stale_callbacks_are_discarded():
    _qapp()
    bridge = UiBridge()
    delivered = []

    bridge.begin_capture("A")
    assert bridge.post_for("A", lambda: delivered.append("A-first")) is True

    # Capture B supersedes A: callbacks for A are now stale.
    bridge.begin_capture("B")
    assert bridge.post_for("A", lambda: delivered.append("A-stale")) is False
    assert bridge.post_for("B", lambda: delivered.append("B-first")) is True

    assert _wait_until(lambda: len(delivered) == 2)
    time.sleep(0.05)
    _qapp().processEvents()
    assert delivered == ["A-first", "B-first"]


def test_post_for_never_started_capture_is_dropped():
    _qapp()
    bridge = UiBridge()
    delivered = []
    assert bridge.post_for("never-begun", lambda: delivered.append("x")) is False
    assert delivered == []


def test_worker_stale_post_is_dropped_before_queueing():
    _qapp()
    bridge = UiBridge()
    delivered = []
    bridge.begin_capture("A")
    bridge.begin_capture("B")

    t = threading.Thread(
        target=lambda: bridge.post_for("A", lambda: delivered.append("stale"))
    )
    t.start()
    t.join()

    time.sleep(0.05)
    _qapp().processEvents()
    assert delivered == []


def test_broken_callback_does_not_break_the_bridge():
    _qapp()
    bridge = UiBridge()
    results = []

    def boom():
        raise RuntimeError("widget exploded")

    bridge.post(boom)
    bridge.post(lambda: results.append("still-alive"))

    assert _wait_until(lambda: results)
    assert results == ["still-alive"]


# ---------------------------------------------------------------------------
# Screenshot failure must not wedge the session
# ---------------------------------------------------------------------------


def _annotating_session(sm: SessionManager):
    session = sm.start_session()
    sm.transition_to(CaptureState.ANNOTATING)
    sm.transition_to(CaptureState.COLLECTING_CONTEXT)
    return session


def test_screenshot_failure_fails_the_session_and_recovers():
    sm = SessionManager()
    session = _annotating_session(sm)

    def failing_capture():
        raise RuntimeError("mss: no monitor")

    try:
        failing_capture()
        raise AssertionError("expected the capture to raise")
    except Exception as e:
        applied = sm.fail_if_active(session.capture_id, f"screenshot failed: {e}")

    assert applied is True
    assert session.state is CaptureState.FAILED
    assert "screenshot failed" in session.error

    # Not wedged: the session can return to IDLE and a new capture can start.
    sm.transition_to(CaptureState.IDLE)
    session2 = sm.start_session()
    assert session2.capture_id != session.capture_id
    assert session2.state is CaptureState.STARTING


def test_failure_for_stale_capture_is_ignored():
    sm = SessionManager()
    old = _annotating_session(sm)
    new = sm.start_session()  # auto-cancels `old`

    applied = sm.fail_if_active(old.capture_id, "too late")
    assert applied is False
    assert new.state is CaptureState.STARTING
    assert old.state is CaptureState.CANCELLED


def test_fail_if_active_without_session_is_safe():
    sm = SessionManager()
    assert sm.fail_if_active(None, "x") is False
    assert sm.fail_if_active("ghost", "x") is False


# ---------------------------------------------------------------------------
# Session state machine under concurrent access
# ---------------------------------------------------------------------------


def test_concurrent_transitions_never_corrupt_state():
    sm = SessionManager()
    session = sm.start_session()
    errors = []

    def worker():
        for _ in range(50):
            try:
                sm.transition_to(CaptureState.ANNOTATING)
            except ValueError:
                pass
            except Exception as e:  # pragma: no cover - corruption signal
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert session.state in set(CaptureState)
    assert sm.is_active(session.capture_id)


def test_is_active_matches_capture_lifecycle():
    sm = SessionManager()
    assert sm.is_active(None) is False
    assert sm.is_active("x") is False

    a = sm.start_session()
    assert sm.is_active(a.capture_id) is True
    assert sm.is_active("other") is False

    b = sm.start_session()
    assert sm.is_active(a.capture_id) is False
    assert sm.is_active(b.capture_id) is True
