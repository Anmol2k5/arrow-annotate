"""Stable input descriptions; enumerating devices never opens a recording stream."""
from collections import Counter


class MicrophoneUnavailable(RuntimeError):
    """An input cannot be safely opened; the message gives a recovery action."""


RUNTIME_ERROR = 'Microphone runtime is missing. Install the latest Arrow setup or SpeechRecognition and PyAudio.'
PERMISSION_ERROR = ('Microphone permission was denied. Enable microphone access for desktop apps in Windows Settings '
                    '→ Privacy & security → Microphone, then retry.')
UNAVAILABLE_ERROR = ('Microphone is unavailable. Connect or enable your input, then refresh and select it in '
                     'Settings → Capture → Microphone. Also check Windows Settings → Privacy & security '
                     '→ Microphone for desktop-app access.')


def _input_devices(audio) -> list[dict]:
    inputs = []
    for index in range(audio.get_device_count()):
        device = audio.get_device_info_by_index(index)
        if device.get('maxInputChannels', 0) <= 0:
            continue
        host_api = audio.get_host_api_info_by_index(device['hostApi'])['name']
        inputs.append({'index': index, 'name': device['name'], 'host_api': host_api})
    counts = Counter((item['name'], item['host_api']) for item in inputs)
    return [dict(item, ambiguous=counts[(item['name'], item['host_api'])] > 1) for item in inputs]


def list_input_devices() -> list[dict]:
    """Return current PortAudio input indices and stable name/host API descriptions."""
    audio = None
    try:
        import pyaudio

        audio = pyaudio.PyAudio()
        return _input_devices(audio)
    except (ImportError, AttributeError) as error:
        raise MicrophoneUnavailable(RUNTIME_ERROR) from error
    except PermissionError as error:
        raise MicrophoneUnavailable(PERMISSION_ERROR) from error
    except OSError as error:
        raise MicrophoneUnavailable(UNAVAILABLE_ERROR) from error
    finally:
        if audio is not None:
            audio.terminate()


def resolve_input_device(selection: dict | None, *, audio=None) -> int | None:
    """Resolve a fresh index, rejecting disappeared or indistinguishable inputs."""
    if selection is None:
        return None
    matches = [item for item in (list_input_devices() if audio is None else _input_devices(audio))
               if item['name'] == selection.get('name') and item['host_api'] == selection.get('host_api')]
    if not matches:
        raise MicrophoneUnavailable('Selected microphone is unavailable. Reconnect it, or refresh and choose an input '
                                    'in Settings → Capture → Microphone.')
    if len(matches) != 1:
        raise MicrophoneUnavailable('Selected microphone is ambiguous: multiple inputs have the same name and host API. '
                                    'Choose another input or System default in Settings → Capture → Microphone.')
    return matches[0]['index']
