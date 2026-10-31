import io
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlparse

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


@pytest.fixture
def model_download(tmp_path, monkeypatch):
    """Replace only the HTTP boundary; exercise real staging and publication."""
    import requests

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    files = {'model.bin': b'weights!', 'config.json': b'config', 'tokenizer.json': b'tokens'}
    calls = []

    class Response:
        def __init__(self, name=None):
            self.name = name
            self.headers = {'Content-Length': str(len(files[name]))} if name else {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def json(self):
            return {'sha': 'a' * 40, 'siblings': [{'rfilename': name, 'size': len(data)}
                                                 for name, data in files.items()]}

        def iter_content(self, chunk_size):
            yield files[self.name][:3]
            yield files[self.name][3:]

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs, self.trust_env))
            return Response(None if '/api/' in url else url.rsplit('/', 1)[-1])

    monkeypatch.setattr(requests, 'Session', Session)
    return SimpleNamespace(files=files, calls=calls, Response=Response)


def test_model_install_reports_actual_bytes_and_pins_an_anonymous_download(model_download, monkeypatch):
    import time

    from arrow.speech import offline

    monkeypatch.setattr(time, 'monotonic', lambda: 100.0)
    progress = []
    offline.install_voice_model(progress=progress.append)
    assert offline.voice_model_ready()
    assert (offline.model_directory() / 'model.bin').read_bytes() == b'weights!'
    assert [event['downloaded_bytes'] for event in progress if event['phase'] == 'downloading'] == [0, 20]
    assert progress[-1] == {'phase': 'ready', 'downloaded_bytes': 20, 'total_bytes': 20}
    for url, options, trust_env in model_download.calls:
        assert not trust_env  # Public requests cannot inherit credentials from .netrc.
        assert options['timeout'][0] <= 5 and options['timeout'][1] <= 5
        if '/resolve/' in url:
            assert '/resolve/' + 'a' * 40 + '/' in url


