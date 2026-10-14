import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from arrow.server import server as srv
from arrow.server.security import Capability, CapabilityManager, TokenManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    token_manager = TokenManager(str(tmp_path / 'token'))
    monkeypatch.setitem(srv.app.config, 'TOKEN_MANAGER', token_manager)
    monkeypatch.setitem(srv.app.config, 'CAPABILITIES', CapabilityManager(enabled=list(Capability)))
    monkeypatch.setitem(srv.app.config, 'WS_BRIDGE', SimpleNamespace(connected=True, inspect=lambda *a: {}))
    monkeypatch.setattr(srv, 'SCREENSHOTS_DIR', str(tmp_path / 'shots'))
    client = srv.app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = 'Bearer ' + token_manager.get_or_create()
    return client


@pytest.mark.parametrize('endpoint,payload', [
    ('/resolve', ['query']), ('/resolve', {'query': 5}),
    ('/execute', {'type': []}), ('/execute/batch', {'actions': [None]}),
    ('/inspect', {'x': 'bad', 'y': 3}),
    ('/highlight/resolve', {'rect': {'x': 0, 'y': 0, 'width': -1, 'height': 1}}),
    ('/highlight/capture', {'rect': 'bad'}),
    ('/highlight/execute', {'rect': {'x': 0, 'y': 0, 'width': 1, 'height': 1}, 'action': []}),
])
def test_invalid_payloads_return_client_error(client, endpoint, payload):
    assert client.post(endpoint, json=payload).status_code == 400


@pytest.mark.parametrize('image', ['not-base64!', base64.b64encode(b'not an image').decode()])
def test_invalid_screenshot_upload_does_not_create_asset(client, image):
    assert client.post('/screenshots/save', json={'image': image}).status_code == 400


def test_repeated_uploads_do_not_overwrite_each_other(client):
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(buf, 'PNG')
    payload = {'image': base64.b64encode(buf.getvalue()).decode()}
    first = client.post('/screenshots/save', json=payload)
    second = client.post('/screenshots/save', json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json['filename'] != second.json['filename']


def test_highlight_capture_uses_global_region_on_offset_monitor(client, monkeypatch):
    class FakeMSS:
        monitors = [{'left': 100, 'top': 200, 'width': 20, 'height': 20}] * 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, region):
            size = (region['width'], region['height'])
            return SimpleNamespace(size=size, rgb=bytes([255, 0, 0]) * size[0] * size[1])

    import mss
    monkeypatch.setattr(mss, 'mss', FakeMSS)
    monkeypatch.setattr(srv, 'HighlightResolver', lambda **kwargs: SimpleNamespace(
        resolve=lambda **kwargs: SimpleNamespace(to_dict=lambda: {})))
    response = client.post('/highlight/capture', json={
        'rect': {'x': 105, 'y': 205, 'width': 5, 'height': 5}})
    assert response.status_code == 200
    with Image.open(response.json['path']) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
