"""Explicit model installation and strictly local CPU speech recognition."""
import io
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from arrow.core.paths import application_home

MODEL_REPOSITORY = 'Systran/faster-whisper-base'
_REQUIRED_FILES = ('model.bin', 'config.json', 'tokenizer.json')
_lock = threading.RLock()
_install_lock = threading.Lock()
_models: dict[str, Any] = {}


class VoiceModelUnavailable(RuntimeError):
    pass


class DownloadCancelled(VoiceModelUnavailable):
    """An explicitly cancelled setup action; existing weights remain usable."""


def model_directory() -> Path:
    return application_home() / 'models' / 'whisper-base'


def voice_model_ready() -> bool:
    # Readiness is queried from the GUI while recognition holds _lock. Avoid
    # waiting for CPU inference; publication may briefly report unavailable.
    try:
        return all((model_directory() / name).is_file() and (model_directory() / name).stat().st_size > 0
                   for name in _REQUIRED_FILES)
    except OSError:
        return False


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled('Voice model download cancelled. You can retry in Settings → Capture.')


@contextmanager
def _cancellable_lock(lock, cancel_event):
    while not lock.acquire(timeout=0.1):
        _check_cancel(cancel_event)
    try:
        _check_cancel(cancel_event)
        yield
    finally:
        lock.release()


def install_voice_model(*, force: bool = False, progress: Callable[[dict], None] | None = None,
                        cancel_event: threading.Event | None = None) -> None:
    """Explicitly download public weights, publishing only a complete model.

    ``progress`` runs on the calling thread with a dict containing ``phase``
    (checking/downloading/installing/ready), actual ``downloaded_bytes`` and
    ``total_bytes`` (None if the server omits sizes). Cancellation is checked
    between chunks and lock waits; network connect/read timeouts are 5/2 seconds.
    Download callbacks are limited to 100 ms or 256 KiB increments, with final
    byte counts and phase changes always reported. Configured environment
    proxies/custom CA bundles are supported without inherited service credentials.
    A cancelled or failed repair keeps the previous model and permits retry.
    """
    import requests

    downloaded = 0
    total = None
    last_phase = None
    last_bytes = 0
    last_time = 0.0

    def report(phase, *, force=False):
        nonlocal last_phase, last_bytes, last_time
        if progress is not None:
            now = time.monotonic()
            if (not force and phase == 'downloading' and phase == last_phase
                    and downloaded - last_bytes < 256 * 1024 and now - last_time < 0.1):
                return
            progress({'phase': phase, 'downloaded_bytes': downloaded, 'total_bytes': total})
            last_phase, last_bytes, last_time = phase, downloaded, now

    def network_options(url):
        # trust_env stays disabled so requests never loads .netrc credentials.
        # Forward only the user's transport configuration, including NO_PROXY.
        return {'proxies': requests.utils.get_environ_proxies(url),
                'verify': os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('CURL_CA_BUNDLE') or True}

    try:
        with _cancellable_lock(_install_lock, cancel_event):
            if voice_model_ready() and not force:
                report('ready')
                return
            report('checking')
            parent = model_directory().parent
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='voice-download-', dir=parent) as temporary, requests.Session() as session:
                # Anonymous public requests must not inherit .netrc credentials.
                session.trust_env = False
                _check_cancel(cancel_event)
                metadata_url = f'https://huggingface.co/api/models/{MODEL_REPOSITORY}'
                with session.get(metadata_url, params={'blobs': 'true'}, timeout=(5, 2),
                                 **network_options(metadata_url)) as response:
                    response.raise_for_status()
                    metadata = response.json()
                _check_cancel(cancel_event)
                revision = metadata['sha']
                if not isinstance(revision, str) or len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
                    raise ValueError('Invalid model revision')
                files = {}
                for item in metadata['siblings']:
                    name = item['rfilename']
                    if isinstance(name, str) and '/' not in name and '\\' not in name and (
                            name == 'model.bin' or name.endswith('.json') or name.startswith('vocabulary.')):
                        size = item.get('size')
                        files[name] = size if isinstance(size, int) and size > 0 else None
                if not all(name in files for name in _REQUIRED_FILES):
                    raise VoiceModelUnavailable('Voice model download was incomplete. Retry in Settings → Capture.')
                total = (sum(size for size in files.values() if size is not None)
                         if all(size is not None for size in files.values()) else None)
                report('downloading')
                staging = Path(temporary) / 'staged'
                staging.mkdir()
                for name, expected_size in files.items():
                    _check_cancel(cancel_event)
                    url = f'https://huggingface.co/{MODEL_REPOSITORY}/resolve/{revision}/{quote(name, safe="")}'
                    with session.get(url, stream=True, timeout=(5, 2), headers={'Accept-Encoding': 'identity'},
                                     **network_options(url)) as response:
                        response.raise_for_status()
                        received = 0
                        with (staging / name).open('wb') as stream:
                            for chunk in response.iter_content(chunk_size=16 * 1024):
                                _check_cancel(cancel_event)
                                if chunk:
                                    stream.write(chunk)
                                    received += len(chunk)
                                    downloaded += len(chunk)
                                    report('downloading')
                        header_size = response.headers.get('Content-Length')
                        # requests decodes transfer compression before yielding
                        # chunks; Content-Length then describes different bytes.
                        if response.headers.get('Content-Encoding', 'identity') != 'identity':
                            header_size = None
                        if (not received or (expected_size is not None and received != expected_size)
                                or (header_size and received != int(header_size))):
                            raise VoiceModelUnavailable('Voice model download was incomplete. Retry in Settings → Capture.')
                if downloaded != last_bytes:
                    report('downloading', force=True)
                report('installing')
                with _cancellable_lock(_lock, cancel_event):
                    target = model_directory()
                    backup = Path(temporary) / 'previous'
                    if target.exists():
                        os.replace(target, backup)
                    try:
                        os.replace(staging, target)
                    except OSError:
                        if backup.exists():
                            os.replace(backup, target)
                        raise
                    _models.pop(str(target), None)
                report('ready')
    except (DownloadCancelled, VoiceModelUnavailable):
        raise
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException) as error:
        _check_cancel(cancel_event)
        raise VoiceModelUnavailable('Voice model download failed. Check your connection and free disk space, then Retry in Settings → Capture.') from error


def transcribe_local(audio, language: str) -> str:
    """Decode audio locally. Missing weights never trigger a network download."""
    if not voice_model_ready():
        raise VoiceModelUnavailable('Offline voice model is missing. Open Settings → Capture → Download voice model, or type your instruction.')
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise VoiceModelUnavailable('Offline speech runtime is missing. Install the latest Arrow setup or the speech extra.') from error
    path = str(model_directory())
    try:
        with _lock:
            if not voice_model_ready():
                raise VoiceModelUnavailable('Offline voice model is missing. Open Settings → Capture → Download voice model, or type your instruction.')
            if path not in _models:
                _models[path] = WhisperModel(path, device='cpu', compute_type='int8', local_files_only=True,
                                            cpu_threads=min(4, os.cpu_count() or 1), num_workers=1)
            wave = io.BytesIO(audio.get_wav_data(convert_rate=16000, convert_width=2))
            segments, _ = _models[path].transcribe(wave, language=None if language == 'auto' else ('hi' if language == 'hi-IN' else 'en'),
                                                 task='transcribe', multilingual=language == 'auto',
                                                 beam_size=3, condition_on_previous_text=False)
            return ' '.join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    except VoiceModelUnavailable:
        raise
    except Exception as error:
        raise VoiceModelUnavailable('Offline speech failed. Try Settings → Capture → Repair voice model, or type your instruction.') from error
