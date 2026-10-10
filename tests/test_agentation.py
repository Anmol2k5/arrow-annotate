"""Agentation handoff: capture → store → intent → provider, with graceful
degradation when Agentation is offline."""

from __future__ import annotations

import os
import socket

import pytest

from arrow.capture.session import CaptureState, SessionManager
from arrow.providers.agentation import (
    AgentationClient,
    AgentationError,
    pick_session_id,
    send_capture_annotation,
)
from arrow.storage.schemas import CaptureRecord


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = repr(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AgentationError(f"HTTP {self.status_code}")


class FakeSession:
    """Stand-in for requests.Session with scriptable responses."""

    def __init__(self):
        self.headers = {}
        self.calls = []
        self._routes = {}

    def route(self, method, path, payload, status=200):
        self._routes[(method, path)] = (payload, status)

    def _handle(self, method, path, json=None):
        self.calls.append((method, path, json))
        if (method, path) not in self._routes:
            raise AssertionError(f"unexpected {method} {path}")
        payload, status = self._routes[(method, path)]
        return FakeResponse(payload, status)

    def get(self, url, timeout=None):
        path = url.split("127.0.0.1:4747", 1)[-1]
        return self._handle("GET", path)

    def post(self, url, json=None, timeout=None):
        path = url.split("127.0.0.1:4747", 1)[-1]
        return self._handle("POST", path, json)

    def patch(self, url, json=None, timeout=None):
        path = url.split("127.0.0.1:4747", 1)[-1]
        return self._handle("PATCH", path, json)


def make_client():
    client = AgentationClient()
    fake = FakeSession()
    client._session = fake
    return client, fake


def make_record(tmp_path, annotation_text="move the button"):
    shot = tmp_path / "captures" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"\x89PNG-fake")
    return CaptureRecord(
        id="cap-1",
        timestamp="2026-10-08T12:00:00Z",
        screenshot_path=str(shot),
        annotation_text=annotation_text,
    )


