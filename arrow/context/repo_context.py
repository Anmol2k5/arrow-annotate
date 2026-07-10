"""
Repository context collection (Phase 7).

Gathers facts about the repository that a coding agent needs in order to act on a
capture: repository root, current branch, commit, dirty state, detected
framework, package manager, development-server URL and the active route.

All values are observed from the filesystem or git. Nothing is fabricated: when a
fact cannot be determined it is left as ``None``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel

log = logging.getLogger("bluely.repo_context")


class RepositoryContext(BaseModel):
    """Observed repository context for a capture."""

    repository_root: Optional[str] = None
    current_branch: Optional[str] = None
    current_commit: Optional[str] = None
    dirty: Optional[bool] = None
    framework: Optional[str] = None
    package_manager: Optional[str] = None
    dev_server_url: Optional[str] = None
    active_route: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("git %s failed: %s", " ".join(args), e)
        return None
    if result.returncode != 0:
        log.debug("git %s returned %d: %s", " ".join(args), result.returncode, result.stderr.strip())
        return None
    return result.stdout.strip()


def _git_root(path: str) -> Optional[str]:
    root = _run_git(["rev-parse", "--show-toplevel"], path)
    if root:
        return os.path.normpath(root)
    return None


def _git_branch(root: str) -> Optional[str]:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if branch and branch != "HEAD":
        return branch
    # Detached HEAD — report None rather than a fabricated branch name.
    return None if branch == "HEAD" else branch


def _git_commit(root: str) -> Optional[str]:
    return _run_git(["rev-parse", "HEAD"], root)


def _git_dirty(root: str) -> Optional[bool]:
    status = _run_git(["status", "--porcelain"], root)
    if status is None:
        return None
    return bool(status.strip())


# ---------------------------------------------------------------------------
# Framework / package-manager detection
# ---------------------------------------------------------------------------

def _detect_package_manager(root: str) -> Optional[str]:
    lockfiles = [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
        ("poetry.lock", "poetry"),
        ("uv.lock", "uv"),
        ("Pipfile.lock", "pipenv"),
    ]
    for filename, manager in lockfiles:
        if os.path.isfile(os.path.join(root, filename)):
            return manager
    if os.path.isfile(os.path.join(root, "package.json")):
        return "npm"
    if os.path.isfile(os.path.join(root, "pyproject.toml")):
        return "pip"
    return None


def _load_package_json(root: str) -> Optional[dict]:
    path = os.path.join(root, "package.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Could not read package.json: %s", e)
    return None


def _detect_framework(root: str, package_json: Optional[dict]) -> Optional[str]:
    if package_json:
        deps: dict[str, str] = {}
        deps.update(package_json.get("dependencies", {}) or {})
        deps.update(package_json.get("devDependencies", {}) or {})
        # Order matters: most specific first.
        for name, framework in (
            ("next", "next"),
            ("@remix-run/react", "remix"),
            ("nuxt", "nuxt"),
            ("@angular/core", "angular"),
            ("svelte", "svelte"),
            ("solid-js", "solid"),
            ("vue", "vue"),
            ("react", "react"),
        ):
            if name in deps:
                return framework
    # Python frameworks
    for filename, framework in (
        ("manage.py", "django"),
    ):
        if os.path.isfile(os.path.join(root, filename)):
            return framework
    return None


def _detect_dev_server_url(package_json: Optional[dict], page_url: Optional[str]) -> Optional[str]:
    if page_url:
        parsed = urlparse(page_url)
        if parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            netloc = parsed.netloc
            return f"{parsed.scheme}://{netloc}"
    return None


def _route_from_url(page_url: Optional[str]) -> Optional[str]:
    if not page_url:
        return None
    parsed = urlparse(page_url)
    if not parsed.scheme:
        return None
    route = parsed.path or "/"
    return route


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_repository_context(
    path: Optional[str],
    page_url: Optional[str] = None,
) -> RepositoryContext:
    """Collect repository context rooted at ``path``.

    Args:
        path: A directory inside the repository (e.g. the selected project). When
            ``None`` or not a git repository, git-derived fields stay ``None``.
        page_url: Optional page URL used to infer the dev-server URL and route.

    Returns:
        A :class:`RepositoryContext` with only observed facts populated.
    """
    ctx = RepositoryContext()

    ctx.active_route = _route_from_url(page_url)

    if path and os.path.isdir(path):
        norm_path = os.path.normpath(path)
        root = _git_root(path)
        if root is None and os.path.isdir(os.path.join(norm_path, ".git")):
            root = norm_path
        ctx.repository_root = root

        if root:
            ctx.current_branch = _git_branch(root)
            ctx.current_commit = _git_commit(root)
            ctx.dirty = _git_dirty(root)

        # Framework / package-manager detection works even without git.
        scan_root = root or norm_path
        package_json = _load_package_json(scan_root)
        ctx.package_manager = _detect_package_manager(scan_root)
        ctx.framework = _detect_framework(scan_root, package_json)
        ctx.dev_server_url = _detect_dev_server_url(package_json, page_url)
    else:
        ctx.dev_server_url = _detect_dev_server_url(None, page_url)

    return ctx


__all__ = ["RepositoryContext", "collect_repository_context"]
