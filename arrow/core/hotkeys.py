"""Global held shortcuts without suppressing normal keyboard input."""

from __future__ import annotations

import threading
from collections.abc import Callable

DEFAULT_CAPTURE_SHORTCUT = 'ctrl+space'


class HoldShortcut:
    """Emit one press/release pair per held chord, including modifier-only chords.

    Callbacks run on the keyboard backend's thread. GUI callers must dispatch
    them to their GUI thread. The backend is imported only when registering.
    """

    def __init__(self, shortcut: str, on_press: Callable, on_release: Callable, backend=None, *, allow_reserved=False):
        self.shortcut = shortcut
        self._allow_reserved = allow_reserved
        self._on_press = on_press
        self._on_release = on_release
        self._backend = backend
        self._groups: tuple[frozenset[int], ...] = ()
        self._pressed: set[int] = set()
        self._active = False
        self._registered = False
        self._hook = None
        self._lock = threading.RLock()

    def _parse(self, shortcut: str):
        if not isinstance(shortcut, str) or not shortcut.strip():
            raise ValueError('Enter a shortcut, for example Ctrl+Space or Ctrl+Shift.')
        normalized = '+'.join(key.strip().lower() for key in shortcut.strip().split('+'))
        if not self._allow_reserved and {'esc', 'escape', 'enter', 'return'} & set(normalized.split('+')):
            raise ValueError('Esc and Enter are reserved for cancelling and finishing captures. Choose another shortcut.')
        if 'fn' in normalized.split('+'):
            raise ValueError('Fn is handled by keyboard firmware and cannot be reliably detected. '
                             'Choose Ctrl, Alt, Shift, or Windows/Command instead.')
        if ',' in normalized or any(not key for key in normalized.split('+')):
            raise ValueError('Use one held key combination, for example Ctrl+Space.')
        if self._backend is None:
            import keyboard
            self._backend = keyboard
        try:
            steps = self._backend.parse_hotkey(normalized)
        except (ValueError, KeyError) as exc:
            raise ValueError(f'Invalid shortcut: {shortcut}') from exc
        if len(steps) != 1 or not steps[0] or any(not group for group in steps[0]):
            raise ValueError('Use one held key combination, for example Ctrl+Space.')
        return normalized, tuple(frozenset(group) for group in steps[0])

    def register(self):
        with self._lock:
            if self._registered:
                return self
            normalized, groups = self._parse(self.shortcut)
            handle = self._backend.hook(self._on_event, suppress=False)
            self.shortcut, self._groups = normalized, groups
            self._hook = handle
            self._registered = True
        return self

    def rebind(self, shortcut: str):
        with self._lock:
            # Validation happens first: a bad edit must preserve the live hook
            # and any current hold. One generic hook serves every valid chord.
            normalized, groups = self._parse(shortcut)
            if not self._registered:
                # A startup registration failure must be recoverable from the
                # settings dialog. Commit the new chord only after hook setup.
                handle = self._backend.hook(self._on_event, suppress=False)
                self._hook = handle
                self._registered = True
            if self._active:
                self._active = False
                self._on_release()
            self._pressed.clear()
            self.shortcut, self._groups = normalized, groups

    def _on_event(self, event):
        with self._lock:
            if not self._registered:
                return
            if event.event_type == 'down':
                self._pressed.add(event.scan_code)
            elif event.event_type == 'up':
                self._pressed.discard(event.scan_code)
            else:
                return
            held = all(group.intersection(self._pressed) for group in self._groups)
            if held and not self._active:
                self._active = True
                self._on_press()
            elif self._active and not held:
                self._active = False
                self._on_release()

    def close(self):
        with self._lock:
            if not self._registered:
                return
            self._registered = False
            self._pressed.clear()
            if self._active:
                self._active = False
                self._on_release()
            handle, self._hook = self._hook, None
            self._backend.unhook(handle)
