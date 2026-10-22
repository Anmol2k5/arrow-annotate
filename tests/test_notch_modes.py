"""Notch -> app wiring for capture modes.

The ScreenshotsView duck-types its callbacks off the parent notch, so a
renamed or missing handler fails silently at runtime. These tests pin the
contract instead.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def view():
    """A ScreenshotsView under a live parent, both kept referenced."""
    from arrow.ui.notch import ScreenshotsView

    _qapp()
    parent = QWidget()
    v = ScreenshotsView()
    v.setParent(parent)
    yield v
    parent.deleteLater()
    v.deleteLater()


def test_point_button_calls_the_point_callback(view):
    calls = []
    view.parent().on_point_requested = lambda: calls.append("point")
    view._point()
    assert calls == ["point"]


def test_capture_button_calls_the_highlight_callback(view):
    calls = []
    view.parent().on_highlight_requested = lambda: calls.append("capture")
    view._highlight()
    assert calls == ["capture"]


def test_missing_callback_does_not_raise(view):
    """A notch without the handler must degrade, not crash the UI thread."""
    view._point()  # must not raise
    view._highlight()  # must not raise
    view._new_task()  # must not raise
    view._copy_task()  # must not raise


def test_task_buttons_are_wired(view):
    seen = []
    parent = view.parent()
    parent.on_new_task_requested = lambda: seen.append("new_task")
    parent.on_copy_task_requested = lambda: seen.append("copy_task")

    view._new_task()
    view._copy_task()
    assert seen == ["new_task", "copy_task"]


def test_point_and_capture_are_distinct_actions(view):
    seen = []
    view.parent().on_point_requested = lambda: seen.append("point")
    view.parent().on_highlight_requested = lambda: seen.append("capture")

    view._highlight()
    view._point()
    assert seen == ["capture", "point"]


def test_capture_mode_enum_round_trips_through_storage():
    """mode is persisted as a plain string, so it must round-trip."""
    from arrow.capture.session import CaptureMode

    for mode in CaptureMode:
        assert CaptureMode(mode.value) is mode
    assert CaptureMode.ANNOTATE.value == "annotate"
    assert CaptureMode.POINT.value == "point"