import logging
import math
import struct
import threading
import time
from contextlib import contextmanager

from PyQt6.QtCore import QObject, pyqtSignal

from arrow.speech.microphone import (
    PERMISSION_ERROR,
    RUNTIME_ERROR,
    UNAVAILABLE_ERROR,
    MicrophoneUnavailable,
    resolve_input_device,
)
from arrow.speech.offline import VoiceModelUnavailable, transcribe_local
from arrow.storage.settings import get_microphone_selection

logger = logging.getLogger("arrow.ui.voice_input")

_SAVED_MICROPHONE = object()
_MICROPHONE_LOCK = threading.Lock()
_DEVICE_WAIT_SECONDS = 5.0


@contextmanager
def _open_microphone(microphone, selection=None):
    # SpeechRecognition's __enter__ swallows PortAudio.open errors, returning a
    # source with stream=None. Open its native stream here so permission/device
    # errors reach the caller, and every successful PyAudio instance terminates.
    if not hasattr(microphone, 'pyaudio_module'):
        with microphone as source:
            yield source
        return
    audio = microphone.pyaudio_module.PyAudio()
    stream = None
    try:
        if selection is not None:
            # Re-resolve in the SAME PortAudio instance used for open. USB
            # hotplug can change indices across the earlier metadata queries.
            microphone.device_index = resolve_input_device(selection, audio=audio)
            sample_rate = audio.get_device_info_by_index(microphone.device_index)['defaultSampleRate']
            if not isinstance(sample_rate, (int, float)) or not math.isfinite(sample_rate) or sample_rate <= 0:
                raise MicrophoneUnavailable(UNAVAILABLE_ERROR)
            microphone.SAMPLE_RATE = int(sample_rate)
        stream = type(microphone).MicrophoneStream(audio.open(
            input_device_index=microphone.device_index, channels=1, format=microphone.format,
            rate=microphone.SAMPLE_RATE, frames_per_buffer=microphone.CHUNK, input=True,
        ))
        microphone.stream = stream
        yield microphone
    finally:
        try:
            if stream is not None:
                stream.close()
        finally:
            microphone.stream = None
            audio.terminate()


