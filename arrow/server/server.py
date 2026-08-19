import asyncio
import base64
import ctypes
import datetime
import io
import json
import logging
import os
import platform
import socket
import threading
import time
from concurrent.futures import Future
from functools import wraps

import websockets
from flask import Flask, jsonify, request, send_from_directory

from arrow.capture.screenshot_service import find_mss_monitor
from arrow.context.highlight_resolver import HighlightResolver
from arrow.context.hybrid_pointer import find_target
from arrow.server.security import (
    MAX_REQUEST_BYTES,
    Capability,
    CapabilityManager,
    TokenManager,
    is_localhost_origin,
    parse_bearer,
)

log = logging.getLogger("arrow.server")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREENSHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")


# ---------------------------------------------------------------------------
# OS Control helpers  (Windows via ctypes)
# ---------------------------------------------------------------------------

class OSController:
    """Execute physical actions on the OS via Win32 API."""

    # Virtual-key codes
    _VK = {
        "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
        "win": 0x5B, "cmd": 0x5B, "enter": 0x0D, "tab": 0x09,
        "escape": 0x1B, "esc": 0x1B, "space": 0x20, "backspace": 0x08,
        "delete": 0x2E, "del": 0x2E, "up": 0x26, "down": 0x28,
        "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22,
    }
    for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
        _VK[_c] = ord(_c.upper())

    @classmethod
    def _key_down(cls, vk):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)

    @classmethod
    def _key_up(cls, vk):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

    @classmethod
    def click(cls, target: str = "", x: int = None, y: int = None):
        """Click at current cursor position or specified (x, y)."""
        if x is not None and y is not None:
            ctypes.windll.user32.SetCursorPos(x, y)
            time.sleep(0.05)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # down
        time.sleep(0.02)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # up
        return {"action": "click", "target": target, "x": x, "y": y}

    @classmethod
    def right_click(cls, x: int = None, y: int = None):
        if x is not None and y is not None:
            ctypes.windll.user32.SetCursorPos(x, y)
            time.sleep(0.05)
        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)  # down
        time.sleep(0.02)
        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)  # up
        return {"action": "right_click", "x": x, "y": y}

    @classmethod
    def double_click(cls, x: int = None, y: int = None):
        cls.click(x=x, y=y)
        time.sleep(0.04)
        cls.click(x=x, y=y)
        return {"action": "double_click", "x": x, "y": y}

    @classmethod
    def type(cls, target: str):
        """Type a string of text character-by-character."""
        for ch in target:
            if ch == '\n':
                cls._key_down(cls._VK['enter'])
                time.sleep(0.01)
                cls._key_up(cls._VK['enter'])
            elif ch == '\t':
                cls._key_down(cls._VK['tab'])
                time.sleep(0.01)
                cls._key_up(cls._VK['tab'])
            else:
                # SendInput for arbitrary Unicode characters
                cls._send_unicode(ch)
            time.sleep(0.02)
        return {"action": "type", "chars": len(target)}

    @classmethod
    def _send_unicode(cls, ch):
        """Send a Unicode character via SendInput."""
        PUL = ctypes.POINTER(ctypes.c_ulong)
        class KeyBdInput(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort),
                        ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", PUL)]
        class HardwareInput(ctypes.Structure):
            _fields_ = [("uMsg", ctypes.c_ulong),
                        ("wParamL", ctypes.c_short),
                        ("wParamH", ctypes.c_ushort)]
        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long),
                        ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", PUL)]
        class InputI(ctypes.Union):
            _fields_ = [("ki", KeyBdInput),
                        ("mi", MouseInput),
                        ("hi", HardwareInput)]
        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong),
                        ("ii", InputI)]

        KEYEVENTF_UNICODE = 0x0004
        INPUT_KEYBOARD = 1

        inp = Input()
        inp.type = INPUT_KEYBOARD
        inp.ii.ki.wScan = ord(ch)
        inp.ii.ki.dwFlags = KEYEVENTF_UNICODE
        inp.ii.ki.time = 0
        inp.ii.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(Input))

        inp.ii.ki.dwFlags = KEYEVENTF_UNICODE | 0x0002  # keyup
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(Input))

    @classmethod
    def hotkey(cls, target: str):
        """Execute a hotkey sequence (e.g. 'ctrl+s', 'alt+tab')."""
        keys = [k.strip().lower() for k in target.split("+")]
        vks = []
        for k in keys:
            vk = cls._VK.get(k, 0)
            if not vk:
                return {"error": f"Unknown key: {k}"}
            vks.append(vk)

        for vk in vks:
            cls._key_down(vk)
            time.sleep(0.02)
        for vk in reversed(vks):
            time.sleep(0.02)
            cls._key_up(vk)

        return {"action": "hotkey", "target": target}

    @classmethod
    def open_app(cls, target: str):
        """Open an existing file or application path.

        Security: only existing filesystem paths are opened via the OS shell
        association. Arbitrary command strings are never passed to a shell
        (no ``shell=True``); general-purpose command execution is not exposed.
        """
        try:
            if os.path.exists(target):
                os.startfile(target)  # noqa: S606 - path existence validated above
                return {"action": "openApp", "target": target}
            return {"error": "open_app only accepts existing file/application paths."}
        except Exception as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)
