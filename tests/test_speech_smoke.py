import io
import json
import os
import socket
import struct
import sys
import wave
from types import SimpleNamespace

import pytest

PHRASE = 'Move the blue button below the heading and keep sixteen pixels of spacing.'


@pytest.fixture
def speech_fixture(tmp_path, monkeypatch):
    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(offline, '_models', {})
    folder = offline.model_directory()
    folder.mkdir(parents=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (folder / name).write_text('synthetic model boundary', encoding='utf-8')
    wav_path = tmp_path / 'synthetic.wav'
    pcm = struct.pack('<1600h', *([200, -200] * 800))
    with wave.open(str(wav_path), 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    calls = []

    class Model:
        def __init__(self, path, **options):
            assert options['local_files_only'] is True

        def transcribe(self, audio, **options):
            # Only native inference is substituted. The real AudioFile and
            # transcribe_local WAV conversion must preserve the sample data.
            assert isinstance(audio, io.BytesIO)
            with wave.open(audio, 'rb') as source:
                assert source.getframerate() == 16000
                assert source.readframes(source.getnframes()) == pcm
            assert os.environ['HF_HUB_OFFLINE'] == '1'
            with socket.socket() as connection:
                with pytest.raises(OSError, match='disabled'):
                    connection.connect(('127.0.0.1', 9))
            calls.append(options)
            return iter([SimpleNamespace(text=PHRASE)]), None

    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    return SimpleNamespace(wav=wav_path, report=tmp_path / 'reports' / 'speech.json', calls=calls, model=Model)


def test_synthetic_wav_exercises_fixed_and_auto_runtime_without_network(speech_fixture):
    from arrow.speech.smoke import write_speech_report

    previous_environment = {name: os.environ.get(name) for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE')}
    original_connect = socket.socket.connect
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 0
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['success'] is True
    assert report['status'] == 'passed'
    assert report['synthetic_audio'] is True
    assert report['model_ready'] is True
    assert {mode: result['transcript'] for mode, result in report['modes'].items()} == {
        'en-US': PHRASE, 'auto': PHRASE,
    }
    assert [call['language'] for call in speech_fixture.calls] == ['en', None]
    assert speech_fixture.calls[1]['multilingual'] is True
    assert socket.socket.connect is original_connect
    assert {name: os.environ.get(name) for name in previous_environment} == previous_environment


@pytest.mark.parametrize('transcript', ['', 'Move the red button above the heading with six pixels.',
                                        'Blue button below heading with sixty pixels.',
                                        'Blueberry buttons below headings with 16 pixels.'])
def test_empty_or_wrong_instruction_fails_both_modes(speech_fixture, monkeypatch, transcript):
    from arrow.speech.smoke import write_speech_report

    monkeypatch.setattr(speech_fixture.model, 'transcribe',
                        lambda *args, **kwargs: (iter([SimpleNamespace(text=transcript)]), None))
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 1
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['status'] == 'unexpected_transcript'
    assert all(result['status'] == 'unexpected_transcript' for result in report['modes'].values())


def test_numeric_spacing_is_accepted(speech_fixture, monkeypatch):
    from arrow.speech.smoke import write_speech_report

    monkeypatch.setattr(speech_fixture.model, 'transcribe', lambda *args, **kwargs: (
        iter([SimpleNamespace(text='Move BLUE button below heading; keep 16 pixels.')]), None))
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 0


def test_auto_mode_failure_cannot_be_hidden_by_fixed_mode_success(speech_fixture, monkeypatch):
    from arrow.speech.smoke import write_speech_report

    def recognize(self, audio, **options):
        text = PHRASE if options['language'] == 'en' else 'Wrong instruction'
        return iter([SimpleNamespace(text=text)]), None

    monkeypatch.setattr(speech_fixture.model, 'transcribe', recognize)
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 1
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['modes']['en-US']['status'] == 'passed'
    assert report['modes']['auto']['status'] == 'unexpected_transcript'
    assert report['success'] is False


@pytest.mark.parametrize('damage', ['missing', 'garbage', 'empty', 'truncated'])
def test_invalid_wav_is_reported_without_inference(speech_fixture, damage):
    from arrow.speech.smoke import write_speech_report

    wav = speech_fixture.wav
    if damage == 'missing':
        wav.unlink()
    elif damage == 'garbage':
        wav.write_bytes(b'not a WAV')
    elif damage == 'truncated':
        wav.write_bytes(wav.read_bytes()[:-10])
    else:
        with wave.open(str(wav), 'wb') as output:
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
    assert write_speech_report(wav, speech_fixture.report) == 1
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['status'] == 'invalid_audio'
    assert report['error']
    assert speech_fixture.calls == []


def test_missing_model_is_not_downloaded(speech_fixture):
    from arrow.speech import offline
    from arrow.speech.smoke import write_speech_report

    (offline.model_directory() / 'model.bin').unlink()
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 1
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['status'] == 'model_unavailable'
    assert report['model_ready'] is False
    assert speech_fixture.calls == []


def test_corrupt_model_preserves_failure_and_restores_offline_guard(speech_fixture, monkeypatch):
    from arrow.speech.smoke import write_speech_report

    def corrupt(*args, **kwargs):
        raise ValueError('Invalid model fixture')

    monkeypatch.setattr(speech_fixture.model, '__init__', corrupt)
    monkeypatch.setenv('HF_HUB_OFFLINE', 'prior-value')
    monkeypatch.delenv('TRANSFORMERS_OFFLINE', raising=False)
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    assert write_speech_report(speech_fixture.wav, speech_fixture.report) == 1
    report = json.loads(speech_fixture.report.read_text(encoding='utf-8'))
    assert report['status'] == 'inference_failed'
    assert 'Invalid model fixture' in report['modes']['en-US']['error']
    assert (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo) == originals
    assert os.environ['HF_HUB_OFFLINE'] == 'prior-value'
    assert 'TRANSFORMERS_OFFLINE' not in os.environ
