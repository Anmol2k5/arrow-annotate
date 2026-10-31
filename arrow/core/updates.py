"""Explicit, read-only update checks against the official GitHub release feed."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

REPOSITORY = "Anmol2k5/arrow-annotate"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_TIMEOUT = (3.0, 7.0)
_MAX_RESPONSE_BYTES = 1_000_000
_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", re.ASCII)


@dataclass(frozen=True)
class UpdateResult:
    version: str
    url: str
    available: bool


class UpdateCheckError(RuntimeError):
    """A user-facing failure that can be retried without changing app settings."""


def _version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError("Expected a stable numeric version (for example 1.2.3).")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _official_url(value: object, path: str, *, download: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        return False
    if download:
        # GitHub assets occupy a single filename component; reject encoded separators,
        # traversal, credentials, alternate repositories and external redirect URLs.
        filename = parsed.path.removeprefix(path)
        return parsed.path.startswith(path) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename))
    return parsed.path == path


def check_for_update(current_version: str) -> UpdateResult:
    """Check once on user request; never download, execute, or open a browser.

    The caller should run this blocking request outside the GUI thread and offer
    ``url`` as an explicit browser action only after a successful result.
    """
    try:
        current = _version(current_version)
    except ValueError as exc:
        raise UpdateCheckError("The installed version is invalid. Reinstall from the official releases page.") from exc
    try:
        with requests.get(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Arrow-Annotate-update-check"},
            timeout=_TIMEOUT,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code == 404:
                raise UpdateCheckError("No public stable release is available yet. Try again later.")
            if response.status_code in (403, 429):
                raise UpdateCheckError("GitHub limited update requests. Wait a few minutes and try again.")
            if response.status_code != 200:
                raise UpdateCheckError("GitHub could not check for updates. Check your connection and try again.")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise UpdateCheckError("GitHub returned an unexpected update response. Try again later.")
            release = json.loads(body)
    except requests.RequestException as exc:
        raise UpdateCheckError("Could not reach GitHub. Check your internet connection and try again.") from exc
    except (ValueError, UnicodeError) as exc:
        raise UpdateCheckError("GitHub returned an invalid update response. Try again later.") from exc

    try:
        if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
            raise ValueError("Not a public stable release")
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith("v"):
            raise ValueError("Invalid release tag")
        latest = _version(tag[1:])
        url = release.get("html_url")
        if not isinstance(url, str) or not _official_url(url, f"/{REPOSITORY}/releases/tag/{tag}"):
            raise ValueError("Untrusted release URL")
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("Invalid release assets")
        for asset in assets:
            if not isinstance(asset, dict) or not _official_url(
                asset.get("browser_download_url"), f"/{REPOSITORY}/releases/download/{tag}/", download=True
            ):
                raise ValueError("Untrusted download URL")
    except (ValueError, TypeError) as exc:
        raise UpdateCheckError("GitHub returned unexpected release information. Visit the official releases page or retry later.") from exc
    return UpdateResult(version=tag[1:], url=url, available=latest > current)
