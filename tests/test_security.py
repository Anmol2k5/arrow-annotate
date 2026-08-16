"""Tests for the local server security surface (Phase 14)."""

from __future__ import annotations

import os
import tempfile
import threading

# Isolate the token/config dir before the server module computes it at import.
os.environ["ARROW_HOME"] = tempfile.mkdtemp(prefix="arrow_test_")

import pytest

from arrow.server import server as srv
from arrow.server.security import (
    Capability,
    CapabilityManager,
    TokenManager,
    is_localhost_origin,
    parse_bearer,
)

# ---------------------------------------------------------------------------
# TokenManager
# ---------------------------------------------------------------------------


def test_token_persisted_and_stable():
    tm = TokenManager()
    first = tm.get_or_create()
    second = tm.get_or_create()
    assert first == second
    assert len(first) >= 40
    assert os.path.isfile(tm._path)
    with open(tm._path, encoding="utf-8") as f:
        assert f.read().strip() == first


def test_token_reloaded_from_disk():
    tm1 = TokenManager()
    token = tm1.get_or_create()
    tm2 = TokenManager()  # fresh instance reads the same file
    assert tm2.get_or_create() == token
    assert tm2.verify(token) is True


def test_token_verify_rejects_bad_inputs():
    tm = TokenManager()
    token = tm.get_or_create()
    assert tm.verify(token) is True
    assert tm.verify("wrong") is False
    assert tm.verify("") is False
    assert tm.verify(None) is False
    assert tm.verify(token + "x") is False


def test_token_creation_is_thread_safe():
    """Concurrent first-ever calls must agree on a single token."""
    tm = TokenManager()
    results: list[str] = []
    errors: list[BaseException] = []

    def _run():
        try:
            results.append(tm.get_or_create())
        except BaseException as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=_run) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(set(results)) == 1
    with open(tm._path, encoding="utf-8") as f:
        assert f.read().strip() == results[0]


# ---------------------------------------------------------------------------
# Bearer parsing / origin checks
# ---------------------------------------------------------------------------


def test_parse_bearer():
    assert parse_bearer("Bearer abc123") == "abc123"
    assert parse_bearer("bearer abc") == "abc"
    assert parse_bearer("Bearer  abc") == "abc"
    assert parse_bearer("Bearer") is None
    assert parse_bearer("Basic abc") is None
    assert parse_bearer("") is None
    assert parse_bearer(None) is None


def test_is_localhost_origin():
    assert is_localhost_origin(None) is True  # non-browser clients
    assert is_localhost_origin("http://127.0.0.1:5001") is True
    assert is_localhost_origin("http://localhost:3000") is True
    assert is_localhost_origin("http://[::1]:5001") is True
    assert is_localhost_origin("https://evil.com") is False
    assert is_localhost_origin("null") is False  # opaque origins


# ---------------------------------------------------------------------------
# CapabilityManager
# ---------------------------------------------------------------------------


def test_capability_defaults():
    caps = CapabilityManager()
    assert caps.is_enabled(Capability.READ_SCREENSHOT) is True
    assert caps.is_enabled(Capability.READ_CAPTURE_CONTEXT) is True
    assert caps.is_enabled(Capability.READ_REPO_CONTEXT) is True
    assert caps.is_enabled(Capability.CONTROL_NATIVE) is False
    assert caps.is_enabled(Capability.EXECUTE_COMMAND) is False
    assert caps.is_enabled(Capability.MODIFY_FILES) is False
    assert caps.is_enabled(Capability.RUN_PROVIDER) is False


def test_capability_env_opt_in(monkeypatch):
    monkeypatch.setenv("ARROW_ENABLED_CAPABILITIES", "control_native, run_provider")
    caps = CapabilityManager()
    assert caps.is_enabled(Capability.CONTROL_NATIVE) is True
    assert caps.is_enabled(Capability.RUN_PROVIDER) is True
    # read caps remain on
    assert caps.is_enabled(Capability.READ_SCREENSHOT) is True


def test_capability_env_ignores_unknown(monkeypatch):
    monkeypatch.setenv("ARROW_ENABLED_CAPABILITIES", "control_native, bogus_cap")
    caps = CapabilityManager()
    assert caps.is_enabled(Capability.CONTROL_NATIVE) is True


def test_capability_enable_disable():
    caps = CapabilityManager()
    caps.enable(Capability.CONTROL_NATIVE)
    assert caps.is_enabled(Capability.CONTROL_NATIVE) is True
    caps.disable(Capability.CONTROL_NATIVE)
    assert caps.is_enabled(Capability.CONTROL_NATIVE) is False


# ---------------------------------------------------------------------------
# require_capability gate (full Flask stack)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    # Per-test capability state + isolated token.
    token_path = os.path.join(tempfile.mkdtemp(prefix="arrow_tok_"), "token")
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(path=token_path))
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", CapabilityManager())
    return srv.app.test_client()


def _token():
    return srv.app.config["TOKEN_MANAGER"].get_or_create()


def test_execute_requires_token(client):
    resp = client.post("/execute", json={"type": "type", "target": "hi"})
    assert resp.status_code == 401


def test_execute_requires_enabled_capability(client):
    resp = client.post(
        "/execute",
        json={"type": "type", "target": "hi"},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert resp.status_code == 403
    assert "disabled" in resp.get_json()["error"]


def test_execute_rejects_non_localhost_origin(client):
    srv.app.config["CAPABILITIES"].enable(Capability.CONTROL_NATIVE)
    resp = client.post(
        "/execute",
        json={"type": "type", "target": "hi"},
        headers={"Authorization": f"Bearer {_token()}", "Origin": "https://evil.com"},
    )
    assert resp.status_code == 403


def test_execute_accepts_localhost_origin_with_token(client):
    srv.app.config["CAPABILITIES"].enable(Capability.CONTROL_NATIVE)
    resp = client.post(
        "/execute",
        json={"type": "openapp", "target": "definitely_missing_file_xyz"},
        headers={"Authorization": f"Bearer {_token()}", "Origin": "http://localhost:3000"},
    )
    # Gate passed; handler runs and returns an error for a missing path
    # (proves open_app never reaches a shell with arbitrary strings).
    assert resp.status_code == 400
    assert "existing file/application paths" in resp.get_json()["error"]


def test_open_app_rejects_missing_path_without_shell(client):
    srv.app.config["CAPABILITIES"].enable(Capability.CONTROL_NATIVE)
    resp = client.post(
        "/execute",
        json={"type": "openapp", "target": "notepad & echo pwned"},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert resp.status_code == 400
    assert "existing file/application paths" in resp.get_json()["error"]


def test_batch_and_highlight_execute_gated(client):
    resp = client.post("/execute/batch", json={"actions": []})
    assert resp.status_code == 401
    resp = client.post("/highlight/execute", json={"rect": {}, "action": {}})
    assert resp.status_code == 401