def test_model_download_uses_configured_proxy_and_ca_without_inheriting_auth(tmp_path, monkeypatch):
    import json

    import requests

    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    monkeypatch.setenv('HTTPS_PROXY', 'http://configured-proxy.example:8080')
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', '/configured/corporate-ca.pem')
    monkeypatch.setenv('HF_TOKEN', 'must-not-be-sent')
    monkeypatch.delenv('https_proxy', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    files = {'model.bin': b'weights', 'config.json': b'config', 'tokenizer.json': b'tokens'}
    transports = []

    def netrc_auth(*args, **kwargs):
        pytest.fail('Public model download must not read .netrc credentials')

    monkeypatch.setattr(requests.sessions, 'get_netrc_auth', netrc_auth)

    def send(adapter, request, **kwargs):
        transports.append((request, kwargs))
        name = urlparse(request.url).path.rsplit('/', 1)[-1]
        if '/api/' in request.url:
            content = json.dumps({'sha': 'b' * 40, 'siblings': [
                {'rfilename': filename, 'size': len(data)} for filename, data in files.items()
            ]}).encode()
        else:
            content = files[name]
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = content
        response._content_consumed = True
        response.headers['Content-Length'] = str(len(content))
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    offline.install_voice_model()
    assert offline.voice_model_ready()
    assert len(transports) == 4
    for request, options in transports:
        assert options['proxies']['https'] == 'http://configured-proxy.example:8080'
        assert options['verify'] == '/configured/corporate-ca.pem'
        assert 'Authorization' not in request.headers


def test_download_progress_is_throttled_without_losing_final_bytes(model_download, monkeypatch):
    import time

    from arrow.speech import offline

    model_download.files['model.bin'] = b'x' * (1024 * 1024)
    monkeypatch.setattr(time, 'monotonic', lambda: 100.0)

    def chunks(self, chunk_size):
        data = model_download.files[self.name]
        for offset in range(0, len(data), chunk_size):
            yield data[offset:offset + chunk_size]

    monkeypatch.setattr(model_download.Response, 'iter_content', chunks)
    progress = []
    offline.install_voice_model(progress=progress.append)
    downloads = [event['downloaded_bytes'] for event in progress if event['phase'] == 'downloading']
    assert downloads == [0, 262144, 524288, 786432, 1048576, 1048588]
    assert progress[-1] == {'phase': 'ready', 'downloaded_bytes': 1048588, 'total_bytes': 1048588}


def test_cancelled_repair_preserves_previous_model_and_allows_retry(model_download):
    from arrow.speech import offline

    offline.install_voice_model()
    before = {name: (offline.model_directory() / name).read_bytes() for name in model_download.files}
    cancel = threading.Event()

    def progress(event):
        if event['phase'] == 'downloading' and event['downloaded_bytes']:
            cancel.set()

    with pytest.raises(offline.DownloadCancelled):
        offline.install_voice_model(force=True, progress=progress, cancel_event=cancel)
    assert {name: (offline.model_directory() / name).read_bytes() for name in before} == before
    assert list(offline.model_directory().parent.iterdir()) == [offline.model_directory()]
    cancel.clear()
    offline.install_voice_model(force=True, cancel_event=cancel)
    assert offline.voice_model_ready()


def test_truncated_download_is_not_published_and_can_be_retried(model_download, monkeypatch):
    from arrow.speech import offline

    real_chunks = model_download.Response.iter_content
    monkeypatch.setattr(model_download.Response, 'iter_content', lambda self, **kw: iter([b'x']))
    with pytest.raises(offline.VoiceModelUnavailable, match='incomplete'):
        offline.install_voice_model()
    assert not offline.voice_model_ready()
    monkeypatch.setattr(model_download.Response, 'iter_content', real_chunks)
    offline.install_voice_model()
    assert offline.voice_model_ready()


def test_decoded_compressed_download_uses_manifest_size(model_download, monkeypatch):
    from arrow.speech import offline

    initialize = model_download.Response.__init__

    def compressed_response(self, name=None):
        initialize(self, name)
        if name:
            # requests.iter_content yields decoded data, while this header
            # describes the compressed wire representation.
            self.headers = {'Content-Length': '99', 'Content-Encoding': 'gzip'}

    monkeypatch.setattr(model_download.Response, '__init__', compressed_response)
    offline.install_voice_model()
    assert offline.voice_model_ready()
    assert (offline.model_directory() / 'model.bin').read_bytes() == b'weights!'


def test_cancel_before_download_makes_no_network_requests(model_download):
    from arrow.speech import offline

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(offline.DownloadCancelled):
        offline.install_voice_model(cancel_event=cancel)
    assert model_download.calls == []
    assert not offline.voice_model_ready()


def test_cancel_during_stalled_download_reports_cancel_and_removes_staging(model_download, monkeypatch):
    import requests

    from arrow.speech import offline

    cancel = threading.Event()

    def stalled(self, **kwargs):
        cancel.set()
        raise requests.ReadTimeout('Stalled connection')

    monkeypatch.setattr(model_download.Response, 'iter_content', stalled)
    with pytest.raises(offline.DownloadCancelled):
        offline.install_voice_model(cancel_event=cancel)
    assert not offline.voice_model_ready()
    assert list(offline.model_directory().parent.iterdir()) == []


def test_cancel_before_publication_keeps_previous_model(model_download):
    from arrow.speech import offline

    offline.install_voice_model()
    target = offline.model_directory()
    (target / 'model.bin').write_bytes(b'old model')
    cancel = threading.Event()

    def progress(event):
        if event['phase'] == 'installing':
            cancel.set()

    with pytest.raises(offline.DownloadCancelled):
        offline.install_voice_model(force=True, progress=progress, cancel_event=cancel)
    assert (target / 'model.bin').read_bytes() == b'old model'


def test_failed_publication_rolls_back_previous_model(model_download, monkeypatch):
    from arrow.speech import offline

    offline.install_voice_model()
    target = offline.model_directory()
    original = (target / 'model.bin').read_bytes()
    replace = offline.os.replace

    def fail_new_model(source, destination):
        if str(source).endswith('staged'):
            raise OSError('Disk full')
        return replace(source, destination)

    monkeypatch.setattr(offline.os, 'replace', fail_new_model)
    with pytest.raises(offline.VoiceModelUnavailable, match='Retry'):
        offline.install_voice_model(force=True)
    assert offline.voice_model_ready()
    assert (target / 'model.bin').read_bytes() == original


@pytest.mark.parametrize('language, expected', [('auto', None), ('hi-IN', 'hi'), ('en-IN', 'en'), ('en-US', 'en')])
def test_language_selection_allows_local_multilingual_detection(tmp_path, monkeypatch, language, expected):
    from arrow.speech import offline

    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    folder = offline.model_directory()
    folder.mkdir(parents=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (folder / name).write_text('fixture')
    options = []

    class Model:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, data, **kwargs):
            options.append(kwargs)
            return iter([SimpleNamespace(text='यह button move करो')]), None

    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    audio = SimpleNamespace(get_wav_data=lambda **kw: b'fixture')
    assert offline.transcribe_local(audio, language) == 'यह button move करो'
    assert options[0]['language'] == expected
    assert options[0]['task'] == 'transcribe'


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