app.config["AGENT_NAME"] = "bluely-agent"
app.config["OS_CTRL"] = OSController()
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.config["TOKEN_MANAGER"] = TokenManager()
app.config["CAPABILITIES"] = CapabilityManager()


def require_capability(capability: Capability):
    """Decorator: enforce bearer auth, localhost origin and a capability.

    Sensitive capabilities are disabled by default, so these endpoints reject
    requests unless the user has explicitly enabled the capability AND presents
    the per-install bearer token.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_localhost_origin(request.headers.get("Origin")):
                return jsonify({"error": "Origin not allowed"}), 403
            tokens: TokenManager = app.config["TOKEN_MANAGER"]
            presented = parse_bearer(request.headers.get("Authorization"))
            if not tokens.verify(presented):
                return jsonify({"error": "Unauthorized"}), 401
            caps: CapabilityManager = app.config["CAPABILITIES"]
            if not caps.is_enabled(capability):
                return jsonify({
                    "error": f"Capability '{capability.value}' is disabled",
                    "hint": "Opt in by setting ARROW_ENABLED_CAPABILITIES="
                            f"{capability.value} before starting the server.",
                }), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "agent": app.config["AGENT_NAME"],
        "version": "1.0.0",
        "hostname": socket.gethostname(),
        "ip": socket.gethostbyname(socket.gethostname()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "status": "healthy",
        "available": True,
        "uptime": time.time() - app.config.get("start_time", time.time()),
    })


@app.route("/screenshot", methods=["GET"])
def screenshot():
    """Capture primary screen → base64 JPEG."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        from arrow.capture.coordinate_mapper import ScreenInfo
        mon = sct.monitors[1]
        screen = ScreenInfo(name="primary", geometry=(mon["left"], mon["top"], mon["width"], mon["height"]), scale=1.0)
        monitor = find_mss_monitor(sct, screen)
        img = sct.grab(monitor)
        pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")

    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=88, optimize=True)
    b64 = base64.b64encode(buffer.getvalue()).decode()

    return jsonify({
        "screenshot": b64,
        "format": "jpeg",
        "width": img.size[0],
        "height": img.size[1],
    })


