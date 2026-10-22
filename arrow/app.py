import ctypes
import logging
import signal
import sys
import threading
from concurrent.futures import Future
from copy import copy

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from arrow.capture.coordinator import CaptureCoordinator
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation, CaptureState, SessionManager
from arrow.context.orchestrator import ContextOrchestrator
from arrow.core.hotkeys import HoldShortcut
from arrow.server.server import AgentServer
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord
from arrow.storage.settings import (
    SPEECH_LANGUAGES,
    get_capture_shortcut,
    get_project_dir,
    get_speech_language,
    set_capture_preferences,
)
from arrow.ui.notch import DynamicNotch
from arrow.ui.overlay import SelectionOverlay
from arrow.ui.tray import install_tray
from arrow.ui.voice_input import VoiceInput

log = logging.getLogger("arrow.app")


class MainThreadDispatcher(QObject):
    """Deliver callbacks to Qt even when the submitting thread has no event loop."""

    requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def submit(self, callback):
        self.requested.emit(callback)

    @pyqtSlot(object)
    def _run(self, callback):
        try:
            callback()
        except Exception:
            log.exception("Main-thread callback failed")


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
    app.setApplicationName("Arrow Annotate")
    ui_dispatcher = MainThreadDispatcher()

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
    voice = VoiceInput(language=get_speech_language())
    app.aboutToQuit.connect(voice.stop_listening)
    app.aboutToQuit.connect(server.stop)

    # -- Setup Session Manager --
    session_manager = SessionManager()

    capture_context = {}

    def snapshot(result):
        data = result.to_dict()
        session = session_manager.active_session
        session.annotations = [Annotation.model_validate(item) for item in data.get("annotations", [])]
        session.annotation_scene_frozen = True
        screenshot_service = ScreenshotService()
        # Exclude both Arrow windows from the saved screenshot.
        visible = notch.isVisible()
        notch.hide()
        try:
            raw_img, screen_info, mapper = screenshot_service.capture_raw(overlay)
        finally:
            if visible:
                notch.show()
        # Keep this capture bound to the repository selected at release.
        capture_pipeline = copy(orchestrator)
        anchors = Future()
        def resolve_context():
            try:
                anchors.set_result(capture_pipeline.resolve_annotations(session.annotations))
            except Exception as exc:
                anchors.set_exception(exc)
        threading.Thread(target=resolve_context, daemon=True).start()
        return data, raw_img, screen_info, mapper, dict(capture_context), anchors, capture_pipeline

    def on_ready(session, frame, voice_text):
        capture_id = session.capture_id
        data, raw_img, screen_info, mapper, context, anchors, capture_pipeline = frame
        rect = data.get("source") or {
            "x": screen_info.x, "y": screen_info.y,
            "width": screen_info.w, "height": screen_info.h,
        }
        cursor_x, cursor_y = context.get("cursor", (0, 0))
        window_title = context.get("window_title", "")

        def _capture_task():
            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            try:
                session_manager.transition_to(CaptureState.PROCESSING, capture_id=capture_id)
            except ValueError:
                return

            try:
                # Run the full pipeline: resolve anchors (browser DOM → UIA),
                # collect repository context, render annotated screenshot +
                # crops, compile the change request, persist the record.
                try:
                    resolved_anchors = anchors.result(timeout=12)
                except Exception:
                    log.warning("Element evidence unavailable; using screenshot context", exc_info=True)
                    resolved_anchors = (None, None)
                pipeline = capture_pipeline.run(
                    session=session,
                    rect=rect,
                    instruction=voice_text,
                    cursor=(cursor_x, cursor_y),
                    window_title=window_title,
                    raw_img=raw_img,
                    screen_info=screen_info,
                    mapper=mapper,
                    resolved_anchors=resolved_anchors,
                )
            except Exception as e:
                log.error("Capture pipeline failed: %s", e)
                session.error = str(e)
                ui_dispatcher.submit(lambda: notch.set_status(f"Capture failed: {session.error}"))
                try:
                    session_manager.transition_to(CaptureState.FAILED, capture_id=capture_id)
                except ValueError:
                    pass
                return

            if pipeline.error:
                log.error("Capture pipeline error: %s", pipeline.error)
                session.error = pipeline.error
                ui_dispatcher.submit(lambda: notch.set_status(f"Capture failed: {session.error}"))
                try:
                    session_manager.transition_to(CaptureState.FAILED, capture_id=capture_id)
                except ValueError:
                    pass
                return

            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            try:
                session_manager.transition_to(CaptureState.PREVIEW, capture_id=capture_id)
                session_manager.transition_to(CaptureState.READY, capture_id=capture_id)
            except ValueError:
                return

            # Update notch on main thread
            ui_dispatcher.submit(notch.refresh_screenshots)
            ui_dispatcher.submit(notch.auto_expand_briefly)

            # Send to Agentation async
            record = CaptureRecord.from_dict(pipeline.record)
            threading.Thread(target=_send_to_agentation, args=(record, capture_id), daemon=True).start()

        def run_capture():
            try:
                _capture_task()
            finally:
                ui_dispatcher.submit(lambda: coordinator.done(capture_id))

        threading.Thread(target=run_capture, daemon=True).start()

    def _send_to_agentation(record, capture_id):
        if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
            return

        from arrow.providers.agentation import AgentationClient, AgentationError
        client = AgentationClient()
        try:
            client.health()
        except AgentationError:
            log.info("Agentation unavailable; capture remains ready for MCP or direct providers")
            return

        try:
            session_manager.transition_to(CaptureState.SENDING, capture_id=capture_id)
            session_manager.transition_to(CaptureState.RUNNING, capture_id=capture_id)
            change_request = record.change_request or {}
            page_url = ((change_request.get("source") or {}).get("element") or {}).get("pageUrl")
            project = (change_request.get("project") or {}).get("repository_root")
            session_id = client.get_or_create_session(page_url or "bluely://desktop", project)["id"]
            
            if session_manager.active_session is None or session_manager.active_session.capture_id != capture_id:
                return

            client.add_annotation(session_id, {
                "comment": (record.annotation_text or "Visual highlight")
                           + f"\n\nAnnotated screenshot (local file): {record.screenshot_path}",
                "element": "desktop_screen",
                "elementPath": "desktop",
                "imagePath": record.screenshot_path
            })
            
            if session_manager.active_session and session_manager.active_session.capture_id == capture_id:
                session_manager.transition_to(CaptureState.COMPLETED, capture_id=capture_id)
        except Exception as e:
            log.error("Agentation sync failed: %s", e)
            if session_manager.active_session and session_manager.active_session.capture_id == capture_id:
                try:
                    session_manager.transition_to(CaptureState.FAILED, capture_id=capture_id)
                except ValueError:
                    pass

    coordinator = CaptureCoordinator(session_manager, overlay, voice, notch, snapshot, on_ready)

    def begin_capture():
        if not coordinator.busy and not QApplication.activeModalWidget():
            capture_context["cursor"] = _get_cursor_position()
            capture_context["window_title"] = _get_foreground_title()
            coordinator.start()

    def toggle_capture():
        if coordinator.recording:
            coordinator.finish()
        else:
            begin_capture()

    notch.on_highlight_requested = toggle_capture
    notch.on_project_selected = orchestrator.set_project_dir
    shortcut = HoldShortcut(
        get_capture_shortcut(),
        lambda: ui_dispatcher.submit(begin_capture),
        lambda: ui_dispatcher.submit(coordinator.finish),
    )
    try:
        shortcut.register()
    except Exception as exc:
        log.warning("Could not register global shortcut: %s", exc)
        notch.set_status(f"Shortcut unavailable: {exc}. Use the capture button or Settings.")
    app.aboutToQuit.connect(shortcut.close)
    cancel_shortcut = HoldShortcut(
        "esc", lambda: ui_dispatcher.submit(coordinator.cancel), lambda: None, allow_reserved=True,
    )
    try:
        cancel_shortcut.register()
    except Exception as exc:
        log.warning("Could not register cancellation shortcut: %s", exc)
    app.aboutToQuit.connect(cancel_shortcut.close)

    def configure_capture(key, language):
        if coordinator.busy:
            raise ValueError('Finish or cancel the current capture before changing capture settings.')
        if language not in SPEECH_LANGUAGES:
            raise ValueError('Choose a supported speech language.')
        old_key = get_capture_shortcut()
        shortcut.rebind(key)
        try:
            set_capture_preferences(key, language)
        except Exception:
            shortcut.rebind(old_key)
            raise
        voice.language = language
        notch.setToolTip(f"Hold {key} to draw and speak; release to capture. Enter finishes, Esc cancels.")
        notch.set_status(f"Hold {key} to draw and speak. Release to capture.")

    notch.on_capture_preferences_changed = configure_capture
    notch.on_settings_requested = lambda: notch.show_settings()
    notch.setToolTip(f"Hold {get_capture_shortcut()} to draw and speak; release to capture.")

    # -- Graceful shutdown on SIGINT --
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Retain the tray for the lifetime of the Qt event loop.
    tray = install_tray(app, notch, notch.on_settings_requested, begin_capture)
    if tray is not None:
        app.setQuitOnLastWindowClosed(False)
        app.aboutToQuit.connect(tray.hide)
    if getattr(sys, 'frozen', False):
        notch.set_status(f"Hold {get_capture_shortcut()} to draw and speak. Release to capture. Settings and Quit are in the system tray.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
