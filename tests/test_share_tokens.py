"""Scoped, short-lived screenshot share tokens (Agentation access path)."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time

import pytest

os.environ.setdefault("ARROW_HOME", tempfile.mkdtemp(prefix="arrow_share_"))

from arrow.server import server as srv  # noqa: E402
from arrow.server.screenshots import save_image_bytes  # noqa: E402
from arrow.server.security import (  # noqa: E402
    ShareTokenManager,
    ShareTokenManagerMintError,
    TokenManager,
    is_safe_filename,
)


@pytest.fixture()
def shares():
    tm = TokenManager(path=os.path.join(tempfile.mkdtemp(prefix="arrow_sh_tok_"), "token"))
    return ShareTokenManager(tm, ttl_seconds=60)


def _png_bytes(color=(255, 0, 0)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Token primitives
# ---------------------------------------------------------------------------


def test_mint_and_verify_roundtrip(shares):
    token = shares.mint("capture_abc.png")
    assert shares.verify(token, "capture_abc.png") is True


def test_token_scoped_to_filename(shares):
    token = shares.mint("capture_abc.png")
    assert shares.verify(token, "capture_other.png") is False


def test_token_expires(shares):
    clock = {"now": 1_000_000.0}
    tm = TokenManager(path=os.path.join(tempfile.mkdtemp(prefix="arrow_sh_exp_"), "token"))
    mgr = ShareTokenManager(tm, ttl_seconds=30, clock=lambda: clock["now"])
    token = mgr.mint("a.png")
    assert mgr.verify(token, "a.png") is True
    clock["now"] += 31
    assert mgr.verify(token, "a.png") is False


def test_tampered_token_rejected(shares):
    token = shares.mint("capture_abc.png")
    body, mac = token.split(".")
    # Flip a character in the payload while keeping valid base64.
    decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    payload = json.loads(decoded)
    payload["f"] = "other.png"
    forged = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    assert shares.verify(f"{forged}.{mac}", "other.png") is False


def test_garbage_tokens_rejected(shares):
    for bad in ["", "x", "a.b", "not-a-token", None, 123, "..", "a.b.c"]:
        assert shares.verify(bad, "a.png") is False


def test_mint_refuses_unsafe_filenames(shares):
    for bad in ["../evil.png", "a/b.png", "a\\b.png", "", "C:evil.png"]:
        with pytest.raises(ShareTokenManagerMintError):
            shares.mint(bad)


def test_share_url_contains_token(shares):
    url = shares.share_url("http://127.0.0.1:5001", "capture.png")
    assert url.startswith("http://127.0.0.1:5001/screenshots/capture.png?t=")
    token = url.split("?t=", 1)[1]
    assert shares.verify(token, "capture.png") is True


@pytest.mark.parametrize(
    "name,expected",
    [
        ("ok.png", True),
        ("capture_20260101_120000_ab12cd34.png", True),
        ("..", False),
        (".", False),
        ("../x.png", False),
        ("a/b.png", False),
        ("a\\b.png", False),
        ("C:evil.png", False),
        ("/abs.png", False),
        ("", False),
        ("x" * 300 + ".png", False),
    ],
)
def test_is_safe_filename(name, expected):
    assert is_safe_filename(name) is expected


# ---------------------------------------------------------------------------
# HTTP integration: GET /screenshots/<file>
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    token_path = os.path.join(tempfile.mkdtemp(prefix="arrow_sh_http_"), "token")
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(path=token_path))
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", srv.CapabilityManager())
    tm = srv.app.config["TOKEN_MANAGER"]
    monkeypatch.setitem(srv.app.config, "SHARE_TOKENS", ShareTokenManager(tm, ttl_seconds=60))
    return srv.app.test_client()


@pytest.fixture()
def shot_file():
    directory = os.path.join(tempfile.mkdtemp(prefix="arrow_sh_files_"))
    filename, path = save_image_bytes(_png_bytes(), directory, "capture")
    return directory, filename, path


def test_fetch_without_credentials_rejected(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    resp = client.get(f"/screenshots/{filename}")
    assert resp.status_code == 401


def test_fetch_with_bad_bearer_rejected(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    resp = client.get(f"/screenshots/{filename}", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_fetch_with_valid_bearer_works(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    token = srv.app.config["TOKEN_MANAGER"].get_or_create()
    resp = client.get(f"/screenshots/{filename}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_fetch_with_share_token_works(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    token = srv.app.config["SHARE_TOKENS"].mint(filename)
    resp = client.get(f"/screenshots/{filename}?t={token}")
    assert resp.status_code == 200


def test_share_token_from_header_works(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    token = srv.app.config["SHARE_TOKENS"].mint(filename)
    resp = client.get(f"/screenshots/{filename}", headers={"X-Arrow-Share": token})
    assert resp.status_code == 200


def test_share_token_for_other_file_rejected(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    token = srv.app.config["SHARE_TOKENS"].mint("some_other_file.png")
    resp = client.get(f"/screenshots/{filename}?t={token}")
    assert resp.status_code == 401


def test_expired_share_token_rejected(client, shot_file, monkeypatch):
    directory, filename, _ = shot_file
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", directory)
    tm = srv.app.config["TOKEN_MANAGER"]
    expired = ShareTokenManager(tm, ttl_seconds=60, clock=lambda: time.time() - 3600).mint(filename)
    resp = client.get(f"/screenshots/{filename}?t={expired}")
    assert resp.status_code == 401


def test_path_traversal_rejected(client, monkeypatch):
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", tempfile.mkdtemp(prefix="arrow_sh_trav_"))
    token = srv.app.config["TOKEN_MANAGER"].get_or_create()
    headers = {"Authorization": f"Bearer {token}"}
    # Unauthenticated probing stops at 401 before any path logic runs...
    assert client.get("/screenshots/..%2F..%2Fpyproject.toml").status_code == 401
    # ...and even a fully authorized caller cannot escape the directory.
    for evil in ["..%2F..%2Fetc%2Fpasswd", "..\\..\\pyproject.toml", "..%5C..%5Cmain.py",
                 "....//....//main.py", "%2e%2e%2fmain.py"]:
        resp = client.get(f"/screenshots/{evil}", headers=headers)
        assert resp.status_code in (400, 404), f"{evil} -> {resp.status_code}"


def test_missing_file_returns_404_not_401(client, monkeypatch):
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", tempfile.mkdtemp(prefix="arrow_sh_404_"))
    token = srv.app.config["TOKEN_MANAGER"].get_or_create()
    resp = client.get("/screenshots/does_not_exist.png", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "not found" in body
    assert "D:\\" not in body and "/home" not in body