@app.route("/screenshots/<path:filename>")
def serve_screenshot_file(filename):
    """Serve captured screenshot files for Agentation MCP to reference."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    return send_from_directory(SCREENSHOTS_DIR, filename)


@app.route("/screenshots/save", methods=["POST"])
def save_screenshot():
    """Save a base64-encoded screenshot and return its URL.

    Accepts: { "image": "<base64_png>", "annotation": "<optional text>" }
    Returns: { "path": "...", "url": "...", "filename": "..." }
    """
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64:
        return jsonify({"error": "image (base64) required"}), 400

    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{ts}.png"
    path = os.path.join(SCREENSHOTS_DIR, filename)

    try:
        image_data = base64.b64decode(image_b64)
        with open(path, "wb") as f:
            f.write(image_data)
    except Exception as e:
        return jsonify({"error": f"Failed to save image: {e}"}), 500

    return jsonify({
        "path": os.path.abspath(path),
        "filename": filename,
        "url": f"/screenshots/{filename}",
        "annotation": data.get("annotation", ""),
    })


def _resolve_target(action: str, target: str, x, y):
    """Auto-resolve text targets to screen coordinates via UIA + OCR.

    For click/rightclick/doubleclick actions: if the caller provides a
    text target but no explicit (x, y), run the hybrid pointer pipeline
    to find the element on screen.  Returns (x, y, resolved_info) where
    resolved_info is a dict with resolution metadata, or None.
    """
    POSITIONAL_ACTIONS = {"click", "rightclick", "doubleclick"}
    if action not in POSITIONAL_ACTIONS:
        return x, y, None
    if x is not None and y is not None:
        return x, y, None  # already have coordinates
    if not target:
        return x, y, None  # nothing to resolve

    hit = find_target(target)
    if hit is None:
        return None, None, {"error": f"Could not resolve target: {target}"}

    return hit.x, hit.y, {
        "resolved": True,
        "source": hit.source,
        "label": hit.label,
        "confidence": round(hit.confidence, 3),
        "bbox": {"left": hit.bbox[0], "top": hit.bbox[1],
                 "right": hit.bbox[2], "bottom": hit.bbox[3]},
    }


@app.route("/resolve", methods=["POST"])
def resolve():
    """Resolve a text query to screen coordinates via UIA + OCR.

    Accepts: { "query": "Save button" }
    Returns: { "status": "ok", "target": { ... } } or error.
    """
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query required"}), 400

    hit = find_target(query)
    if hit is None:
        return jsonify({"error": f"No element found matching: {query}",
                        "status": "not_found"}), 404

    return jsonify({
        "status": "ok",
        "target": {
            "x": hit.x,
            "y": hit.y,
            "label": hit.label,
            "source": hit.source,
            "confidence": round(hit.confidence, 3),
            "bbox": {"left": hit.bbox[0], "top": hit.bbox[1],
                     "right": hit.bbox[2], "bottom": hit.bbox[3]},
        },
    })


@app.route("/execute", methods=["POST"])
@require_capability(Capability.CONTROL_NATIVE)
def execute():
    """Dispatch OS actions based on type.

    For click/rightclick/doubleclick: if 'target' is provided but x/y
    are missing, the hybrid pointer (UIA + OCR) auto-resolves the text
    target to screen coordinates before executing.
    """
    data = request.get_json(silent=True) or {}
    action = data.get("type", "").strip().lower()
    target = data.get("target", "")
    x = data.get("x")
    y = data.get("y")

    # Auto-resolve text targets to coordinates
    x, y, resolve_info = _resolve_target(action, target, x, y)
    if resolve_info and "error" in resolve_info:
        return jsonify({"error": resolve_info["error"], "type": action,
                        "status": "error"}), 404

    ctrl = app.config["OS_CTRL"]

    dispatch = {
        "click": lambda: ctrl.click(target, x, y),
        "rightclick": lambda: ctrl.right_click(x, y),
        "doubleclick": lambda: ctrl.double_click(x, y),
        "type": lambda: ctrl.type(target),
        "hotkey": lambda: ctrl.hotkey(target),
        "openapp": lambda: ctrl.open_app(target),
    }

    handler = dispatch.get(action)
    if handler is None:
        return jsonify({"error": f"Unknown action type: {action}"}), 400

    try:
        result = handler()
        result["type"] = action
        result["status"] = "ok" if "error" not in result else "error"
        if resolve_info:
            result["resolved"] = resolve_info
        code = 200 if result["status"] == "ok" else 400
        return jsonify(result), code
    except Exception as e:
        return jsonify({"error": str(e), "type": action, "status": "error"}), 500


@app.route("/execute/batch", methods=["POST"])
@require_capability(Capability.CONTROL_NATIVE)
def execute_batch():
    """Execute multiple actions sequentially."""
    data = request.get_json(silent=True) or {}
    actions = data.get("actions", [])
    results = []

    has_error = False
    for action in actions:
        resp = execute_inner(action)
        results.append(resp)
        if resp.get("status") == "error":
            has_error = True

    status_code = 400 if has_error else 200
    return jsonify({"status": "error" if has_error else "ok", "count": len(results), "results": results}), status_code


def execute_inner(action_data):
    """Non-route helper for batch execution."""
    action = action_data.get("type", "").strip().lower()
    target = action_data.get("target", "")
    x = action_data.get("x")
    y = action_data.get("y")

    # Auto-resolve text targets to coordinates
    x, y, resolve_info = _resolve_target(action, target, x, y)
    if resolve_info and "error" in resolve_info:
        return {"error": resolve_info["error"], "type": action, "status": "error"}

    ctrl = app.config["OS_CTRL"]

    dispatch = {
        "click": lambda: ctrl.click(target, x, y),
        "rightclick": lambda: ctrl.right_click(x, y),
        "doubleclick": lambda: ctrl.double_click(x, y),
        "type": lambda: ctrl.type(target),
        "hotkey": lambda: ctrl.hotkey(target),
        "openapp": lambda: ctrl.open_app(target),
    }

    handler = dispatch.get(action)
    if handler is None:
        return {"error": f"Unknown action: {action}", "status": "error"}
    try:
        result = handler()
        result["type"] = action
        result["status"] = "ok" if "error" not in result else "error"
        if resolve_info:
            result["resolved"] = resolve_info
        return result
    except Exception as e:
        return {"error": str(e), "type": action, "status": "error"}



# ---------------------------------------------------------------------------
# WebSocket Bridge  (connects to browser extension)
# ---------------------------------------------------------------------------

class WebSocketBridge:
    """Bidirectional bridge between Flask and the browser extension via WebSocket.

    Runs its own asyncio event loop in a daemon thread.
    Extension connects to ws://HOST:PORT, must present the per-install bearer
    token in an ``auth`` message within ``auth_timeout`` seconds, and only then
    receives inspect commands.
    """

    # Custom close code for rejected/unauthenticated connections.
    _CLOSE_AUTH = 4001

    def __init__(self, host="127.0.0.1", port=5002, token_manager=None,
                 auth_timeout: float = 10.0):
        self.host = host
        self.port = port
        self.token_manager = token_manager or app.config["TOKEN_MANAGER"]
        self.auth_timeout = auth_timeout
        self._loop = None
        self._thread = None
        self._ws = None
        self._pending: dict[str, Future] = {}
        self._ready = threading.Event()
        self._pending_lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WSBridge")
        self._thread.start()
        self._ready.wait(timeout=3)

    @property
    def connected(self):
        return self._ws is not None

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with websockets.serve(self._handler, self.host, self.port):
            self._ready.set()
            await asyncio.Future()

    async def _handler(self, websocket):
        if not await self._authenticate(websocket):
            return
        try:
            async for raw in websocket:
                data = json.loads(raw)
                msg_id = data.pop("id", None)
                if msg_id:
                    with self._pending_lock:
                        fut = self._pending.pop(msg_id, None)
                    if fut:
                        fut.set_result(data)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if self._ws is websocket:
                self._ws = None

    async def _authenticate(self, websocket) -> bool:
        """Require an ``auth`` message with a valid bearer token before use.

        The connection is only registered (``self._ws``) after a successful
        handshake, so inspect commands cannot be issued before auth completes.
        """
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=self.auth_timeout)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            await self._close_unauth(websocket, "auth timeout or closed")
            return False
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._close_unauth(websocket, "malformed auth message")
            return False
        if data.get("type") != "auth":
            await self._close_unauth(websocket, "auth required")
            return False
        if not self.token_manager.verify(data.get("token")):
            await self._close_unauth(websocket, "invalid token")
            return False
        self._ws = websocket
        await websocket.send(json.dumps({"type": "auth_ok"}))
        return True

    async def _close_unauth(self, websocket, reason: str) -> None:
        try:
            await websocket.send(json.dumps({"type": "auth_error", "error": reason}))
        except websockets.exceptions.ConnectionClosed:
            pass
        try:
            await websocket.close(code=self._CLOSE_AUTH, reason=reason)
        except websockets.exceptions.ConnectionClosed:
            pass

    def inspect(self, x: int, y: int, timeout: float = 5.0) -> dict:
        """Send inspect command to extension. Blocking call from any thread."""
        if not self._ws:
            raise ConnectionError("No browser extension connected to WebSocket bridge")

        msg_id = f"{time.monotonic_ns()}"
        fut: Future = Future()
        with self._pending_lock:
            self._pending[msg_id] = fut

        async def _send():
            await self._ws.send(json.dumps({
                "type": "inspect", "id": msg_id, "x": x, "y": y,
            }))

        asyncio.run_coroutine_threadsafe(_send(), self._loop)

        try:
            return fut.result(timeout=timeout)
        except TimeoutError:
            with self._pending_lock:
                self._pending.pop(msg_id, None)
            raise TimeoutError("Extension did not respond in time")


# ---------------------------------------------------------------------------
# Inspect endpoint  (bridges Flask → WebSocketBridge)
# ---------------------------------------------------------------------------

@app.route("/inspect", methods=["POST"])
def inspect_web():
    """Inspect a DOM element at (x, y) in the active browser tab.

    Accepts: { "x": int, "y": int }
    Returns: element data from the content script, or error.
    """
    bridge: WebSocketBridge = app.config.get("WS_BRIDGE")
    if not bridge or not bridge.connected:
        return jsonify({"error": "Browser extension not connected"}), 503

    data = request.get_json(silent=True) or {}
    x = data.get("x")
    y = data.get("y")
    if x is None or y is None:
        return jsonify({"error": "x and y required"}), 400

    try:
        result = bridge.inspect(int(x), int(y))
        return jsonify({"status": "ok", "element": result})
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except TimeoutError as e:
        return jsonify({"error": str(e)}), 504


# ---------------------------------------------------------------------------
# Highlight endpoints  (TipTour-style "Focus Highlight" resolution)
# ---------------------------------------------------------------------------

@app.route("/highlight/resolve", methods=["POST"])
def highlight_resolve():
    """Resolve a highlighted screen region into source context.

    Accepts: {
        "rect": {"x": 0, "y": 0, "width": 100, "height": 200},
        "source_file_path": "optional explicit path",
        "selected_text": "optional text selection"
    }
    Returns: HighlightResolution with kind, confidence, tools, etc.
    """
    data = request.get_json(silent=True) or {}
    rect_data = data.get("rect", {})
    if not rect_data:
        return jsonify({"error": "rect {x, y, width, height} required"}), 400

    x = rect_data.get("x")
    y = rect_data.get("y")
    w = rect_data.get("width") or rect_data.get("w")
    h = rect_data.get("height") or rect_data.get("h")
    if x is None or y is None or w is None or h is None:
        return jsonify({"error": "rect requires x, y, width, height"}), 400

    bridge = app.config.get("WS_BRIDGE")
    resolver = HighlightResolver(ws_bridge=bridge)
    resolution = resolver.resolve(
        rect=(int(x), int(y), int(w), int(h)),
        explicit_file_path=data.get("source_file_path"),
        selected_text=data.get("selected_text"),
    )
    return jsonify(resolution.to_dict())


@app.route("/highlight/capture", methods=["POST"])
def highlight_capture():
    """Capture a highlighted screen region as a cropped screenshot.

    Accepts: {
        "rect": {"x": 0, "y": 0, "width": 100, "height": 200},
        "annotation": "optional text annotation"
    }
    Returns: { "path": "...", "filename": "...", "url": "...", "resolution": {...} }
    """
    import mss
    from PIL import Image

    data = request.get_json(silent=True) or {}
    rect_data = data.get("rect", {})
    if not rect_data:
        return jsonify({"error": "rect required"}), 400

    x = rect_data.get("x", 0)
    y = rect_data.get("y", 0)
    w = rect_data.get("width") or rect_data.get("w", 0)
    h = rect_data.get("height") or rect_data.get("h", 0)
    if not w or not h:
        return jsonify({"error": "rect must have non-zero width/height"}), 400

    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"highlight_{ts}.png"
    path = os.path.join(SCREENSHOTS_DIR, filename)

    with mss.mss() as sct:
        from arrow.capture.coordinate_mapper import ScreenInfo
        screen = ScreenInfo(name="overlay", geometry=(int(x), int(y), int(w), int(h)), scale=1.0)
        monitor = find_mss_monitor(sct, screen)
        full = sct.grab(monitor)
        pil_full = Image.frombytes("RGB", full.size, full.rgb)
        cropped = pil_full.crop((int(x), int(y), int(x + w), int(y + h)))
        cropped.save(path, "PNG")

    bridge = app.config.get("WS_BRIDGE")
    resolver = HighlightResolver(ws_bridge=bridge)
    resolution = resolver.resolve(
        rect=(int(x), int(y), int(w), int(h)),
        explicit_file_path=data.get("source_file_path"),
        selected_text=data.get("selected_text"),
    )

    return jsonify({
        "path": os.path.abspath(path),
        "filename": filename,
        "url": f"/screenshots/{filename}",
        "width": int(w),
        "height": int(h),
        "annotation": data.get("annotation", ""),
        "resolution": resolution.to_dict(),
    })


@app.route("/highlight/execute", methods=["POST"])
@require_capability(Capability.CONTROL_NATIVE)
def highlight_execute():
    """Execute an action scoped to a highlighted region.

    Accepts: {
        "rect": {"x": 0, "y": 0, "width": 100, "height": 200},
        "action": { "type": "click|type|hotkey|edit|inspect", ... }
    }
    For positional actions (click), the highlight center is used as (x, y).
    """
    data = request.get_json(silent=True) or {}
    rect_data = data.get("rect", {})
    action_data = data.get("action", {})

    if not rect_data:
        return jsonify({"error": "rect required"}), 400
    if not action_data:
        return jsonify({"error": "action required"}), 400

    x = rect_data.get("x", 0)
    y = rect_data.get("y", 0)
    w = rect_data.get("width") or rect_data.get("w", 0)
    h = rect_data.get("height") or rect_data.get("h", 0)

    action_type = action_data.get("type", "").strip().lower()

    if action_type == "inspect":
        cx = x + w // 2
        cy = y + h // 2
        bridge = app.config.get("WS_BRIDGE")
        if not bridge or not bridge.connected:
            return jsonify({"error": "Browser extension not connected"}), 503
        try:
            result = bridge.inspect(int(cx), int(cy))
            return jsonify({"status": "ok", "element": result, "center": [cx, cy]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if action_type in ("click", "rightclick", "doubleclick"):
        cx = data.get("x", x + w // 2)
        cy = data.get("y", y + h // 2)
        action_data["x"] = int(cx)
        action_data["y"] = int(cy)

    if action_type == "edit" or action_type == "select_all":
        cx = x + w // 2
        cy = y + h // 2
        ctrl = app.config["OS_CTRL"]
        ctrl.click(x=int(cx), y=int(cy))
        from time import sleep
        sleep(0.1)
        ctrl.hotkey("ctrl+a")
        return jsonify({"status": "ok", "action": "select_all", "at": [cx, cy]})

    return execute_inner(action_data)


# ---------------------------------------------------------------------------
# Server runner  (thread-safe)
# ---------------------------------------------------------------------------

class AgentServer:
    """Wraps the Flask server and WebSocket bridge in background threads."""

    def __init__(self, host="127.0.0.1", port=5001, ws_host="127.0.0.1", ws_port=5002):
        self.host = host
        self.port = port
        self.ws_host = ws_host
        self.ws_port = ws_port
        self._thread = None
        self._ws_bridge = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        app.config["start_time"] = time.time()

        # Start WebSocket bridge
        self._ws_bridge = WebSocketBridge(
            host=self.ws_host,
            port=self.ws_port,
            token_manager=app.config["TOKEN_MANAGER"],
        )
        self._ws_bridge.start()
        app.config["WS_BRIDGE"] = self._ws_bridge
        log.info("[WSBridge] listening on ws://%s:%s", self.ws_host, self.ws_port)

        # Start Flask
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="AgentServer",
        )
        self._thread.start()
        log.info("[AgentServer] listening on http://%s:%s", self.host, self.port)

    def _run(self):
        app.run(host=self.host, port=self.port, threaded=True, debug=False, use_reloader=False)

    def stop(self):
        self._running = False

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def ws_bridge(self):
        """The WebSocket bridge used by the browser extension."""
        return self._ws_bridge
