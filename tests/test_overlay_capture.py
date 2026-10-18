"""Regression coverage for preserving and exporting the drawn annotation scene."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication

from arrow.capture.session import Annotation
from arrow.ui.overlay import SelectionOverlay


@pytest.fixture
def overlay():
    app = QApplication.instance() or QApplication([])
    widget = SelectionOverlay()
    widget.show_overlay()
    widget._fade_timer.stop()
    yield widget
    widget.close()
    app.processEvents()


def mouse(overlay, kind, x, y):
    point = QPointF(x, y)
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    event = QMouseEvent(kind, point, point + overlay._offset, button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(overlay, event)


def draw(overlay, start=(10, 20), end=(30, 40), release=True):
    mouse(overlay, QEvent.Type.MouseButtonPress, *start)
    mouse(overlay, QEvent.Type.MouseMove, *end)
    if release:
        mouse(overlay, QEvent.Type.MouseButtonRelease, *end)


def capture(overlay):
    results = []
    overlay.selection_complete.connect(lambda result: results.append(result.to_dict()))
    overlay.hide_overlay()
    return results


def test_live_stroke_retains_points_older_than_the_comet_tail(overlay):
    draw(overlay, release=False)
    original = list(overlay._current_stroke.points)
    for point in original:
        point.timestamp = time.time() - 10

    overlay._update_fade()

    assert overlay._current_stroke.points == original


def test_long_live_annotation_stays_visible_before_mouse_release(overlay):
    draw(overlay, start=(30, 40), end=(200, 200), release=False)
    for point in overlay._current_stroke.points:
        point.timestamp = time.time() - 10

    overlay._update_fade()
    image = overlay.grab().toImage()

    assert image.pixelColor(30, 40).alpha() > 100


def test_finishing_while_mouse_is_down_exports_the_whole_stroke(overlay):
    overlay._offset = QPointF(-500, -200)
    draw(overlay, release=False)
    expected = [{"x": p.point.x() - 500, "y": p.point.y() - 200}
                for p in overlay._current_stroke.points]

    results = capture(overlay)

    assert len(results) == 1
    result = results[0]
    annotations = [Annotation.model_validate(item) for item in result["annotations"]]
    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation.type == "freehand"
    assert annotation.role == "source"
    assert annotation.coordinateSpace == "virtual_screen"
    assert annotation.geometry["points"] == expected
    assert {k: annotation.geometry[k] for k in ("x", "y", "width", "height")} == result["source"]
    assert result["x"] == result["source"]["x"]
    assert [{k: p[k] for k in ("x", "y")} for p in overlay.get_gesture_trail()] == expected
    assert not overlay.isVisible()
    assert overlay._current_stroke is None


def test_mouse_release_includes_final_endpoint_and_keeps_source_and_destination(overlay):
    mouse(overlay, QEvent.Type.MouseButtonPress, 10, 20)
    mouse(overlay, QEvent.Type.MouseButtonRelease, 40, 50)
    draw(overlay, start=(100, 110), end=(140, 150))

    result = capture(overlay)[0]

    assert [a["role"] for a in result["annotations"]] == ["source", "destination"]
    assert result["annotations"][0]["geometry"]["points"][-1] == {"x": 40, "y": 50}
    assert result["destination"]["x"] > result["source"]["x"]


def test_hide_overlay_is_idempotent_and_empty_capture_has_no_annotation(overlay):
    results = capture(overlay)
    overlay.hide_overlay()

    assert len(results) == 1
    assert results[0]["annotations"] == []
    assert results[0]["source"] is None
    assert not overlay.isVisible()


def test_cancel_discards_in_progress_capture_without_completion(overlay):
    draw(overlay, release=False)
    results = []
    overlay.selection_complete.connect(results.append)

    overlay.cancel_overlay()
    overlay.hide_overlay()

    assert results == []
    assert overlay.get_gesture_trail() == []
    assert not overlay.isVisible()


@pytest.mark.parametrize("key,signal", [(Qt.Key.Key_Return, "finish_requested"), (Qt.Key.Key_Escape, "cancel_requested")])
def test_keyboard_shortcuts_request_finish_or_cancel(overlay, key, signal):
    requests = []
    getattr(overlay, signal).connect(lambda: requests.append(True))

    QApplication.sendEvent(overlay, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    assert requests == [True]
