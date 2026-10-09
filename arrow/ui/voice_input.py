import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("arrow.ui.voice_input")


class VoiceInput(QObject):
    """Microphone capture with generation-based cancellation.

    Each listening session gets a generation number. A session may only
    touch shared state or emit results while it is still the serving
    generation — so a slow thread from a cancelled session can never clobber
    the state of the session that replaced it (the audit's
    ``finally: self._listening = False`` race).
    """

    # Emits (transcript_text, capture_id)
    result_ready = pyqtSignal(str, str)
    # Emits (error_message, capture_id)
    error = pyqtSignal(str, str)
    listening_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._listening = False
        # Bumped whenever in-flight sessions must be invalidated (stop or a
        # fresh spawn). _thread_gen is the generation of the alive thread.
        self._generation = 0
        self._thread_gen = -1
        # "idle" | "mic" (thread holds / is opening the microphone) |
        # "recognize" (microphone released, result pending)
        self._phase = "idle"
        self._thread: threading.Thread | None = None
        self._recognizer = None
        self.current_capture_id = ""

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def phase(self) -> str:
        return self._phase

    def start_listening(self, capture_id: str):
        emit_changed = False
        with self._lock:
            self.current_capture_id = capture_id
            thread_alive = self._thread is not None and self._thread.is_alive()

            if thread_alive and self._phase == "mic":
                # A microphone session is already capturing: reassign it to
                # the new capture instead of opening a second microphone
                # (which fails on Windows while the first one is held).
                self._generation = self._thread_gen
                self._listening = True
                emit_changed = True
            else:
                # Either nothing is running, or the old thread is past the
                # microphone (recognize phase) and about to exit: spawn fresh.
                self._generation += 1
                gen = self._generation
                self._thread_gen = gen
                self._phase = "mic"
                self._listening = True
                self._thread = threading.Thread(
                    target=self._listen, args=(gen,), daemon=True
                )
                self._thread.start()
                emit_changed = True
        if emit_changed:
            self.listening_changed.emit(True)

    def stop_listening(self):
        with self._lock:
            # Invalidate any in-flight session: its results and its finally
            # block become no-ops, so it cannot clobber the next session.
            self._generation += 1
            was_listening = self._listening
            self._listening = False
        if was_listening:
            self.listening_changed.emit(False)

    def _serving(self, gen: int) -> bool:
        with self._lock:
            return gen == self._generation and self._listening

    def _listen(self, gen: int):
        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            self._recognizer = recognizer
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                # Listen with timeouts to avoid blocking forever
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=8)

            with self._lock:
                # Microphone released; results are pending.
                if gen == self._generation:
                    self._phase = "recognize"
                capture_id = self.current_capture_id

            if not self._serving(gen):
                logger.info(
                    "Discarding voice input because session %s was cancelled or superseded",
                    gen,
                )
                return

            try:
                text = recognizer.recognize_google(audio)
                if self._serving(gen):
                    with self._lock:
                        capture_id = self.current_capture_id
                    self.result_ready.emit(text, capture_id)
            except sr.UnknownValueError:
                if self._serving(gen):
                    with self._lock:
                        capture_id = self.current_capture_id
                    self.error.emit("Could not understand audio", capture_id)
            except sr.RequestError as e:
                if self._serving(gen):
                    with self._lock:
                        capture_id = self.current_capture_id
                    self.error.emit(f"Speech recognition error: {e}", capture_id)
        except ImportError:
            if self._serving(gen):
                with self._lock:
                    capture_id = self.current_capture_id
                self.error.emit("Install: pip install SpeechRecognition pyaudio", capture_id)
        except OSError:
            if self._serving(gen):
                with self._lock:
                    capture_id = self.current_capture_id
                self.error.emit("No microphone found", capture_id)
        except sr.WaitTimeoutError:
            # Benign: no speech arrived within listen()'s timeout. Stop this
            # session cleanly without cancelling the capture — the user can
            # still finish with the mouse or a typed instruction.
            if self._serving(gen):
                logger.info("No speech detected within timeout; stopping voice session")
        except Exception as e:
            if self._serving(gen):
                with self._lock:
                    capture_id = self.current_capture_id
                self.error.emit(f"Voice error: {e}", capture_id)
        finally:
            with self._lock:
                # Only the session that is still current may reset shared
                # state; a superseded session exits without touching it.
                current = gen == self._generation
                was_listening = False
                if current:
                    self._phase = "idle"
                    self._thread = None
                    was_listening = self._listening
                    self._listening = False
                elif self._thread is threading.current_thread():
                    # Superseded and nothing newer replaced this thread:
                    # release the bookkeeping without touching _listening.
                    self._thread = None
                    self._phase = "idle"
            if current and was_listening:
                self.listening_changed.emit(False)