class VoiceInput(QObject):
    """Record while held, then recognize the complete recording after release."""

    result_ready = pyqtSignal(str, str)
    error = pyqtSignal(str, str)
    finished = pyqtSignal(str, str, str)
    listening_changed = pyqtSignal(bool)
    phase_changed = pyqtSignal(str, str)
    audio_level = pyqtSignal(float, str)

    def __init__(self, language: str = 'auto', *, microphone_selection=_SAVED_MICROPHONE,
                 max_recording_seconds: float | None = None):
        super().__init__()
        if max_recording_seconds is not None and (
                not math.isfinite(max_recording_seconds) or max_recording_seconds <= 0):
            raise ValueError('Recording limit must be a positive finite duration')
        self._max_recording_seconds = max_recording_seconds
        self.language = language
        self._microphone_selection = (dict(microphone_selection) if isinstance(microphone_selection, dict)
                                      else microphone_selection)
        self._listening = False
        self._active = False
        self._thread: threading.Thread | None = None
        self.current_capture_id = ""
        self._generation = 0
        self._state_lock = threading.RLock()
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
            selection = (get_microphone_selection() if self._microphone_selection is _SAVED_MICROPHONE
                         else self._microphone_selection)
            selection = dict(selection) if selection is not None else None
            self.phase_changed.emit('opening', capture_id)
            self._thread = threading.Thread(
                target=self._listen,
                args=(capture_id, generation, finish_requested, self.language, selection),
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
            if self._active:
                self.phase_changed.emit('idle', self.current_capture_id)
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
            self.phase_changed.emit('idle', capture_id)
            # Publish exactly once, while holding the generation guard. Qt
            # delivers these signals to GUI slots on the GUI thread.
            if error:
                self.error.emit(error, capture_id)
            else:
                self.result_ready.emit(text, capture_id)
            self.finished.emit(text, error, capture_id)

    def _acquire_microphone(self, generation: int) -> bool:
        deadline = time.monotonic() + _DEVICE_WAIT_SECONDS
        while self._is_current(generation):
            if _MICROPHONE_LOCK.acquire(timeout=0.05):
                return True
            if time.monotonic() >= deadline:
                raise MicrophoneUnavailable('Microphone is busy. Stop the other recording or close the app using it, '
                                            'then retry.')
        return False

    def _listen(self, capture_id: str, generation: int, finish_requested: threading.Event,
                language: str, selection: dict | None):
        transcript = ''
        error = ''
        stage = 'opening'
        try:
            import speech_recognition as sr

            frames = []
            # All instances share device ownership, including microphone tests.
            # Release it before inference, and let cancelled waiters exit promptly.
            if not self._acquire_microphone(generation):
                return
            try:
                if not self._is_current(generation):
                    return
                index = resolve_input_device(selection)
                if not self._is_current(generation):
                    return
                microphone = sr.Microphone() if index is None else sr.Microphone(device_index=index)
                with _open_microphone(microphone, selection) as source:
                    with self._state_lock:
                        if not self._is_current(generation):
                            return
                        self._set_listening(True)
                        self.phase_changed.emit('recording', capture_id)
                    stage = 'recording'
                    last_level = float('-inf')
                    deadline = (time.monotonic() + self._max_recording_seconds
                                if self._max_recording_seconds is not None else None)
                    while not finish_requested.is_set() and (deadline is None or time.monotonic() < deadline):
                        frame = source.stream.read(source.CHUNK)
                        if not self._is_current(generation):
                            return
                        if not frame:
                            break
                        # Release during a pending read must retain its final chunk.
                        frames.append(frame)
                        now = time.monotonic()
                        if source.SAMPLE_WIDTH == 2 and len(frame) >= 2 and now - last_level >= 0.1:
                            samples = struct.iter_unpack('<h', frame[:len(frame) // 2 * 2])
                            level = min(1.0, math.sqrt(sum(value * value for (value,) in samples)
                                                      / (len(frame) // 2)) / 32768)
                            with self._state_lock:
                                if self._is_current(generation):
                                    self.audio_level.emit(level, capture_id)
                            last_level = now
                    pcm = b''.join(frames)
                    sample_width = source.SAMPLE_WIDTH
                    audio = sr.AudioData(pcm, source.SAMPLE_RATE, sample_width)
            finally:
                _MICROPHONE_LOCK.release()
                with self._state_lock:
                    if self._is_current(generation):
                        self._set_listening(False)
            if not self._is_current(generation):
                return
            if not frames:
                error = 'No audio recorded. Hold the shortcut or start the microphone test, then speak and retry.'
            elif sample_width == 2 and len(pcm) >= 2 and not any(pcm):
                error = ('No microphone signal detected. Check mute, input volume and your selected microphone '
                         'in Settings → Capture, then retry.')
            else:
                with self._state_lock:
                    if not self._is_current(generation):
                        return
                    self.phase_changed.emit('transcribing', capture_id)
                stage = 'transcribing'
                transcript = transcribe_local(audio, language)
                if not transcript:
                    error = 'Could not understand audio'
        except (VoiceModelUnavailable, MicrophoneUnavailable) as exc:
            error = str(exc)
        except ImportError:
            error = RUNTIME_ERROR
        except PermissionError:
            error = PERMISSION_ERROR
        except AttributeError as exc:
            error = (RUNTIME_ERROR if 'pyaudio' in str(exc).lower()
                     else 'Microphone recording failed. Retry or choose another input in Settings → Capture.')
        except OSError:
            error = (UNAVAILABLE_ERROR if stage == 'opening' else
                     'Microphone stream failed. Check the input connection and close other apps using it, then retry.')
        except Exception as exc:
            # Exception details can contain recognized text from a decoder.
            logger.warning('Voice input failed for capture %s (%s)', capture_id, type(exc).__name__)
            error = 'Voice recording failed. Check your microphone and local voice model in Settings → Capture.'
        self._complete(transcript, error, capture_id, generation)
