import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_local_transcription_never_fetches_a_model_or_calls_a_speech_service(tmp_path, monkeypatch):
    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    folder = offline.model_directory()
    folder.mkdir(parents=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (folder / name).write_text('fixture')
    loads, requests = [], []

    class Model:
        def __init__(self, path, **kwargs):
            loads.append((path, kwargs))

        def transcribe(self, data, **kwargs):
            assert isinstance(data, io.BytesIO)
            requests.append(kwargs)
            return iter([SimpleNamespace(text=' Move this'), SimpleNamespace(text=' button here.')]), None

    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    audio = SimpleNamespace(get_wav_data=lambda **kw: b'RIFF audio fixture')
    assert offline.transcribe_local(audio, 'hi-IN') == 'Move this button here.'
    assert loads[0][0] == str(folder)
    assert loads[0][1]['local_files_only'] is True
    assert loads[0][1]['device'] == 'cpu'
    assert requests[0]['language'] == 'hi'


def test_missing_voice_model_is_an_actionable_local_error(tmp_path, monkeypatch):
    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    with pytest.raises(offline.VoiceModelUnavailable, match='Settings'):
        offline.transcribe_local(SimpleNamespace(), 'en-IN')
    assert not list(tmp_path.iterdir())


def test_model_install_is_explicit_anonymous_and_uses_a_staging_directory(tmp_path, monkeypatch):
    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    downloads = []

    def download(**kwargs):
        downloads.append(kwargs)
        directory = Path(kwargs['local_dir'])
        for name in ('model.bin', 'config.json', 'tokenizer.json'):
            (directory / name).write_text('weights')

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=download))
    offline.install_voice_model()
    assert offline.voice_model_ready()
    assert downloads[0]['token'] is False
    assert Path(downloads[0]['local_dir']) != offline.model_directory()


def test_corrupt_voice_model_reports_repair_instead_of_a_microphone_error(tmp_path, monkeypatch):
    from arrow.speech import offline
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    folder = offline.model_directory()
    folder.mkdir(parents=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (folder / name).write_text('invalid model')
    def broken_model(*args, **kwargs):
        raise OSError('Invalid model file')
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=broken_model))
    with pytest.raises(offline.VoiceModelUnavailable, match='Repair voice model'):
        offline.transcribe_local(SimpleNamespace(), 'en-IN')
