import sys
import signal

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from notch import DynamicNotch
from server import AgentServer
from highlight_overlay import SelectionOverlay
from voice_input import VoiceInput
from capture_store import CaptureStore, CaptureRecord
import datetime
import os


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bluely Agent")

    # -- Start Flask server in background daemon thread --
    server = AgentServer(host="127.0.0.1", port=5001)
    server.start()

    # -- Build and show the DynamicNotch overlay --
    notch = DynamicNotch(server=server)
    notch.show()

    # -- Setup Capture Store --
    capture_store = CaptureStore()

    # -- Setup Highlight Overlay & Voice Input --
    overlay = SelectionOverlay()
    voice = VoiceInput()

    current_voice_text = ""
    is_annotating = False

    def toggle_annotation():
        nonlocal is_annotating
        from PyQt6.QtCore import QMetaObject, Qt
        if not is_annotating:
            is_annotating = True
            current_voice_text = ""
            QMetaObject.invokeMethod(overlay, "show_overlay", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(voice, "start_listening", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(notch, "update_status", Qt.ConnectionType.QueuedConnection, "🎤 Recording & Drawing...")
        else:
            is_annotating = False
            QMetaObject.invokeMethod(overlay, "hide_overlay", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(voice, "stop_listening", Qt.ConnectionType.QueuedConnection)

    notch.on_highlight_requested = toggle_annotation

    def on_voice_result(text):
        nonlocal current_voice_text, is_annotating
        current_voice_text = text
        if is_annotating:
            toggle_annotation() # triggers hide_overlay -> selection_complete

    def on_voice_error(err):
        nonlocal is_annotating
        print("Voice error:", err)
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(notch, "update_status", Qt.ConnectionType.QueuedConnection, f"⚠️ {err}")
        if is_annotating:
            toggle_annotation()

    voice.result_ready.connect(on_voice_result)
    voice.error.connect(on_voice_error)

    def on_selection(result):
        # We get here when overlay hides.
        # Let's capture the screenshot locally using mss to avoid web overhead, or via server endpoint
        def _capture_task():
            import mss
            from PIL import Image
            
            # Capture the designated rect
            rect = result.to_dict()
            with mss.mss() as sct:
                # capture full screen for simplicity if bounds are weird, or exact bounds
                # Actually, capturing full screen and saving is safer for "Desktop Overlay"
                monitor = sct.monitors[1]  # primary monitor
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(screenshots_dir, f"capture_{ts}.png")
            img.save(path)
            
            # Save to capture store
            record = CaptureRecord(
                id=ts,
                timestamp=datetime.datetime.now().isoformat(),
                screenshot_path=path,
                annotation_text=current_voice_text,
                bounding_box=rect
            )
            capture_store.add(record)
            
            # Update Notch
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(notch._content_stack.widget(2), "_scan_existing", Qt.ConnectionType.QueuedConnection)
            
            # Send to Agentation async
            import threading
            threading.Thread(target=_send_to_agentation, args=(record,), daemon=True).start()

        import threading
        threading.Thread(target=_capture_task, daemon=True).start()
        
    def _send_to_agentation(record):
        try:
            from agentation_client import AgentationClient
            client = AgentationClient()
            # Agentation expects a session, so we fetch the first open one or create
            sessions = client.list_sessions()
            if sessions:
                session_id = sessions[0]["id"]
            else:
                s = client.create_session("bluely://desktop")
                session_id = s["id"]
                
            # Post annotation
            client.add_annotation(session_id, {
                "comment": record.annotation_text or "Visual highlight",
                "element": "desktop_screen",
                "elementPath": "desktop",
                "imagePath": record.screenshot_path
            })
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(notch, "update_status", Qt.ConnectionType.QueuedConnection, "✅ Synced to Agentation")
        except Exception as e:
            print("Agentation sync failed:", e)

    overlay.selection_complete.connect(on_selection)

    # Optional global hotkey
    try:
        import keyboard
        keyboard.add_hotkey("ctrl+shift+space", toggle_annotation)
    except Exception as e:
        print(f"Warning: could not register global hotkey: {e}")

    # -- Poll server status every 5s to update notch --
    def poll_server():
        try:
            import urllib.request
            import json as _json
            url = f"{server.base_url}/status"
            resp = urllib.request.urlopen(url, timeout=2)
            data = _json.loads(resp.read().decode())
            notch.update_status(f"● {data.get('status', 'connected').title()}")
        except Exception:
            notch.update_status("○ Offline")

    poll_timer = QTimer()
    poll_timer.timeout.connect(poll_server)
    poll_timer.start(5000)
    poll_server()

    # -- Graceful shutdown on SIGINT --
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
