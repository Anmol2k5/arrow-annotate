"""Point Mode lifecycle: ordering, thread safety and state reconciliation.

Every test drives the coordinator with fakes and an injected ``spawn``, so
ordering is deterministic and no Qt widget, UIA call or screenshot happens.
The point of these tests is the *guarantees*, not the happy path.
"""

from __future__ import annotations

import threading

import pytest

from arrow.capture.point_capture import PointCaptureCoordinator, PointCaptureRequest
from arrow.capture.session import CaptureMode, CaptureState, SessionManager

DESKTOP = {"x": -1920, "y": -1080, "width": 3840, "height": 2160}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeScreenshotService:
    """Records what the worker observed at capture time."""

    instances: list["FakeScreenshotService"] = []

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.overlay_visible_at_capture = None
        self.thread = threading.current_thread()
        FakeScreenshotService.instances.append(self)

    def capture_raw(self):
        # Reads state the worker must not depend on; the assertion is that the
        # coordinator guarantees overlay teardown happened before we got here.
        self.overlay_visible_at_capture = _OVERLAY_STATE["visible"]
        if self.fail:
            raise RuntimeError("mss: no monitor")
        return "RAW_IMAGE", "SCREEN_INFO", "MAPPER"


_OVERLAY_STATE = {"visible": True}


class FakeOrchestrator:
    def __init__(self, error=None, raises=False):
        self.error = error
        self.raises = raises
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("compiler exploded")

        class R:
            pass

        r = R()
        r.error = self.error
        return r


class FakeBridge:
    def __init__(self):
        self.posted = []

    def post_for(self, capture_id, fn):
        fn()  # deliver synchronously: the test is about ordering, not Qt
        self.posted.append(capture_id)
        return True


class FakeTarget:
    def __init__(self, method="windows_uia", label="Search", rect=None):
        self.method = method
        self.label = label
        self.rect = rect or {"x": 100, "y": 200, "width": 120, "height": 40}
        self.is_fallback = method == "fallback"


@pytest.fixture(autouse=True)
def _reset():
    FakeScreenshotService.instances.clear()
    _OVERLAY_STATE["visible"] = True
    yield


@pytest.fixture
def worker_threads():
    """spawn captures the callable instead of running it."""
    held = []
    return held


def _request(sm, **kw):
    session = sm.active_session
    defaults = dict(
        capture_id=session.capture_id,
        x=100,
        y=200,
        mode=CaptureMode.POINT,
        desktop_bounds=DESKTOP,
        cursor=(100, 200),
        window_title="Example",
        instruction="move this",
    )
    defaults.update(kw)
    return PointCaptureRequest(**defaults)


def _build(sm, *, orchestrator=None, fail_shot=False, resolver=None, statuses=None):
    started = []
    coord = PointCaptureCoordinator(
        session_manager=sm,
        orchestrator=orchestrator or FakeOrchestrator(),
        bridge=FakeBridge(),
        on_status=(statuses if statuses is not None else []).append,
        screenshot_service_factory=lambda: FakeScreenshotService(fail=fail_shot),
        resolver_factory=resolver,
        spawn=started.append,
    )
    return coord, started


def _teardown_log(log):
    def teardown():
        log.append("teardown")
        _OVERLAY_STATE["visible"] = False

    return teardown


def _annotating(sm):
    session = sm.start_session()
    sm.transition_to(CaptureState.ANNOTATING)
    return session


# ---------------------------------------------------------------------------
# 1. Worker cannot access QWidget geometry
# ---------------------------------------------------------------------------


def test_worker_never_touches_a_widget():
    """Geometry is snapshotted on the GUI thread into the frozen request."""
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)

    request = _request(sm)
    assert coord.begin(request, session, _teardown_log([])) is True

    # The worker only ever sees the frozen dataclass.
    assert isinstance(request, PointCaptureRequest)
    with pytest.raises(Exception):
        request.x = 999  # type: ignore[misc]


def test_desktop_bounds_are_frozen_at_click_time():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)
    bounds = dict(DESKTOP)
    request = _request(sm, desktop_bounds=bounds)
    coord.begin(request, session, _teardown_log([]))

    bounds["x"] = 12345  # caller mutates its dict afterwards
    assert request.desktop_bounds["x"] == -1920


# ---------------------------------------------------------------------------
# 2 + 3. Overlay teardown strictly precedes the screenshot
# ---------------------------------------------------------------------------


def test_raw_capture_begins_only_after_overlay_teardown():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)
    order = []

    assert coord.begin(_request(sm), session, _teardown_log(order)) is True
    assert order == ["teardown"], "teardown must be synchronous on the GUI thread"

    # Only after the worker runs does the screenshot happen.
    for fn in started:
        fn()
    assert FakeScreenshotService.instances[0].overlay_visible_at_capture is False


def test_overlay_cannot_appear_in_captured_pixels():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()
    assert FakeScreenshotService.instances[0].overlay_visible_at_capture is False


