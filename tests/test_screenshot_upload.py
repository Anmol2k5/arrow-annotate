"""Screenshot upload validation, filename uniqueness and atomic saves."""

from __future__ import annotations

import base64
import io
import os
import tempfile
import threading

import pytest

os.environ.setdefault("ARROW_HOME", tempfile.mkdtemp(prefix="arrow_upload_"))

from arrow.server import server as srv  # noqa: E402
from arrow.server.screenshots import (  # noqa: E402
    MAX_DECODED_BYTES,
    UploadError,
    decode_image_b64,
    safe_join,
    save_decoded_upload,
    save_image_bytes,
    sniff_format,
    unique_filename,
    validate_image,
)
from arrow.server.security import CapabilityManager, TokenManager  # noqa: E402


def png_bytes(size=(8, 8), color=(10, 20, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Filename uniqueness
# ---------------------------------------------------------------------------


def test_unique_filename_same_second_differs():
    names = {unique_filename("capture", now=1_700_000_000.0) for _ in range(50)}
    assert len(names) == 50
    for name in names:
        assert name.startswith("capture_")
        assert name.endswith(".png")


def test_unique_filename_concurrent():
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker():
        try:
            for _ in range(20):
                name = unique_filename("highlight")
                with lock:
                    results.append(name)
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == len(set(results))


def test_unique_filename_rejects_bad_prefix_and_suffix():
    with pytest.raises(UploadError):
        unique_filename("../evil")
    with pytest.raises(UploadError):
        unique_filename("ok", suffix=".exe")
    with pytest.raises(UploadError):
        unique_filename("has space")


def test_concurrent_saves_write_distinct_files():
    directory = tempfile.mkdtemp(prefix="arrow_conc_")
    saved: list[str] = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(10):
                filename, path = save_image_bytes(png_bytes(), directory, "capture")
                assert os.path.isfile(path)
                with lock:
                    saved.append(filename)
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(saved) == len(set(saved)) == 60
    leftovers = [f for f in os.listdir(directory) if f.endswith(".tmp")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


def test_decode_rejects_non_string_and_empty():
    for bad in [None, "", "   ", 42, b"bytes"]:
        with pytest.raises(UploadError):
            decode_image_b64(bad)


def test_decode_rejects_invalid_base64():
    with pytest.raises(UploadError) as exc:
        decode_image_b64("not!!valid@@base64==")
    assert exc.value.status == 400


def test_decode_accepts_data_url():
    raw = base64.b64encode(png_bytes()).decode()
    assert decode_image_b64(f"data:image/png;base64,{raw}") == png_bytes()


def test_decode_rejects_oversized_payload():
    with pytest.raises(UploadError) as exc:
        decode_image_b64("A" * ((MAX_DECODED_BYTES * 4) // 3 + 64))
    assert exc.value.status == 413


def test_validate_rejects_non_image():
    with pytest.raises(UploadError) as exc:
        validate_image(b"MZ this is an executable, not an image")
    assert exc.value.status == 415


def test_validate_rejects_truncated_png():
    good = png_bytes()
    with pytest.raises(UploadError):
        validate_image(good[:20])


def test_validate_accepts_png():
    fmt, w, h = validate_image(png_bytes(size=(16, 9)))
    assert fmt == "PNG"
    assert (w, h) == (16, 9)


def test_sniff_format():
    assert sniff_format(png_bytes()) == "PNG"
    assert sniff_format(b"\xff\xd8\xff\xe0rest") == "JPEG"
    assert sniff_format(b"random bytes") is None


def test_validate_rejects_oversized_dimensions():
    from PIL import Image

    from arrow.server.screenshots import MAX_IMAGE_DIMENSION

    buf = io.BytesIO()
    Image.new("RGB", (MAX_IMAGE_DIMENSION + 1, 1)).save(buf, format="PNG")
    with pytest.raises(UploadError) as exc:
        validate_image(buf.getvalue())
    assert exc.value.status == 413


def test_safe_join_blocks_traversal():
    directory = tempfile.mkdtemp(prefix="arrow_safe_")
    assert safe_join(directory, "a.png").startswith(os.path.abspath(directory))
    for evil in ["../a.png", "..\\a.png", "/etc/passwd", "C:\\x.png", ""]:
        with pytest.raises(UploadError):
            safe_join(directory, evil)


# ---------------------------------------------------------------------------
# HTTP: POST /screenshots/save
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch, tmp_path):
    token_path = os.path.join(tempfile.mkdtemp(prefix="arrow_up_tok_"), "token")
    monkeypatch.setitem(srv.app.config, "TOKEN_MANAGER", TokenManager(path=token_path))
    monkeypatch.setitem(srv.app.config, "CAPABILITIES", CapabilityManager())
    monkeypatch.setattr(srv, "SCREENSHOTS_DIR", str(tmp_path))
    return srv.app.test_client()


def _headers():
    token = srv.app.config["TOKEN_MANAGER"].get_or_create()
    return {"Authorization": f"Bearer {token}"}


def test_save_requires_auth(client):
    resp = client.post("/screenshots/save", json={"image": base64.b64encode(png_bytes()).decode()})
    assert resp.status_code == 401


def test_save_happy_path_writes_unique_file(client, tmp_path):
    payload = base64.b64encode(png_bytes()).decode()
    first = client.post("/screenshots/save", json={"image": payload}, headers=_headers())
    second = client.post("/screenshots/save", json={"image": payload}, headers=_headers())
    assert first.status_code == 200
    assert second.status_code == 200
    body1, body2 = first.get_json(), second.get_json()
    assert body1["filename"] != body2["filename"]
    assert os.path.isfile(os.path.join(str(tmp_path), body1["filename"]))
    assert body1["url"] == f"/screenshots/{body1['filename']}"
    assert body1["format"] == "png"


def test_save_rejects_missing_image(client):
    resp = client.post("/screenshots/save", json={}, headers=_headers())
    assert resp.status_code == 400


def test_save_rejects_garbage_base64(client):
    resp = client.post("/screenshots/save", json={"image": "@@@not-base64@@@"}, headers=_headers())
    assert resp.status_code == 400
    assert "base64" in resp.get_json()["error"].lower()


def test_save_rejects_non_image_content(client, tmp_path):
    payload = base64.b64encode(b"#!/bin/sh\necho pwned\n").decode()
    resp = client.post("/screenshots/save", json={"image": payload}, headers=_headers())
    assert resp.status_code == 415
    assert os.listdir(str(tmp_path)) == []


def test_save_rejects_when_capability_disabled(client):
    from arrow.server.security import Capability

    srv.app.config["CAPABILITIES"].disable(Capability.READ_SCREENSHOT)
    try:
        payload = base64.b64encode(png_bytes()).decode()
        resp = client.post("/screenshots/save", json={"image": payload}, headers=_headers())
        assert resp.status_code == 403
        assert "disabled" in resp.get_json()["error"]
    finally:
        srv.app.config["CAPABILITIES"].enable(Capability.READ_SCREENSHOT)


# ---------------------------------------------------------------------------
# End-to-end save
# ---------------------------------------------------------------------------


def test_save_decoded_upload_end_to_end(tmp_path):
    payload = base64.b64encode(png_bytes(size=(32, 32))).decode()
    filename, path, fmt = save_decoded_upload(payload, str(tmp_path), "capture")
    assert fmt == "PNG"
    assert os.path.isfile(path)
    assert filename.endswith(".png")
