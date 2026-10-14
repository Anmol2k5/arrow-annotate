from pathlib import Path

from arrow.capture.context_file import build_context_md, mirror_latest
from arrow.mcp.tools import ArrowTools
from arrow.storage.repository import Repository


def test_latest_mirror_and_mcp_honor_arrow_home(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'state'))
    screenshot = tmp_path / 'capture.png'
    screenshot.write_bytes(b'image')
    directory = mirror_latest(str(screenshot), '# Capture', 'c1')
    assert Path(directory) == tmp_path / 'state' / 'latest'
    assert ArrowTools(Repository(str(tmp_path / 'db'))).call('arrow_get_context_md') == '# Capture'


def test_context_markdown_uses_actual_repository_schema():
    result = build_context_md('c1', 'Move button', repository={
        'repository_root': '/work/project', 'current_branch': 'feature', 'framework': 'react'})
    assert '/work/project' in result
    assert 'feature' in result