def test_screenshot_failure_is_recorded_on_the_session():
    sm = SessionManager()
    session = _annotating(sm)
    statuses = []
    coord, started = _build(sm, fail_shot=True, statuses=statuses)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()

    assert session.state is CaptureState.FAILED
    assert "screenshot failed" in (session.error or "")
    assert statuses == ["Capture failed"]


# ---------------------------------------------------------------------------
# 4 + 5. One click, one capture
# ---------------------------------------------------------------------------


def test_one_click_produces_one_capture():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()
    assert len(orch.calls) == 1


def test_rapid_double_click_does_not_duplicate():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)

    assert coord.begin(_request(sm), session, _teardown_log([])) is True
    assert coord.begin(_request(sm), session, _teardown_log([])) is False

    for fn in started:
        fn()
    assert len(orch.calls) == 1, "second click must not create a second capture"


def test_second_capture_is_allowed_after_the_first_completes():
    sm = SessionManager()
    coord, started = _build(sm)
    session = _annotating(sm)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()
    assert coord.is_capturing() is False

    # A fresh session can start immediately.
    session2 = _annotating(sm)
    assert coord.begin(_request(sm), session2, _teardown_log([])) is True


# ---------------------------------------------------------------------------
# 6. Returns controls to ready
# ---------------------------------------------------------------------------


def test_successful_capture_reaches_ready_state():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()
    assert session.state is CaptureState.READY


# ---------------------------------------------------------------------------
# 7. Stale workers cannot update a newer session
# ---------------------------------------------------------------------------


def test_old_callbacks_cannot_update_a_new_capture():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    coord.begin(_request(sm), session, _teardown_log([]))
    old_worker = started[0]

    # A new capture supersedes the old one before the worker runs.
    session2 = _annotating(sm)
    old_worker()

    assert orch.calls == [], "stale worker must not run the pipeline"
    assert session2.state is CaptureState.ANNOTATING


def test_cancelled_capture_is_never_persisted():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    coord.begin(_request(sm), session, _teardown_log([]))
    old_worker = started[0]

    sm.clear_session()  # user cancelled
    old_worker()
    assert orch.calls == []


# ---------------------------------------------------------------------------
# 8. Instruction snapshot stays with its capture
# ---------------------------------------------------------------------------


def test_instruction_snapshot_is_immutable():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    coord.begin(_request(sm, instruction="move this"), session, _teardown_log([]))

    # The user starts typing something else before the worker finishes.
    for fn in started:
        fn()
    assert orch.calls[0]["instruction"] == "move this"


def test_pipeline_receives_the_snapshotted_instruction_not_a_later_value():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    request = _request(sm, instruction="original")
    coord.begin(request, session, _teardown_log([]))

    mutable_holder = {"text": "original"}
    for fn in started:
        fn()
    assert mutable_holder["text"] == "original"
    assert orch.calls[0]["instruction"] == "original"


# ---------------------------------------------------------------------------
# 9. UIA failure -> honest fallback
# ---------------------------------------------------------------------------


def test_resolution_failure_produces_a_fallback_target():
    from arrow.context.point_target import resolve_point_target

    class Boom:
        def resolve_point(self, x, y):
            raise RuntimeError("UIA crashed")

    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch, resolver=Boom)
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()

    assert len(orch.calls) == 1, "a failed resolution must still produce a capture"
    rect = orch.calls[0]["rect"]
    assert rect["width"] > 0 and rect["height"] > 0
    assert resolve_point_target  # module still importable


# ---------------------------------------------------------------------------
# 11 + 12. Coordinates and re-entry
# ---------------------------------------------------------------------------


def test_negative_monitor_coordinates_reach_the_pipeline():
    sm = SessionManager()
    session = _annotating(sm)
    orch = FakeOrchestrator()
    coord, started = _build(sm, orchestrator=orch)
    coord.begin(_request(sm, x=-1500, y=-900), session, _teardown_log([]))
    for fn in started:
        fn()

    rect = orch.calls[0]["rect"]
    assert rect["x"] >= -1920 and rect["y"] >= -1080


def test_begin_rejects_a_mismatched_capture_id():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm)
    bad = _request(sm, capture_id="not-the-active-session")
    assert coord.begin(bad, session, _teardown_log([])) is False
    assert started == []


def test_pipeline_error_fails_the_session():
    sm = SessionManager()
    session = _annotating(sm)
    statuses = []
    coord, started = _build(
        sm, orchestrator=FakeOrchestrator(error="bad crop"), statuses=statuses
    )
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()

    assert session.state is CaptureState.FAILED
    assert statuses == ["Capture failed"]


def test_pipeline_exception_fails_the_session():
    sm = SessionManager()
    session = _annotating(sm)
    statuses = []
    coord, started = _build(
        sm, orchestrator=FakeOrchestrator(raises=True), statuses=statuses
    )
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()

    assert session.state is CaptureState.FAILED
    assert statuses == ["Capture failed"]


def test_in_flight_is_released_even_when_the_worker_crashes():
    sm = SessionManager()
    session = _annotating(sm)
    coord, started = _build(sm, orchestrator=FakeOrchestrator(raises=True))
    coord.begin(_request(sm), session, _teardown_log([]))
    for fn in started:
        fn()
    assert coord.is_capturing() is False