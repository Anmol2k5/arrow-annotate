import io
import os
import base64
import socket
import platform
import subprocess
import threading
import json
import ctypes
import time
import re

from flask import Flask, jsonify, request, Response


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
            vk = cls._VK.get(ch.lower(), 0)
            if vk:
                cls._key_down(vk)
                time.sleep(0.01)
                cls._key_up(vk)
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
        """Open an application or file."""
        try:
            if os.path.exists(target):
                os.startfile(target)
            else:
                subprocess.Popen(target, shell=True)
            return {"action": "openApp", "target": target}
        except Exception as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["AGENT_NAME"] = "bluely-agent"
app.config["OS_CTRL"] = OSController()


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
        monitor = sct.monitors[1]
        img = sct.grab(monitor)
        pil_img = Image.frombytes("RGB", img.size, img.rgb)

    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=88, optimize=True)
    b64 = base64.b64encode(buffer.getvalue()).decode()

    return jsonify({
        "screenshot": b64,
        "format": "jpeg",
        "width": img.size[0],
        "height": img.size[1],
    })


@app.route("/execute", methods=["POST"])
def execute():
    """Dispatch OS actions based on type."""
    data = request.get_json(silent=True) or {}
    action = data.get("type", "").strip().lower()
    target = data.get("target", "")
    x = data.get("x")
    y = data.get("y")

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
        code = 200 if result["status"] == "ok" else 400
        return jsonify(result), code
    except Exception as e:
        return jsonify({"error": str(e), "type": action, "status": "error"}), 500


@app.route("/execute/batch", methods=["POST"])
def execute_batch():
    """Execute multiple actions sequentially."""
    data = request.get_json(silent=True) or {}
    actions = data.get("actions", [])
    results = []

    for action in actions:
        resp = execute_inner(action)
        results.append(resp)

    return jsonify({"status": "ok", "count": len(results), "results": results})


def execute_inner(action_data):
    """Non-route helper for batch execution."""
    action = action_data.get("type", "").strip().lower()
    target = action_data.get("target", "")
    x = action_data.get("x")
    y = action_data.get("y")
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
        return result
    except Exception as e:
        return {"error": str(e), "type": action, "status": "error"}


# ---------------------------------------------------------------------------
# Server runner  (thread-safe)
# ---------------------------------------------------------------------------

class AgentServer:
    """Wraps the Flask server in a background thread."""

    def __init__(self, host="127.0.0.1", port=5001):
        self.host = host
        self.port = port
        self._thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        app.config["start_time"] = time.time()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="AgentServer",
        )
        self._thread.start()
        print(f"[AgentServer] listening on http://{self.host}:{self.port}")

    def _run(self):
        app.run(host=self.host, port=self.port, threaded=True, debug=False, use_reloader=False)

    def stop(self):
        self._running = False
        # Flask has no clean shutdown from outside in older versions;
        # the daemon thread will die with the process.

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"
