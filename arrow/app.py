import ctypes
import logging
import os
import signal
import sys
import threading

from PyQt6.QtCore import QMetaObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation, CaptureState, SessionManager
from arrow.context.orchestrator import ContextOrchestrator
from arrow.server.server import AgentServer
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord
from arrow.storage.settings import get_project_dir
from arrow.ui.notch import DynamicNotch
from arrow.ui.overlay import SelectionOverlay
from arrow.ui.voice_input import VoiceInput

log = logging.getLogger("arrow.app")


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

    # -- Setup the capture pipeline (one orchestrator for all capture flows) --
    orchestrator = ContextOrchestrator(
        store=capture_store,
        ws_bridge=server.ws_bridge,
        project_dir=get_project_dir(),
    )

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
    notch.on_project_selected = orchestrator.set_project_dir

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
        log.error("Voice error: %s", err)
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

        # Capture raw screenshot on main thread (with overlay auto-hiding)
        screenshot_service = ScreenshotService()
        raw_img, screen_info, mapper = screenshot_service.capture_raw(overlay)

        # Create annotations from the overlay result (source + optional destination)
        data = result.to_dict()
        source_rect = data.get("source") or data
        dest_rect = data.get("destination")
        rect = source_rect

        annotations = [
            Annotation(
                id=f"ann_src_{capture_id}",
                type="rectangle",
                role="source",
                label="Current element",
                geometry={"x": source_rect["x"], "y": source_rect["y"],
                          "width": source_rect["width"], "height": source_rect["height"]}
            )
        ]
        if dest_rect:
            annotations.append(
                Annotation(
                    id=f"ann_dst_{capture_id}",
                    type="rectangle",
                    role="destination",
                    label="Move here",
                    geometry={"x": dest_rect["x"], "y": dest_rect["y"],
                              "width": dest_rect["width"], "height": dest_rect["height"]}
                )
            )
        session.annotations = annotations

        def _capture_task():
            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            try:
                session_manager.transition_to(CaptureState.PROCESSING)
            except ValueError:
                return

            try:
                # Run the full pipeline: resolve anchors (browser DOM → UIA),
                # collect repository context, render annotated screenshot +
                # crops, compile the change request, persist the record.
                pipeline = orchestrator.run(
                    session=session,
                    rect=rect,
                    instruction=voice_text,
                    cursor=(cursor_x, cursor_y),
                    window_title=window_title,
                    raw_img=raw_img,
                    screen_info=screen_info,
                    mapper=mapper,
                )
            except Exception as e:
                log.error("Capture pipeline failed: %s", e)
                try:
                    session_manager.transition_to(CaptureState.FAILED)
                except ValueError:
                    pass
                return

            if pipeline.error:
                log.error("Capture pipeline error: %s", pipeline.error)
                try:
                    session_manager.transition_to(CaptureState.FAILED)
                except ValueError:
                    pass
                return

            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

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
            record = CaptureRecord.from_dict(pipeline.record)
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
            log.error("Agentation sync failed: %s", e)
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
        log.warning("Could not register global hotkey: %s", e)

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
