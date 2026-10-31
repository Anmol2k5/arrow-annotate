"""Update checks never trust arbitrary release links or perform background work."""

import json

import pytest
import requests

from arrow.core import updates


def release(**changes):
    return {
        "tag_name": "v0.4.0",
        "html_url": "https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0",
        "draft": False,
        "prerelease": False,
        "assets": [{"browser_download_url": "https://github.com/Anmol2k5/arrow-annotate/releases/download/v0.4.0/Arrow-Setup.exe"}],
        **changes,
    }


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        yield self.body


def mock_release(monkeypatch, value):
    response = Response(json.dumps(value).encode())
    monkeypatch.setattr(updates.requests, "get", lambda *a, **kw: response)
    return response


def test_explicit_check_uses_fixed_endpoint_timeout_and_no_redirects(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(json.dumps(release()).encode())

    monkeypatch.setattr(updates.requests, "get", get)
    assert not calls
    result = updates.check_for_update("0.3.0")
    assert result == updates.UpdateResult("0.4.0", release()["html_url"], True)
    assert calls[0][0] == updates.LATEST_RELEASE_API
    assert calls[0][1]["timeout"] == (3.0, 7.0)
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("current,available", [("0.4.0", False), ("0.5.0", False), ("0.3.99", True), ("0.10.0", False)])
def test_numeric_versions_only_report_newer_releases(monkeypatch, current, available):
    mock_release(monkeypatch, release())
    assert updates.check_for_update(current).available is available


@pytest.mark.parametrize("url", [
    "http://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0",
    "https://github.com.evil.test/Anmol2k5/arrow-annotate/releases/tag/v0.4.0",
    "https://github.com@evil.test/Anmol2k5/arrow-annotate/releases/tag/v0.4.0",
    "https://github.com/attacker/arrow-annotate/releases/tag/v0.4.0",
    "https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0?next=evil",
    "https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0#evil",
    "https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0/extra",
    "javascript:alert(1)", "https://github.com:443/Anmol2k5/arrow-annotate/releases/tag/v0.4.0",
])
def test_rejects_untrusted_release_urls(monkeypatch, url):
    mock_release(monkeypatch, release(html_url=url))
    with pytest.raises(updates.UpdateCheckError, match="unexpected release"):
        updates.check_for_update("0.3.0")


@pytest.mark.parametrize("url", [
    "https://evil.test/setup.exe",
    "https://github.com/other/repo/releases/download/v0.4.0/setup.exe",
    "https://github.com/Anmol2k5/arrow-annotate/releases/download/v0.4.0/../setup.exe",
    "https://github.com/Anmol2k5/arrow-annotate/releases/download/v0.4.0/%2fsetup.exe",
    "https://github.com/Anmol2k5/arrow-annotate/releases/download/v0.4.0/setup.exe?redirect=evil",
])
def test_rejects_untrusted_download_urls(monkeypatch, url):
    mock_release(monkeypatch, release(assets=[{"browser_download_url": url}]))
    with pytest.raises(updates.UpdateCheckError):
        updates.check_for_update("0.3.0")


@pytest.mark.parametrize("value", [
    {}, [], None, release(draft=True), release(prerelease=True), release(draft=0),
    release(tag_name="v1.0.0-beta"), release(tag_name="1.0.0"), release(tag_name="v01.2.3"),
    release(assets=None), release(assets=[None]), release(tag_name="v1.2"), release(prerelease="false"),
])
def test_rejects_malformed_and_unstable_releases(monkeypatch, value):
    mock_release(monkeypatch, value)
    with pytest.raises(updates.UpdateCheckError):
        updates.check_for_update("0.3.0")


@pytest.mark.parametrize("status,message", [(404, "No public stable"), (403, "limited"), (429, "limited"), (500, "connection"), (302, "connection")])
def test_http_failures_are_actionable(monkeypatch, status, message):
    response = mock_release(monkeypatch, release())
    response.status_code = status
    with pytest.raises(updates.UpdateCheckError, match=message):
        updates.check_for_update("0.3.0")


def test_network_failure_is_actionable(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout("internal diagnostic")

    monkeypatch.setattr(updates.requests, "get", fail)
    with pytest.raises(updates.UpdateCheckError, match="internet connection"):
        updates.check_for_update("0.3.0")


@pytest.mark.parametrize("body", [b"not-json", b"x" * 1_000_001])
def test_invalid_or_oversized_response_is_rejected(monkeypatch, body):
    monkeypatch.setattr(updates.requests, "get", lambda *a, **kw: Response(body))
    with pytest.raises(updates.UpdateCheckError, match="response"):
        updates.check_for_update("0.3.0")


def test_invalid_current_version_does_not_make_request(monkeypatch):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Invalid version must not make a network request")

    monkeypatch.setattr(updates.requests, "get", unexpected_request)
    with pytest.raises(updates.UpdateCheckError, match="installed version"):
        updates.check_for_update("v0.3.0")
