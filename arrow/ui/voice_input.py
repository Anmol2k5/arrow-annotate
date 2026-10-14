import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("arrow.ui.voice_input")


class VoiceInput(QObject):
    # Emits (transcript_text, capture_id)
    result_ready = pyqtSignal(str, str)
    # Emits (error_message, capture_id)
    error = pyqtSignal(str, str)
    listening_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._listening = False
        self._thread: threading.Thread | None = None
        self._recognizer = None
        self.current_capture_id = ""
        self._generation = 0

    @property
    def is_listening(self) -> bool:
        return self._listening

    def start_listening(self, capture_id: str):
        if self._listening:
            if self.current_capture_id == capture_id:
                return
            self.stop_listening()
        self._generation += 1
        self._listening = True
        self.current_capture_id = capture_id
        self.listening_changed.emit(True)
        self._thread = threading.Thread(target=self._listen, args=(capture_id, self._generation), daemon=True)
        self._thread.start()

    def stop_listening(self):
        self._generation += 1
        self._listening = False
        self.listening_changed.emit(False)

    def _listen(self, capture_id: str, generation: int):
        def is_current():
            return self._listening and self.current_capture_id == capture_id and self._generation == generation

        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                # Listen with timeouts to avoid blocking forever
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=8)
            
            # Check if this session has been cancelled or changed before recognizing
            if not is_current():
                logger.info("Discarding voice input because capture session %s was cancelled or changed", capture_id)
                return

            try:
                text = recognizer.recognize_google(audio)
                if is_current():
                    self.result_ready.emit(text, capture_id)
            except sr.UnknownValueError:
                if is_current():
                    self.error.emit("Could not understand audio", capture_id)
            except sr.RequestError as e:
                if is_current():
                    self.error.emit(f"Speech recognition error: {e}", capture_id)
        except ImportError:
            if is_current():
                self.error.emit("Install: pip install SpeechRecognition pyaudio", capture_id)
        except OSError:
            if is_current():
                self.error.emit("No microphone found", capture_id)
        except Exception as e:
            if is_current():
                self.error.emit(f"Voice error: {e}", capture_id)
        finally:
            if self._generation == generation:
                self._listening = False
                self.listening_changed.emit(False)
