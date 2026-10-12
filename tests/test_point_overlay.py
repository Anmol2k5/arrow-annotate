"""Point Mode gesture handling in the selection overlay.

The overlay is the only place that interprets a mouse click, so it is the seam
where POINT and ANNOTATE must diverge without sharing mutable state.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from arrow.capture.session import CaptureMode
from arrow.ui.overlay import SelectionOverlay

_APP = None


def _qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def overlay():
    _qapp()
    ov = SelectionOverlay()
    # Pin a geometry with a negative origin: the virtual desktop is not
    # necessarily anchored at (0, 0).
    ov._offset = QPointF(-1920, -1080)
    yield ov
    ov._teardown()
    ov.deleteLater()


def _click(ov: SelectionOverlay, x: float, y: float, button=Qt.MouseButton.LeftButton):
    """Synthesize a press in widget-local coordinates."""
    local = QPointF(x, y)
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        local,
        QPointF(local.x() + ov._offset.x(), local.y() + ov._offset.y()),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    ov.mousePressEvent(ev)


def test_point_mode_click_emits_virtual_desktop_coordinates(overlay):
    overlay.set_capture_mode(CaptureMode.POINT)
    seen = []
    overlay.point_selected.connect(lambda x, y: seen.append((x, y)))

    _click(overlay, 100, 200)
    assert seen == [(100 - 1920, 200 - 1080)]


def test_point_mode_click_creates_no_stroke(overlay):
    overlay.set_capture_mode(CaptureMode.POINT)
    _click(overlay, 50, 60)
    assert overlay._strokes == []
    assert overlay._current_stroke is None


def test_point_mode_emits_for_every_click(overlay):
    """Multi-capture: the overlay stays up so one task collects several."""
    overlay.set_capture_mode(CaptureMode.POINT)
    seen = []
    overlay.point_selected.connect(lambda x, y: seen.append((x, y)))

    _click(overlay, 10, 10)
    _click(overlay, 20, 20)
    _click(overlay, 30, 30)
    assert len(seen) == 3


def test_point_mode_ignores_non_left_buttons(overlay):
    overlay.set_capture_mode(CaptureMode.POINT)
    seen = []
    overlay.point_selected.connect(lambda x, y: seen.append((x, y)))

    _click(overlay, 10, 10, button=Qt.MouseButton.RightButton)
    assert seen == []


def test_annotate_mode_click_does_not_emit_point(overlay):
    overlay.set_capture_mode(CaptureMode.ANNOTATE)
    seen = []
    overlay.point_selected.connect(lambda x, y: seen.append((x, y)))

    _click(overlay, 100, 100)
    assert seen == []
    assert overlay._current_stroke is not None
    assert overlay._current_stroke.role == "source"


def test_switching_to_point_mode_discards_partial_strokes(overlay):
    overlay.set_capture_mode(CaptureMode.ANNOTATE)
    _click(overlay, 10, 10)
    assert overlay._strokes or overlay._current_stroke is not None

    overlay.set_capture_mode(CaptureMode.POINT)
    assert overlay._strokes == []
    assert overlay._current_stroke is None


def test_default_mode_is_annotate(overlay):
    """Existing freehand behaviour must be the default, not a behaviour change."""
    assert overlay.capture_mode is CaptureMode.ANNOTATE


def test_point_mode_finish_without_click_cancels(overlay):
    """No silent full-screen capture when the user never pointed at anything."""
    overlay.set_capture_mode(CaptureMode.POINT)
    overlay._active = True
    events = []
    overlay.cancelled.connect(lambda: events.append("cancelled"))
    selections = []
    overlay.selection_complete.connect(lambda r: selections.append(r))

    overlay.hide_overlay()
    assert events == ["cancelled"]
    assert selections == []


def test_annotate_mode_finish_without_stroke_still_falls_back(overlay):
    """Unchanged pre-existing behaviour for the freehand flow."""
    overlay._active = True
    selections = []
    overlay.selection_complete.connect(lambda r: selections.append(r))

    overlay.hide_overlay()
    assert len(selections) == 1
    geom = overlay.geometry()
    assert selections[0].to_dict()["width"] == geom.width()