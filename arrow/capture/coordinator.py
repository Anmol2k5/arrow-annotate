"""Join release-time screenshot capture with asynchronous speech recognition."""
import logging

from PyQt6.QtCore import QObject

from arrow.capture.session import CaptureState

log = logging.getLogger(__name__)


class CaptureCoordinator(QObject):
    def __init__(self, manager, overlay, voice, notch, snapshot, on_ready):
        super().__init__()
        self.manager, self.overlay, self.voice, self.notch = manager, overlay, voice, notch
        self.snapshot, self.on_ready = snapshot, on_ready
        self._phase = 'idle'
        self._capture_id = None
        self._frame = None
        self._speech = None
        overlay.selection_complete.connect(self._on_selection)
        overlay.finish_requested.connect(self.finish)
        overlay.cancel_requested.connect(self.cancel)
        voice.finished.connect(self._on_voice_finished)

    @property
    def busy(self):
        return self._phase != 'idle'

    @property
    def recording(self):
        return self._phase == 'recording'

    def start(self):
        if self.busy:
            return
        session = self.manager.start_session()
        self._capture_id = session.capture_id
        self._frame, self._speech = None, None
        self._phase = 'recording'
        self.manager.transition_to(CaptureState.ANNOTATING, capture_id=self._capture_id)
        self.notch.set_recording(True)
        self.overlay.show_overlay()
        self.voice.start_listening(self._capture_id)

    def finish(self):
        if not self.recording:
            return
        self._phase = 'finishing'
        self.notch.set_recording(False)
        self.manager.transition_to(CaptureState.COLLECTING_CONTEXT, capture_id=self._capture_id)
        self.voice.finish_listening()
        # Emits a frozen scene synchronously. Snapshot now, before waiting for
        # recognition, so the screenshot matches what the user pointed at.
        self.overlay.hide_overlay()

    def toggle(self):
        if self.recording:
            self.finish()
        elif not self.busy:
            self.start()

    def _on_selection(self, selection):
        if self._phase != 'finishing':
            return
        try:
            self._frame = self.snapshot(selection)
        except Exception as exc:
            log.exception('Screenshot capture failed')
            session = self.manager.active_session
            if session and session.capture_id == self._capture_id:
                session.error = str(exc)
                self.manager.transition_to(CaptureState.FAILED, capture_id=self._capture_id)
                self.notch.set_status(f'Capture failed: {exc}')
            self.voice.stop_listening()
            self._phase = 'idle'
            return
        self._maybe_ready()

    def _on_voice_finished(self, text, error, capture_id):
        if capture_id != self._capture_id or self._phase not in ('recording', 'finishing'):
            return
        self._speech = (text, error)
        self._maybe_ready()

    def _maybe_ready(self):
        if self._phase != 'finishing' or self._frame is None or self._speech is None:
            return
        session = self.manager.active_session
        if not session or session.capture_id != self._capture_id:
            self._phase = 'idle'
            return
        self._phase = 'processing'
        text, error = self._speech
        session.voice_transcript = text
        if error:
            log.warning('Voice capture: %s', error)
            self.notch.set_status(f'{error}. Preparing screenshot; use Edit to add your instruction.')
        else:
            self.notch.set_status('Preparing annotated capture…')
        try:
            self.on_ready(session, self._frame, text)
        except Exception as exc:
            log.exception('Capture processing could not start')
            session.error = str(exc)
            self.manager.transition_to(CaptureState.FAILED, capture_id=self._capture_id)
            self.notch.set_status(f'Capture failed: {exc}')
            self._phase = 'idle'

    def done(self, capture_id):
        if capture_id == self._capture_id:
            self._phase = 'idle'
            self._frame = None
            session = self.manager.active_session
            if session and session.capture_id == capture_id and session.state in (
                CaptureState.READY, CaptureState.SENDING, CaptureState.RUNNING, CaptureState.COMPLETED,
            ):
                error = self._speech[1] if self._speech else ''
                self.notch.set_status(
                    f'{error}. Screenshot ready; use Edit to add your instruction.' if error else
                    'Capture ready. Review, copy, or send to Codex / Claude Code.'
                )

    def cancel(self):
        if self._phase not in ('recording', 'finishing'):
            return
        self.voice.stop_listening()
        if hasattr(self.overlay, 'cancel_overlay'):
            self.overlay.cancel_overlay()
        else:
            self.overlay.hide()
        self.notch.set_recording(False)
        session = self.manager.active_session
        if session and session.capture_id == self._capture_id:
            self.manager.transition_to(CaptureState.CANCELLED, capture_id=self._capture_id)
        self._phase = 'idle'
        self._frame, self._speech = None, None
