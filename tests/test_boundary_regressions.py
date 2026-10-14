"""Boundary failures missed by the original happy-path tests."""

import json
import subprocess
import sys

import pytest
from PIL import Image

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation
from arrow.server.security import TokenManager


@pytest.mark.parametrize('token', ['é', '\ud800'])
def test_non_ascii_bearer_is_rejected_without_crashing(tmp_path, token):
    assert TokenManager(str(tmp_path / 'token')).verify(token) is False


def test_source_crop_intersects_original_rectangle_at_left_edge():
    image = Image.new('RGB', (100, 100))
    mapper = CoordinateMapper([ScreenInfo('primary', (0, 0, 100, 100), 1)])
    annotation = Annotation(id='a', type='rectangle', role='source',
                            geometry={'x': -10, 'y': 10, 'width': 20, 'height': 20})
    crop, _, _ = ScreenshotService().generate_crops(image, [annotation], mapper)
    assert crop.size == (10, 20)


def test_mcp_survives_non_object_requests_and_invalid_params(tmp_path):
    import os
    env = {**os.environ, 'ARROW_DB_PATH': str(tmp_path / 'mcp.db')}
    requests = [[], {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': []},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}]
    proc = subprocess.run([sys.executable, '-m', 'arrow.mcp.server'],
                          input=''.join(json.dumps(r) + '\n' for r in requests),
                          capture_output=True, text=True, env=env, timeout=10)
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert responses[0]['error']['code'] == -32600
    assert responses[1]['error']['code'] == -32602
    assert responses[2] == {'jsonrpc': '2.0', 'id': 2, 'result': {}}


@pytest.mark.parametrize('method', ['ping', 'tools/list', 'resources/list'])
def test_mcp_notifications_have_no_response(tmp_path, method):
    from arrow.mcp.server import MCPServer
    assert MCPServer(db_path=str(tmp_path / 'mcp.db')).handle(
        {'jsonrpc': '2.0', 'method': method}) is None


def test_very_thin_screenshot_downscales_to_valid_dimensions():
    assert ScreenshotService.downscale_for_agent(Image.new('RGB', (2000, 1))).size == (1568, 1)


def test_padding_instruction_is_not_classified_as_adding_an_element():
    from arrow.intent.compiler import CompilerInput, IntentCompiler
    from arrow.intent.schemas import Intent
    request = IntentCompiler().compile(CompilerInput(raw_instruction='Increase padding'))
    assert request.normalized_intent == Intent.CHANGE_SPACING


def test_voice_instruction_is_not_duplicated_in_compiled_request():
    from arrow.intent.compiler import CompilerInput, IntentCompiler
    request = IntentCompiler().compile(CompilerInput(
        raw_instruction='Make it wider', voice_transcript='Make it wider'))
    assert request.raw_user_request == 'Make it wider'


def test_move_and_restyle_retains_both_requested_changes():
    from arrow.intent.compiler import CompilerInput, IntentCompiler
    request = IntentCompiler().compile(CompilerInput(raw_instruction='Move this and change the background'))
    assert {c.operation for c in request.requested_changes} == {'move', 'restyle'}


@pytest.mark.parametrize('path_kind', ['absolute', 'traversal', 'symlink'])
def test_source_metadata_cannot_map_files_outside_selected_repository(tmp_path, path_kind):
    from arrow.context.source_mapper import ElementContext, SourceMapper
    root = tmp_path / 'repo'
    root.mkdir()
    outside = tmp_path / 'Outside.tsx'
    outside.write_text('export default function Outside() { return null; }')
    if path_kind == 'symlink':
        (root / 'linked.tsx').symlink_to(outside)
        file_name = 'linked.tsx'
    elif path_kind == 'traversal':
        file_name = '../Outside.tsx'
    else:
        file_name = str(outside)
    mapping = SourceMapper(str(root)).map(ElementContext(
        react_source={'fileName': file_name, 'lineNumber': 1}))
    assert mapping.resolved is False
    assert mapping.source_file is None


def test_browser_highlight_resolver_accepts_real_bridge_response(monkeypatch):
    from arrow.context import highlight_resolver as module

    class Bridge:
        connected = True

        def inspect(self, x, y, timeout):
            return {'type': 'inspect_result', 'pageUrl': 'https://example.com/page', 'text': 'Buy'}

    monkeypatch.setattr(module, '_get_foreground_window_info',
                        lambda: {'exe_name': 'chrome.exe', 'title': 'Page - Google Chrome'})
    monkeypatch.setattr(module, '_get_uia_info_at_point', lambda *a: None)
    result = module.HighlightResolver(Bridge()).resolve((10, 20, 30, 40))
    assert result.source_url == 'https://example.com/page'
    assert result.selected_text == 'Buy'


def test_stale_capture_worker_cannot_transition_new_session():
    from arrow.capture.session import CaptureState, SessionManager
    manager = SessionManager()
    old = manager.start_session()
    manager.transition_to(CaptureState.ANNOTATING)
    new = manager.start_session()
    with pytest.raises(ValueError, match='no longer active'):
        manager.transition_to(CaptureState.FAILED, capture_id=old.capture_id)
    assert new.state == CaptureState.STARTING
