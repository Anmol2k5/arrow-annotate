"""Device inventory is mocked at PortAudio: no real device opens in these tests."""
import importlib
import sys
from types import SimpleNamespace

import pytest


def install_portaudio(monkeypatch, devices, *, failure=None):
    terminated = []

    class PortAudio:
        def get_device_count(self):
            return len(devices)

        def get_device_info_by_index(self, index):
            if failure:
                raise failure
            return devices[index]

        def get_host_api_info_by_index(self, index):
            return {'name': {0: 'Windows WASAPI', 1: 'MME'}[index]}

        def terminate(self):
            terminated.append(True)

    monkeypatch.setitem(sys.modules, 'pyaudio', SimpleNamespace(PyAudio=PortAudio))
    return terminated


def microphone():
    return importlib.import_module('arrow.speech.microphone')


def test_inventory_filters_outputs_and_flags_duplicate_descriptions(monkeypatch):
    terminated = install_portaudio(monkeypatch, [
        {'name': 'Speakers', 'maxInputChannels': 0, 'hostApi': 0},
        {'name': 'USB Mic', 'maxInputChannels': 1, 'hostApi': 0},
        {'name': 'USB Mic', 'maxInputChannels': 1, 'hostApi': 0},
        {'name': 'USB Mic', 'maxInputChannels': 1, 'hostApi': 1},
    ])
    assert microphone().list_input_devices() == [
        {'index': 1, 'name': 'USB Mic', 'host_api': 'Windows WASAPI', 'ambiguous': True},
        {'index': 2, 'name': 'USB Mic', 'host_api': 'Windows WASAPI', 'ambiguous': True},
        {'index': 3, 'name': 'USB Mic', 'host_api': 'MME', 'ambiguous': False},
    ]
    assert terminated == [True]


def test_selection_resolves_again_after_portaudio_index_reorders(monkeypatch):
    devices = [{'name': 'USB Mic', 'maxInputChannels': 1, 'hostApi': 0}]
    install_portaudio(monkeypatch, devices)
    selected = {'name': 'USB Mic', 'host_api': 'Windows WASAPI'}
    assert microphone().resolve_input_device(selected) == 0
    devices.insert(0, {'name': 'Headset', 'maxInputChannels': 1, 'hostApi': 0})
    assert microphone().resolve_input_device(selected) == 1
    assert microphone().resolve_input_device(None) is None


@pytest.mark.parametrize('devices, word', [
    ([], 'unavailable'),
    ([{'name': 'USB Mic', 'maxInputChannels': 1, 'hostApi': 0}] * 2, 'ambiguous'),
])
def test_missing_or_ambiguous_selection_never_silently_uses_default(monkeypatch, devices, word):
    install_portaudio(monkeypatch, devices)
    with pytest.raises(microphone().MicrophoneUnavailable, match=word):
        microphone().resolve_input_device({'name': 'USB Mic', 'host_api': 'Windows WASAPI'})


@pytest.mark.parametrize('failure, word', [
    (PermissionError('denied'), 'permission'),
    (OSError('PortAudio failure'), 'unavailable'),
])
def test_inventory_failure_is_actionable_and_always_terminates(monkeypatch, failure, word):
    terminated = install_portaudio(monkeypatch, [dict()], failure=failure)
    with pytest.raises(microphone().MicrophoneUnavailable, match=word):
        microphone().list_input_devices()
    assert terminated == [True]


def test_missing_audio_runtime_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pyaudio', None)
    with pytest.raises(microphone().MicrophoneUnavailable, match='runtime'):
        microphone().list_input_devices()
