"""Explicit model installation and strictly local CPU speech recognition."""
import io
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from arrow.core.paths import application_home

MODEL_REPOSITORY = 'Systran/faster-whisper-base'
_REQUIRED_FILES = ('model.bin', 'config.json', 'tokenizer.json')
_lock = threading.Lock()
_models: dict[str, Any] = {}


class VoiceModelUnavailable(RuntimeError):
    pass


def model_directory() -> Path:
    return application_home() / 'models' / 'whisper-base'


def voice_model_ready() -> bool:
    return all((model_directory() / name).is_file() and (model_directory() / name).stat().st_size > 0
               for name in _REQUIRED_FILES)


def install_voice_model(*, force: bool = False) -> None:
    """Download public model weights only after an explicit setup action."""
    if voice_model_ready() and not force:
        return
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise VoiceModelUnavailable('Install Arrow with its speech dependencies, then use Settings → Capture → Download voice model.') from error
    parent = model_directory().parent
    parent.mkdir(parents=True, exist_ok=True)
    with _lock, tempfile.TemporaryDirectory(prefix='voice-download-', dir=parent) as temporary:
        snapshot_download(repo_id=MODEL_REPOSITORY, local_dir=temporary, token=False,
                          allow_patterns=['*.json', 'model.bin', 'vocabulary.*'])
        if not all((Path(temporary) / name).is_file() and (Path(temporary) / name).stat().st_size > 0
                   for name in _REQUIRED_FILES):
            raise VoiceModelUnavailable('Voice model download was incomplete. Retry in Settings → Capture.')
        target = model_directory()
        if target.exists():
            shutil.rmtree(target)
        os.replace(temporary, target)
        _models.pop(str(target), None)


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
            if path not in _models:
                _models[path] = WhisperModel(path, device='cpu', compute_type='int8', local_files_only=True,
                                            cpu_threads=min(4, os.cpu_count() or 1), num_workers=1)
            wave = io.BytesIO(audio.get_wav_data(convert_rate=16000, convert_width=2))
            segments, _ = _models[path].transcribe(wave, language='hi' if language == 'hi-IN' else 'en',
                                                 beam_size=3, condition_on_previous_text=False)
            return ' '.join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    except Exception as error:
        raise VoiceModelUnavailable('Offline speech failed. Try Settings → Capture → Repair voice model, or type your instruction.') from error
