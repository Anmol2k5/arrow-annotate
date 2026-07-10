import json
import os
import subprocess

import pytest

from arrow.context.repo_context import collect_repository_context


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _have_git():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def test_none_path():
    ctx = collect_repository_context(None)
    assert ctx.repository_root is None
    assert ctx.current_branch is None


def test_route_and_dev_server_from_url():
    ctx = collect_repository_context(None, page_url="http://localhost:3000/pricing?x=1")
    assert ctx.active_route == "/pricing"
    assert ctx.dev_server_url == "http://localhost:3000"


def test_route_from_root_url():
    ctx = collect_repository_context(None, page_url="http://localhost:5173/")
    assert ctx.active_route == "/"


def test_non_local_url_no_dev_server():
    ctx = collect_repository_context(None, page_url="https://example.com/pricing")
    assert ctx.active_route == "/pricing"
    assert ctx.dev_server_url is None


def test_framework_and_package_manager_detection(tmp_path):
    root = str(tmp_path)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"dependencies": {"next": "14.0.0", "react": "18.0.0"}}, f)
    with open(os.path.join(root, "pnpm-lock.yaml"), "w", encoding="utf-8") as f:
        f.write("")
    ctx = collect_repository_context(root)
    assert ctx.framework == "next"
    assert ctx.package_manager == "pnpm"


@pytest.mark.skipif(not _have_git(), reason="git not available")
def test_git_repository_context(tmp_path):
    root = str(tmp_path)
    _git(["init"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["checkout", "-b", "main"], root)
    with open(os.path.join(root, "file.txt"), "w", encoding="utf-8") as f:
        f.write("hello")
    _git(["add", "."], root)
    _git(["commit", "-m", "init"], root)

    ctx = collect_repository_context(root)
    assert ctx.repository_root is not None
    assert ctx.current_branch == "main"
    assert ctx.current_commit is not None
    assert len(ctx.current_commit) == 40
    assert ctx.dirty is False

    with open(os.path.join(root, "file.txt"), "w", encoding="utf-8") as f:
        f.write("changed")
    ctx2 = collect_repository_context(root)
    assert ctx2.dirty is True
