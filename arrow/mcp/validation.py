"""Private, synthetic-only MCP endpoint for an explicitly requested live check."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from arrow.mcp.server import MCPServer, _error


class ValidationServer:
    """Delegate the one permitted capture call to the production MCP server."""

    def __init__(self, fixture_dir, receipt_path):
        self.directory = Path(fixture_dir).resolve()
        self.receipt_path = Path(receipt_path).resolve()
        if not self.receipt_path.is_relative_to(self.directory):
            raise ValueError('Receipt must be inside the synthetic fixture directory')
        manifest = json.loads((self.directory / 'fixture.json').read_text(encoding='utf-8'))
        self.capture_id = manifest['capture_id']
        self.session_nonce = manifest['session_nonce']
        # Never use a caller's normal Arrow database, even when its environment
        # points there. This endpoint is only for runner-generated fixtures.
        os.environ['ARROW_HOME'] = str(self.directory / 'home')
        os.environ['ARROW_DB_PATH'] = str(self.directory / 'captures.db')
        self.server = MCPServer(db_path=str(self.directory / 'captures.db'))

    def handle(self, request):
        if not isinstance(request, dict):
            return _error(None, -32600, 'Invalid request')
        method = request.get('method')
        if method in ('initialize', 'ping', 'notifications/initialized', 'notifications/cancelled'):
            response = self.server.handle(request)
            if method == 'initialize' and response and 'result' in response:
                response['result']['capabilities'] = {'tools': {}}
            return response
        if method == 'tools/list':
            response = self.server.handle(request)
            if response and 'result' in response:
                response['result']['tools'] = [schema for schema in response['result']['tools']
                                                if schema['name'] == 'arrow_get_capture_bundle']
                response['result']['tools'][0]['inputSchema']['required'] = ['capture_id']
            return response
        params = request.get('params', {})
        if (method == 'tools/call' and isinstance(params, dict)
                and params.get('name') == 'arrow_get_capture_bundle'
                and params.get('arguments') == {'capture_id': self.capture_id}):
            return self.server.handle(request)
        if 'id' not in request:
            return None
        return _error(request.get('id'), -32601, 'Not available in synthetic validation')

    def record_response(self, request, response):
        """Record only after the response has been written and flushed to stdio."""
        if not isinstance(request, dict):
            return
        params = request.get('params', {})
        if (request.get('method') != 'tools/call' or not isinstance(params, dict)
                or params.get('arguments') != {'capture_id': self.capture_id}
                or params.get('name') != 'arrow_get_capture_bundle' or not response):
            return
        result = response.get('result', {})
        if result.get('isError'):
            return
        content = result.get('content', [])
        images = [part for part in content if part.get('type') == 'image' and part.get('mimeType') == 'image/png']
        texts = [part for part in content if part.get('type') == 'text']
        if len(images) != 1 or len(texts) != 1:
            return
        metadata = json.loads(texts[0]['text']).get('metadata', {})
        if metadata.get('capture_id') != self.capture_id:
            return
        receipt = {'capture_id': self.capture_id, 'session_nonce': self.session_nonce,
                   'request_id': request['id'],
                   'image_sha256': hashlib.sha256(base64.b64decode(images[0]['data'], validate=True)).hexdigest()}
        with self.receipt_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(receipt) + '\n')

    def serve_stdio(self):
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = _error(None, -32700, 'Parse error')
                request = {}
            else:
                response = self.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + '\n')
                sys.stdout.flush()
                self.record_response(request, response)


def serve_validation(fixture_dir, receipt_path):
    ValidationServer(fixture_dir, receipt_path).serve_stdio()


if __name__ == '__main__':  # convenient subprocess protocol tests
    serve_validation(*sys.argv[1:])
