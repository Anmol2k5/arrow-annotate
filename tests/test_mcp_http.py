import pytest
from flask import Flask
from PIL import Image

from arrow.mcp.server import MCPServer
from arrow.server.security import Capability, CapabilityManager, TokenManager
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord


@pytest.fixture
def api(tmp_path, monkeypatch):
    from arrow.mcp.http import register_mcp_http
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    db = str(tmp_path / 'context.db')
    image = tmp_path / 'saved.png'
    Image.new('RGB', (12, 10), 'red').save(image)
    CaptureStore(db).add(CaptureRecord(id='one', timestamp='now', screenshot_path=str(image),
        annotation_text='Move this control', original_voice_transcript='original words',
        capture_context={'window_context': {'source': {'text': 'Full window text'}}},
        change_request={'capture_id': 'one', 'raw_user_request': 'Move this control',
                        'assets': {'annotated': str(image)}}))
    app = Flask(__name__)
    tokens = TokenManager(str(tmp_path / 'local-token'))
    app.config.update(TOKEN_MANAGER=tokens, CAPABILITIES=CapabilityManager(),
                      MCP_SERVER_FACTORY=lambda: MCPServer(db))
    register_mcp_http(app)
    return app.test_client(), {'Authorization': 'Bearer ' + tokens.get_or_create()}, app


def test_shared_endpoint_supports_mcp_initialization_and_full_saved_capture(api):
    client, auth, _ = api
    response = client.post('/mcp', headers=auth, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}})
    assert response.status_code == 200
    assert response.json['result']['protocolVersion'] == '2025-03-26'
    notice = client.post('/mcp', headers=auth, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert notice.status_code == 202 and not notice.data
    capture = client.post('/mcp', headers=auth, json={
        'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': 'arrow_get_capture_bundle', 'arguments': {'capture_id': 'one'}}})
    parts = capture.json['result']['content']
    assert [part['type'] for part in parts] == ['text', 'image']
    assert 'Full window text' in parts[0]['text'] and 'original words' in parts[0]['text']
    assert capture.headers['Cache-Control'] == 'no-store'


def test_rest_and_mcp_read_the_same_capture_and_image(api):
    client, auth, _ = api
    assert client.get('/api/captures', headers=auth).json[0]['capture_id'] == 'one'
    data = client.get('/api/captures/one', headers=auth).json
    assert data['metadata']['current_instruction'] == 'Move this control'
    image = client.get('/api/captures/one/image', headers=auth)
    assert image.status_code == 200 and image.data.startswith(b'\x89PNG')
    assert client.get('/api/captures/missing', headers=auth).status_code == 404


def test_context_endpoint_rejects_other_websites_hosts_and_missing_local_token(api):
    client, auth, _ = api
    assert client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}).status_code == 401
    assert client.get('/api/captures', headers={**auth, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/captures', headers={**auth, 'Host': 'evil.example'}).status_code == 403


def test_mcp_respects_disabled_context_and_screenshot_capabilities(api):
    client, auth, app = api
    app.config['CAPABILITIES'] = CapabilityManager(enabled=[])
    assert client.get('/api/captures', headers=auth).status_code == 403
    assert client.post('/mcp', headers=auth, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).status_code == 403
    app.config['CAPABILITIES'] = CapabilityManager(enabled=[Capability.READ_CAPTURE_CONTEXT])
    assert client.post('/mcp', headers=auth, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': 'arrow_look', 'arguments': {}}}).status_code == 403


def test_http_mcp_reports_malformed_messages_without_a_server_error(api):
    client, auth, _ = api
    assert client.post('/mcp', headers=auth, data='not JSON').status_code == 415
    assert client.post('/mcp', headers=auth, json=[]).status_code == 400
    response = client.post('/mcp', headers=auth, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': []})
    assert response.status_code == 200
    assert response.json['error']['code'] == -32602