def free_closed_port() -> int:
    """Reserve an ephemeral port and release it, so nothing listens there."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Client behaviour
# ---------------------------------------------------------------------------


def test_client_offline_raises_agentation_error():
    port = free_closed_port()
    client = AgentationClient(base_url=f"http://127.0.0.1:{port}")
    with pytest.raises(AgentationError) as excinfo:
        client.list_sessions()
    assert "GET /sessions failed" in str(excinfo.value)


def test_client_create_session_posts_url():
    client, fake = make_client()
    fake.route("POST", "/sessions", {"id": "sess-new"}, status=201)
    result = client.create_session("bluely://desktop")
    assert result["id"] == "sess-new"
    method, path, body = fake.calls[-1]
    assert (method, path) == ("POST", "/sessions")
    assert body == {"url": "bluely://desktop"}


def test_add_annotation_requires_core_fields():
    client, _ = make_client()
    with pytest.raises(AgentationError) as excinfo:
        client.add_annotation("sess-1", {"comment": "x"})
    assert "element" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Session selection (the audit's "first session blindly" finding)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sessions,expected",
    [
        ([], None),
        (None, None),
        ([{"name": "no-id"}, {"other": 1}], None),
        ([{"id": "a"}, {"id": "b"}], "a"),
        ([{"name": "skip"}, {"id": "kept"}, {"id": "later"}], "kept"),
        ([{"id": 123}], "123"),
    ],
)
def test_pick_session_id_skips_malformed_entries(sessions, expected):
    assert pick_session_id(sessions) == expected


def test_send_capture_reuses_existing_session(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [{"id": "sess-1"}])
    fake.route("POST", "/sessions/sess-1/annotations", {"id": "ann-1"}, status=201)

    session_id = send_capture_annotation(client, make_record(tmp_path), "http://x/img.png")
    assert session_id == "sess-1"
    paths = [(m, p) for m, p, _ in fake.calls]
    assert ("POST", "/sessions") not in paths, "must not create a session when one exists"


def test_send_capture_annotation_payload_is_complete(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [{"id": "sess-1"}])
    fake.route("POST", "/sessions/sess-1/annotations", {"id": "ann-1"}, status=201)

    send_capture_annotation(client, make_record(tmp_path), "http://127.0.0.1:5001/share.png")

    method, path, body = fake.calls[-1]
    assert (method, path) == ("POST", "/sessions/sess-1/annotations")
    assert body["comment"] == "move the button"
    assert body["element"] == "desktop_screen"
    assert body["elementPath"] == "desktop"
    assert body["imagePath"] == "http://127.0.0.1:5001/share.png"


def test_send_capture_defaults_comment_when_empty(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [{"id": "sess-1"}])
    fake.route("POST", "/sessions/sess-1/annotations", {"id": "ann-1"}, status=201)

    send_capture_annotation(client, make_record(tmp_path, annotation_text=""), "u")
    assert fake.calls[-1][2]["comment"] == "Visual highlight"


def test_send_capture_creates_session_when_none(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [])
    fake.route("POST", "/sessions", {"id": "sess-new"}, status=201)
    fake.route("POST", "/sessions/sess-new/annotations", {"id": "ann-1"}, status=201)

    session_id = send_capture_annotation(client, make_record(tmp_path), "u")
    assert session_id == "sess-new"
    paths = [(m, p) for m, p, _ in fake.calls]
    assert ("POST", "/sessions") in paths


def test_send_capture_skips_malformed_sessions_and_creates(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [{"name": "broken"}, {"id": ""}])
    fake.route("POST", "/sessions", {"id": "sess-new"}, status=201)
    fake.route("POST", "/sessions/sess-new/annotations", {"id": "ann-1"}, status=201)

    session_id = send_capture_annotation(client, make_record(tmp_path), "u")
    assert session_id == "sess-new"


def test_send_capture_rejects_create_without_id(tmp_path):
    client, fake = make_client()
    fake.route("GET", "/sessions", [])
    fake.route("POST", "/sessions", {"ok": True}, status=201)

    with pytest.raises(AgentationError, match="no session id"):
        send_capture_annotation(client, make_record(tmp_path), "u")


def test_send_capture_offline_raises(tmp_path):
    port = free_closed_port()
    client = AgentationClient(base_url=f"http://127.0.0.1:{port}")
    with pytest.raises(AgentationError):
        send_capture_annotation(client, make_record(tmp_path), "u")


# ---------------------------------------------------------------------------
# End-to-end: pipeline record → handoff, offline degradation
# ---------------------------------------------------------------------------


def _record_from_pipeline_store(tmp_path):
    """Build a store-backed record the way the capture pipeline does."""
    from arrow.storage.capture_store import CaptureStore

    store = CaptureStore(db_path=str(tmp_path / "captures.db"))
    record = CaptureRecord(
        id="cap-e2e",
        timestamp="2026-10-08T12:00:00Z",
        screenshot_path=str(tmp_path / "shot.png"),
        annotation_text="resize this card",
    )
    (tmp_path / "shot.png").write_bytes(b"\x89PNG-fake")
    store.add(record)
    loaded = store.get("cap-e2e")
    assert loaded is not None
    return loaded


def test_pipeline_record_flows_into_agentation_handoff(tmp_path):
    record = _record_from_pipeline_store(tmp_path)
    client, fake = make_client()
    fake.route("GET", "/sessions", [{"id": "sess-1"}])
    fake.route("POST", "/sessions/sess-1/annotations", {"id": "ann-1"}, status=201)

    image_url = f"http://127.0.0.1:5001/share/{os.path.basename(record.screenshot_path)}"
    session_id = send_capture_annotation(client, record, image_url)

    assert session_id == "sess-1"
    body = fake.calls[-1][2]
    assert body["comment"] == "resize this card"
    assert body["imagePath"].endswith("shot.png")


def test_agentation_offline_completes_session_without_crashing(tmp_path):
    """Offline Agentation must not fail a locally saved capture: the session
    completes (the screenshot is already stored) and the app degrades with an
    offline status instead of an error."""
    sm = SessionManager()
    session = sm.start_session()
    sm.transition_to(CaptureState.ANNOTATING)
    sm.transition_to(CaptureState.COLLECTING_CONTEXT)
    sm.transition_to(CaptureState.PROCESSING)
    sm.transition_to(CaptureState.PREVIEW)
    sm.transition_to(CaptureState.READY)
    sm.transition_to(CaptureState.SENDING)
    sm.transition_to(CaptureState.RUNNING)

    port = free_closed_port()
    client = AgentationClient(base_url=f"http://127.0.0.1:{port}")

    with pytest.raises(AgentationError) as excinfo:
        send_capture_annotation(client, make_record(tmp_path, "x"), "u")
    assert "failed" in str(excinfo.value)

    # Local capture is fine: complete, do not fail.
    applied = sm.complete_if_active(session.capture_id)
    assert applied is True
    assert session.state is CaptureState.COMPLETED
    assert session.error is None

    # Recoverable: back to IDLE, a new capture can start.
    sm.transition_to(CaptureState.IDLE)
    assert sm.start_session().state is CaptureState.STARTING


def test_complete_if_active_ignores_superseded_session():
    sm = SessionManager()
    session = sm.start_session()
    sm.transition_to(CaptureState.ANNOTATING)
    sm.transition_to(CaptureState.COLLECTING_CONTEXT)
    sm.transition_to(CaptureState.PROCESSING)
    sm.transition_to(CaptureState.PREVIEW)
    sm.transition_to(CaptureState.READY)
    sm.transition_to(CaptureState.SENDING)
    sm.transition_to(CaptureState.RUNNING)
    old_id = session.capture_id

    # A new capture supersedes the old one.
    sm.start_session()
    assert sm.complete_if_active(old_id) is False
    assert sm.active_session is not None
    assert sm.active_session.capture_id != old_id
