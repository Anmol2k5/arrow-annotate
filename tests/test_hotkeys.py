from types import SimpleNamespace

import pytest

from arrow.core.hotkeys import HoldShortcut


class Keyboard:
    def __init__(self):
        self.callbacks = []
        self.removed = []
        self.keys = {
            'ctrl+space': (((29, 97), (57,)),),
            'ctrl+shift': (((29, 97), (42, 54)),),
            'alt+a': (((56, 100), (30,)),),
            'a,b': (((30,),), ((48,),)),
        }

    def parse_hotkey(self, shortcut):
        if shortcut not in self.keys:
            raise ValueError('Unknown key')
        return self.keys[shortcut]

    def hook(self, callback, suppress=False):
        assert suppress is False
        self.callbacks.append(callback)
        return callback

    def unhook(self, callback):
        self.callbacks.remove(callback)
        self.removed.append(callback)

    def emit(self, event_type, scan_code):
        for callback in list(self.callbacks):
            callback(SimpleNamespace(event_type=event_type, scan_code=scan_code))


def shortcut(backend, value='ctrl+space'):
    calls = []
    hook = HoldShortcut(value, lambda: calls.append('press'), lambda: calls.append('release'), backend)
    hook.register()
    return hook, calls


def test_hold_starts_once_and_releases_on_either_shortcut_key():
    backend = Keyboard()
    hook, calls = shortcut(backend)
    backend.emit('down', 97)  # Right Ctrl is an alternative scan code.
    assert calls == []
    backend.emit('down', 57)
    backend.emit('down', 57)  # OS key repeat must not start a second capture.
    backend.emit('down', 30)
    backend.emit('up', 30)
    assert calls == ['press']
    backend.emit('up', 97)
    backend.emit('up', 57)
    assert calls == ['press', 'release']
    backend.emit('down', 29)
    backend.emit('down', 57)
    backend.emit('up', 57)
    assert calls == ['press', 'release', 'press', 'release']
    hook.close()


def test_modifier_only_shortcut_supports_both_sides():
    backend = Keyboard()
    hook, calls = shortcut(backend, 'ctrl+shift')
    backend.emit('down', 54)
    backend.emit('down', 97)
    backend.emit('up', 54)
    assert calls == ['press', 'release']
    hook.close()


@pytest.mark.parametrize('invalid', ['fn+space', 'FN', '', 'unknown', 'a,b'])
def test_invalid_rebind_preserves_working_shortcut(invalid):
    backend = Keyboard()
    hook, calls = shortcut(backend)
    with pytest.raises(ValueError):
        hook.rebind(invalid)
    backend.emit('down', 29)
    backend.emit('down', 57)
    backend.emit('up', 57)
    assert calls == ['press', 'release']
    assert hook.shortcut == 'ctrl+space'
    hook.close()


def test_rebind_releases_old_hold_then_uses_new_chord():
    backend = Keyboard()
    hook, calls = shortcut(backend)
    backend.emit('down', 29)
    backend.emit('down', 57)
    hook.rebind('alt+a')
    assert calls == ['press', 'release']
    backend.emit('up', 57)
    backend.emit('down', 57)
    assert calls == ['press', 'release']
    backend.emit('down', 56)
    backend.emit('down', 30)
    backend.emit('up', 30)
    assert calls == ['press', 'release', 'press', 'release']
    assert hook.shortcut == 'alt+a'
    hook.close()


def test_close_releases_active_hold_once_and_unhooks():
    backend = Keyboard()
    hook, calls = shortcut(backend)
    hook.register()
    assert len(backend.callbacks) == 1
    backend.emit('down', 29)
    backend.emit('down', 57)
    hook.close()
    hook.close()
    backend.emit('up', 57)
    assert calls == ['press', 'release']
    assert len(backend.removed) == 1


def test_fn_error_explains_hardware_limitation():
    backend = Keyboard()
    hook = HoldShortcut('fn+space', lambda: None, lambda: None, backend)
    with pytest.raises(ValueError, match='(?i)(firmware|hardware)'):
        hook.register()
    assert backend.callbacks == []


def test_rebind_recovers_registration_after_initial_hook_failure():
    class FailingKeyboard(Keyboard):
        failures = 1

        def hook(self, callback, suppress=False):
            if self.failures:
                self.failures -= 1
                raise RuntimeError('Keyboard unavailable')
            return super().hook(callback, suppress)

    backend = FailingKeyboard()
    calls = []
    hook = HoldShortcut('ctrl+space', lambda: calls.append('press'), lambda: calls.append('release'), backend)
    with pytest.raises(RuntimeError):
        hook.register()
    hook.rebind('alt+a')
    backend.emit('down', 56)
    backend.emit('down', 30)
    backend.emit('up', 30)
    assert calls == ['press', 'release']
    hook.close()


def test_failed_rebind_registration_preserves_previous_shortcut():
    class FailingKeyboard(Keyboard):
        def hook(self, callback, suppress=False):
            raise RuntimeError('Keyboard unavailable')

    hook = HoldShortcut('ctrl+space', lambda: None, lambda: None, FailingKeyboard())
    with pytest.raises(RuntimeError):
        hook.register()
    with pytest.raises(RuntimeError):
        hook.rebind('alt+a')
    assert hook.shortcut == 'ctrl+space'
    hook.close()


@pytest.mark.parametrize('value', ['esc', 'ctrl+esc', 'enter', 'ctrl+enter', 'return', 'escape'])
def test_capture_chords_cannot_use_reserved_finish_or_cancel_keys(value):
    backend = Keyboard()
    backend.keys[value] = (((1,),),)  # Backend accepts these, capture routing cannot.
    hook = HoldShortcut(value, lambda: None, lambda: None, backend)
    with pytest.raises(ValueError, match='reserved'):
        hook.register()


def test_app_can_explicitly_register_escape_as_control_hook():
    backend = Keyboard()
    backend.keys['esc'] = (((1,),),)
    calls = []
    hook = HoldShortcut('esc', lambda: calls.append('cancel'), lambda: None,
                        backend, allow_reserved=True)
    hook.register()
    backend.emit('down', 1)
    assert calls == ['cancel']
    hook.close()
