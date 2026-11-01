"""Opt-in synthetic WAV validation of the local speech runtime, without Qt or a microphone."""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from arrow.speech.offline import transcribe_local, voice_model_ready

_OFFLINE_ENV = ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE')
_EXPECTED_WORDS = {'blue', 'button', 'below', 'heading'}


@contextmanager
def _offline_inference() -> Iterator[None]:
    """Process-wide guard for this opt-in command's fresh, single-purpose process.

    Environment flags prevent Hugging Face fetches; socket hooks also reject
    Python network connections even if a dependency ignores those flags.
    """
    environment = {name: os.environ.get(name) for name in _OFFLINE_ENV}
    hooks: list[tuple[Any, str]] = [(socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                                   (socket, 'create_connection'), (socket, 'getaddrinfo')]
    originals = [(owner, name, getattr(owner, name)) for owner, name in hooks]

    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise OSError('Network connections are disabled during the offline speech smoke test')

    try:
        for name in _OFFLINE_ENV:
            os.environ[name] = '1'
        for owner, name, _ in originals:
            setattr(owner, name, disabled)
        yield
    finally:
        for owner, name, original in originals:
            setattr(owner, name, original)
        for name, previous in environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


def _read_audio(path: Path) -> Any:
    import speech_recognition as sr

    # AudioFile alone tolerates a truncated data chunk. Reject an incomplete or
    # empty fixture so a decoder hallucination cannot turn it into a pass.
    with wave.open(str(path), 'rb') as source:
        expected = source.getnframes() * source.getnchannels() * source.getsampwidth()
        if expected == 0 or len(source.readframes(source.getnframes())) != expected:
            raise ValueError('Synthetic WAV is empty or its PCM data is truncated')
    with sr.AudioFile(str(path)) as source:
        return sr.Recognizer().record(source)


def _error_detail(error: Exception) -> str:
    details = []
    current: BaseException | None = error
    while current is not None:
        details.append(f'{type(current).__name__}: {current}')
        current = current.__cause__
    return ' <- '.join(details)


def write_speech_report(wav_path: Path, report_path: Path) -> int:
    """Return 0 only when fixed English and auto modes decode the fixture meaning.

    The supplied audio must be the synthetic English instruction produced by
    scripts/create-speech-fixture.ps1. Transcripts are deliberately included in
    this opt-in report; this is not the app's normal privacy-safe diagnostic.
    No setup/download is attempted. Run in a fresh source or frozen process.
    """
    report: dict[str, Any] = {
        'success': False, 'status': 'invalid_audio', 'synthetic_audio': True,
        'scope': 'Synthetic English WAV only; no physical microphone, Hinglish, or real-world accuracy validation.',
        'frozen': bool(getattr(sys, 'frozen', False)), 'platform': platform.system(),
        'python': platform.python_version(), 'model_ready': voice_model_ready(), 'modes': {},
    }
    try:
        audio = _read_audio(Path(wav_path))
    except Exception as error:
        report['error'] = _error_detail(error)
    else:
        if not report['model_ready']:
            report['status'] = 'model_unavailable'
            report['error'] = 'Offline voice model is missing or incomplete; explicitly install it before this check.'
        else:
            with _offline_inference():
                for language in ('en-US', 'auto'):
                    result: dict[str, Any] = {'status': 'inference_failed'}
                    try:
                        transcript = transcribe_local(audio, language)
                        result['transcript'] = transcript
                        words = set(re.findall(r'\b\w+\b', transcript.lower()))
                        missing = sorted(_EXPECTED_WORDS - words)
                        if not {'sixteen', '16'} & words:
                            missing.append('sixteen/16')
                        if missing:
                            result.update(status='unexpected_transcript',
                                          error=f'Synthetic instruction is missing expected words: {", ".join(missing)}')
                        else:
                            result['status'] = 'passed'
                    except Exception as error:
                        result['error'] = _error_detail(error)
                    report['modes'][language] = result
            failures = [result['status'] for result in report['modes'].values() if result['status'] != 'passed']
            report['success'] = not failures
            report['status'] = failures[0] if failures else 'passed'
    destination = Path(report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    return 0 if report['success'] else 1
