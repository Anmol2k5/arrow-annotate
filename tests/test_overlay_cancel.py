"""P0-6: Escape cancels the capture, finish hotkeys complete it.

Escape must never emit a selection (which would fall through to the
full-screen screenshot fallback), and duplicate triggers must not produce
a second selection.
"""

from __future__ import annotations

import sys

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from arrow.ui.overlay import SelectionOverlay

_APP = None


def _qapp():
    # Keep a module-level reference: a garbage-collected QApplication would
    # crash later widget construction.
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture()
def overlay():
    _qapp()
    ov = SelectionOverlay()
    yield ov
    ov.hide()


def _press(ov, key):
    ov.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_escape_cancels_without_emitting_selection(overlay):
    selections, cancels = [], []
    overlay.selection_complete.connect(lambda r: selections.append(r))
    overlay.cancelled.connect(lambda: cancels.append(True))

    overlay.show_overlay()
    _press(overlay, Qt.Key.Key_Escape)

    assert cancels == [True]
    assert selections == []  # no selection → no full-screen fallback capture
    assert overlay._active is False
    assert overlay.isVisible() is False


def test_finish_emits_selection_complete(overlay):
    selections, cancels = [], []
    overlay.selection_complete.connect(lambda r: selections.append(r))
    overlay.cancelled.connect(lambda: cancels.append(True))

    overlay.show_overlay()
    overlay.hide_overlay()

    assert len(selections) == 1
    assert cancels == []
    # No stroke drawn → full-screen fallback still applies on the finish path.
    result = selections[0].to_dict()
    assert {"x", "y", "width", "height"} <= set(result)


def test_finish_without_active_overlay_is_noop(overlay):
    selections = []
    overlay.selection_complete.connect(lambda r: selections.append(r))

    overlay.hide_overlay()  # never shown

    assert selections == []


def test_duplicate_finish_emits_selection_once(overlay):
    selections = []
    overlay.selection_complete.connect(lambda r: selections.append(r))

    overlay.show_overlay()
    overlay.hide_overlay()
    overlay.hide_overlay()  # duplicate hotkey trigger

    assert len(selections) == 1


def test_duplicate_cancel_emits_once(overlay):
    cancels = []
    overlay.cancelled.connect(lambda: cancels.append(True))

    overlay.show_overlay()
    overlay.cancel_overlay()
    overlay.cancel_overlay()

    assert cancels == [True]


def test_finish_after_cancel_does_not_capture(overlay):
    selections, cancels = [], []
    overlay.selection_complete.connect(lambda r: selections.append(r))
    overlay.cancelled.connect(lambda: cancels.append(True))

    overlay.show_overlay()
    _press(overlay, Qt.Key.Key_Escape)
    overlay.hide_overlay()  # late finish trigger must not resurrect the capture

    assert cancels == [True]
    assert selections == []


def test_escape_without_active_overlay_does_nothing(overlay):
    cancels = []
    overlay.cancelled.connect(lambda: cancels.append(True))

    _press(overlay, Qt.Key.Key_Escape)

    assert cancels == []
