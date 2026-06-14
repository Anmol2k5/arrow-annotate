import threading

from PyQt6.QtCore import QObject, pyqtSignal


class VoiceInput(QObject):
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    listening_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._listening = False
        self._thread: threading.Thread | None = None
        self._recognizer = None

    @property
    def is_listening(self) -> bool:
        return self._listening

    def start_listening(self):
        if self._listening:
            return
        self._listening = True
        self.listening_changed.emit(True)
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop_listening(self):
        self._listening = False
        self.listening_changed.emit(False)

    def _listen(self):
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=5, phrase_time_limit=10)
            try:
                text = self._recognizer.recognize_google(audio)
                self.result_ready.emit(text)
            except sr.UnknownValueError:
                self.error.emit("Could not understand audio")
            except sr.RequestError as e:
                self.error.emit(f"Speech recognition error: {e}")
        except ImportError:
            self.error.emit("Install: pip install SpeechRecognition pyaudio")
        except OSError:
            self.error.emit("No microphone found")
        except Exception as e:
            self.error.emit(f"Voice error: {e}")
        finally:
            self._listening = False
            self.listening_changed.emit(False)
