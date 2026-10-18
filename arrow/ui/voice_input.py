import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("arrow.ui.voice_input")


class VoiceInput(QObject):
    """Record while held, then recognize the complete recording after release."""

    result_ready = pyqtSignal(str, str)
    error = pyqtSignal(str, str)
    finished = pyqtSignal(str, str, str)
    listening_changed = pyqtSignal(bool)

    def __init__(self, language: str = 'en-IN'):
        super().__init__()
        self.language = language
        self._listening = False
        self._active = False
        self._thread: threading.Thread | None = None
        self.current_capture_id = ""
        self._generation = 0
        self._state_lock = threading.RLock()
        self._microphone_lock = threading.Lock()
        self._finish_requested = threading.Event()

    @property
    def is_listening(self) -> bool:
        with self._state_lock:
            return self._listening

    def _set_listening(self, listening: bool):
        # Called with _state_lock held so an old worker cannot change a new
        # capture's recording state or emit an out-of-order state transition.
        if self._listening != listening:
            self._listening = listening
            self.listening_changed.emit(listening)

    def start_listening(self, capture_id: str):
        with self._state_lock:
            if self._active and self.current_capture_id == capture_id:
                return
            self.stop_listening()
            self._active = True
            self.current_capture_id = capture_id
            generation = self._generation
            finish_requested = threading.Event()
            self._finish_requested = finish_requested
            self._thread = threading.Thread(
                target=self._listen,
                args=(capture_id, generation, finish_requested, self.language),
                daemon=True,
            )
            self._thread.start()

    def finish_listening(self):
        """Request release without waiting for audio I/O or recognition."""
        with self._state_lock:
            self._finish_requested.set()

    def stop_listening(self):
        """Cancel recording or transcription and discard this generation."""
        with self._state_lock:
            self._generation += 1
            self._active = False
            self._finish_requested.set()
            self._set_listening(False)

    def _is_current(self, generation: int) -> bool:
        with self._state_lock:
            return self._active and self._generation == generation

    def _complete(self, text: str, error: str, capture_id: str, generation: int):
        with self._state_lock:
            if not self._is_current(generation):
                return
            self._set_listening(False)
            self._active = False
            # Publish exactly once, while holding the generation guard. Qt
            # delivers these signals to GUI slots on the GUI thread.
            if error:
                self.error.emit(error, capture_id)
            else:
                self.result_ready.emit(text, capture_id)
            self.finished.emit(text, error, capture_id)

    def _listen(self, capture_id: str, generation: int, finish_requested: threading.Event, language: str):
        transcript = ''
        error = ''
        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            # Network I/O must not leave a capture processing indefinitely.
            recognizer.operation_timeout = 15
            frames = []
            # Serialize device ownership, but release the microphone before
            # network recognition so a new capture can start immediately.
            with self._microphone_lock:
                if not self._is_current(generation):
                    return
                with sr.Microphone() as source:
                    with self._state_lock:
                        if not self._is_current(generation):
                            return
                        self._set_listening(True)
                    while not finish_requested.is_set():
                        frame = source.stream.read(source.CHUNK)
                        if not frame:
                            break
                        # If release arrives during this read, retain its audio.
                        frames.append(frame)
                    audio = sr.AudioData(b''.join(frames), source.SAMPLE_RATE, source.SAMPLE_WIDTH)
                with self._state_lock:
                    if self._is_current(generation):
                        self._set_listening(False)
            if not self._is_current(generation):
                return
            if not frames:
                error = 'No audio recorded'
            else:
                try:
                    transcript = recognizer.recognize_google(audio, language=language)
                except sr.UnknownValueError:
                    error = 'Could not understand audio'
                except sr.RequestError as exc:
                    error = f'Speech recognition error: {exc}'
        except ImportError:
            error = 'Install: pip install SpeechRecognition pyaudio'
        except OSError:
            error = 'No microphone found'
        except Exception as exc:
            logger.warning('Voice input failed for capture %s: %s', capture_id, exc)
            error = f'Voice error: {exc}'
        self._complete(transcript, error, capture_id, generation)
