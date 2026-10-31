"""Authenticated loopback MCP (stateless JSON HTTP) and capture REST reads."""
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request, send_file

from arrow.mcp.server import MCPServer
from arrow.mcp.tools import ToolError
from arrow.server.security import LOCALHOST_HOSTS, Capability, is_localhost_origin, parse_bearer


def register_mcp_http(app):
    api = Blueprint('arrow_context', __name__)

    def authorized(function):
        @wraps(function)
        def check(*args, **kwargs):
            if (urlparse(request.host_url).hostname not in LOCALHOST_HOSTS
                    or not is_localhost_origin(request.headers.get('Origin'))):
                return jsonify(error='Local context origin/host not allowed'), 403
            if not current_app.config['TOKEN_MANAGER'].verify(parse_bearer(request.headers.get('Authorization'))):
                return jsonify(error='Local connection authorization required'), 401
            if not current_app.config['CAPABILITIES'].is_enabled(Capability.READ_CAPTURE_CONTEXT):
                return jsonify(error='Capture context access is disabled'), 403
            return function(*args, **kwargs)
        return check

    def server():
        return current_app.config.get('MCP_SERVER_FACTORY', MCPServer)()

    @api.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @api.post('/mcp')
    @authorized
    def mcp():
        if request.mimetype != 'application/json':
            return jsonify(error='Use application/json'), 415
        message = request.get_json(silent=True)
        if not isinstance(message, dict):
            return jsonify(error='Expected one JSON-RPC object'), 400
        params = message.get('params')
        if (isinstance(params, dict) and params.get('name') == 'arrow_look'
                and not current_app.config['CAPABILITIES'].is_enabled(Capability.READ_SCREENSHOT)):
            return jsonify(error='Live screenshot access is disabled'), 403
        reply = server().handle(message)
        if reply is None:
            return '', 202
        return jsonify(reply)

    @api.get('/api/captures')
    @authorized
    def captures():
        try:
            limit = int(request.args.get('limit', 20))
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            return jsonify(error='limit must be between 1 and 100'), 400
        return jsonify(server().repo.list_captures(limit))

    @api.get('/api/captures/<capture_id>')
    @authorized
    def capture(capture_id):
        try:
            return jsonify(server().tools.call('arrow_get_capture_bundle', {'capture_id': capture_id}))
        except (ToolError, LookupError):
            return jsonify(error='Capture not found'), 404

    @api.get('/api/captures/<capture_id>/image')
    @authorized
    def image(capture_id):
        try:
            value = server().tools.call('arrow_get_capture_bundle', {'capture_id': capture_id})
        except (ToolError, LookupError):
            return jsonify(error='Capture not found'), 404
        if not value['annotated_path']:
            return jsonify(error='Capture has no saved image'), 404
        return send_file(value['annotated_path'], mimetype='image/png', conditional=False)

    app.register_blueprint(api)
