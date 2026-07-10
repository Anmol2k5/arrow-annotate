import ctypes
import datetime
import os
import signal
import sys
import threading

from PyQt6.QtCore import QMetaObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from arrow.capture.session import CaptureState, SessionManager
from arrow.server.server import AgentServer
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord
from arrow.ui.notch import DynamicNotch
from arrow.ui.overlay import SelectionOverlay
from arrow.ui.voice_input import VoiceInput


def _get_cursor_position():
    """Get current cursor position via Win32 API."""
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return 0, 0


def _get_foreground_title():
    """Get the title of the foreground window via Win32 API."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        return buf.value
    except Exception:
        return ""


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

    # -- Setup Session Manager --
    session_manager = SessionManager()

    current_voice_text = ""
    is_annotating = False

    def toggle_annotation():
        nonlocal is_annotating, current_voice_text
        if not is_annotating:
            is_annotating = True
            current_voice_text = ""
            
            # Start new capture session
            session = session_manager.start_session()
            capture_id = session.capture_id
            
            # Transition to ANNOTATING
            session_manager.transition_to(CaptureState.ANNOTATING)

            QMetaObject.invokeMethod(overlay, "show_overlay", Qt.ConnectionType.QueuedConnection)
            # Pass capture_id to voice input
            QMetaObject.invokeMethod(voice, "start_listening", Qt.ConnectionType.QueuedConnection, capture_id)
            # Show waveform in notch idle pill
            QMetaObject.invokeMethod(notch, "set_recording", Qt.ConnectionType.QueuedConnection, True)
        else:
            is_annotating = False
            QMetaObject.invokeMethod(overlay, "hide_overlay", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(voice, "stop_listening", Qt.ConnectionType.QueuedConnection)
            # Restore logo in notch idle pill
            QMetaObject.invokeMethod(notch, "set_recording", Qt.ConnectionType.QueuedConnection, False)
            
            # If no selection comes, cancellation is handled in hide_overlay/on_selection

    notch.on_highlight_requested = toggle_annotation

    def on_voice_result(text, capture_id):
        nonlocal current_voice_text, is_annotating
        session = session_manager.active_session
        if not session or session.capture_id != capture_id:
            return
        
        current_voice_text = text
        if is_annotating:
            toggle_annotation()  # triggers hide_overlay -> selection_complete

    def on_voice_error(err, capture_id):
        nonlocal is_annotating
        session = session_manager.active_session
        if not session or session.capture_id != capture_id:
            return
        print("Voice error:", err)
        if is_annotating:
            toggle_annotation()

    voice.result_ready.connect(on_voice_result)
    voice.error.connect(on_voice_error)

    def on_selection(result):
        """Full capture flow when overlay selection completes."""
        nonlocal current_voice_text

        session = session_manager.active_session
        if not session:
            return
        
        capture_id = session.capture_id
        
        try:
            session_manager.transition_to(CaptureState.COLLECTING_CONTEXT)
        except ValueError:
            return

        # Capture the voice text before it gets reset
        voice_text = current_voice_text
        # Grab cursor + window title on main thread context
        cursor_x, cursor_y = _get_cursor_position()
        window_title = _get_foreground_title()

        def _capture_task():
            import mss
            from PIL import Image

            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            try:
                session_manager.transition_to(CaptureState.PROCESSING)
            except ValueError:
                return

            rect = result.to_dict()
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            screenshots_dir = os.path.join(root_dir, "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                sct_img = sct.grab(monitor)
                full_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # Save full screenshot
            full_path = os.path.join(screenshots_dir, f"full_{ts}.png")
            full_img.save(full_path)

            # Crop to selection bounding box
            sel_x = max(0, rect.get("x", 0))
            sel_y = max(0, rect.get("y", 0))
            sel_w = rect.get("width", 0)
            sel_h = rect.get("height", 0)

            if sel_w > 0 and sel_h > 0:
                crop_box = (
                    sel_x,
                    sel_y,
                    min(sel_x + sel_w, full_img.width),
                    min(sel_y + sel_h, full_img.height),
                )
                cropped_img = full_img.crop(crop_box)
                crop_path = os.path.join(screenshots_dir, f"capture_{ts}.png")
                cropped_img.save(crop_path)
            else:
                crop_path = full_path

            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            # Save to capture store
            record = CaptureRecord(
                id=ts,
                timestamp=datetime.datetime.now().isoformat(),
                screenshot_path=crop_path,
                annotation_text=voice_text,
                cursor_x=cursor_x,
                cursor_y=cursor_y,
                bounding_box=rect,
                window_title=window_title,
            )
            capture_store.add(record)

            try:
                session_manager.transition_to(CaptureState.PREVIEW)
                session_manager.transition_to(CaptureState.READY)
            except ValueError:
                return

            # Update notch on main thread
            QMetaObject.invokeMethod(notch, "refresh_screenshots", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(notch, "auto_expand_briefly", Qt.ConnectionType.QueuedConnection)

            try:
                session_manager.transition_to(CaptureState.SENDING)
            except ValueError:
                return

            # Send to Agentation async
            threading.Thread(target=_send_to_agentation, args=(record, capture_id), daemon=True).start()

        threading.Thread(target=_capture_task, daemon=True).start()

    def _send_to_agentation(record, capture_id):
        if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
            return

        try:
            session_manager.transition_to(CaptureState.RUNNING)
            from arrow.providers.agentation import AgentationClient
            client = AgentationClient()
            sessions = client.list_sessions()
            if sessions:
                session_id = sessions[0]["id"]
            else:
                s = client.create_session("bluely://desktop")
                session_id = s["id"]

            filename = os.path.basename(record.screenshot_path)
            image_url = f"{server.base_url}/screenshots/{filename}"
            
            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            client.add_annotation(session_id, {
                "comment": record.annotation_text or "Visual highlight",
                "element": "desktop_screen",
                "elementPath": "desktop",
                "imagePath": image_url
            })
            
            if session_manager.active_session and session_manager.active_session.capture_id == capture_id:
                session_manager.transition_to(CaptureState.COMPLETED)
        except Exception as e:
            print("Agentation sync failed:", e)
            if session_manager.active_session and session_manager.active_session.capture_id == capture_id:
                try:
                    session_manager.transition_to(CaptureState.FAILED)
                except ValueError:
                    pass

    overlay.selection_complete.connect(on_selection)

    # Optional global hotkey
    try:
        import keyboard
        keyboard.add_hotkey("ctrl+shift+space", toggle_annotation)
    except Exception as e:
        print(f"Warning: could not register global hotkey: {e}")

    # -- Poll server status every 5s --
    def poll_server():
        try:
            import json as _json
            import urllib.request
            url = f"{server.base_url}/status"
            resp = urllib.request.urlopen(url, timeout=2)
            _json.loads(resp.read().decode())
        except Exception:
            pass

    poll_timer = QTimer()
    poll_timer.timeout.connect(poll_server)
    poll_timer.start(5000)
    poll_server()

    # -- Graceful shutdown on SIGINT --
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
