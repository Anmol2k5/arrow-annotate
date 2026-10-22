"""Regression coverage for preserving and exporting the drawn annotation scene."""

import math
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
    assert [(a.type, a.role) for a in annotations] == [("rectangle", "source"), ("freehand", "supporting")]
    source, annotation = annotations
    assert source.label == "1 Source"
    assert annotation.style["semantic_role"] == "source"
    assert annotation.coordinateSpace == "virtual_screen"
    assert annotation.geometry["points"] == expected
    assert source.geometry == result["source"]
    assert result["x"] == result["source"]["x"]
    assert [{k: p[k] for k in ("x", "y")} for p in overlay.get_gesture_trail()] == expected
    assert not overlay.isVisible()
    assert overlay._current_stroke is None


def test_mouse_release_includes_final_endpoint_and_keeps_source_and_destination(overlay):
    mouse(overlay, QEvent.Type.MouseButtonPress, 10, 20)
    mouse(overlay, QEvent.Type.MouseButtonRelease, 40, 50)
    draw(overlay, start=(100, 110), end=(140, 150))

    result = capture(overlay)[0]

    assert [(a["type"], a["role"]) for a in result["annotations"]] == [
        ("rectangle", "source"), ("rectangle", "destination"),
        ("freehand", "supporting"), ("freehand", "supporting"), ("arrow", "informational"),
    ]
    assert result["annotations"][2]["geometry"]["points"][-1] == {"x": 40, "y": 50}
    assert result["destination"]["x"] > result["source"]["x"]


def test_completed_strokes_show_semantic_boxes_and_connector_before_export(overlay):
    draw(overlay, start=(100, 300), end=(180, 360))
    draw(overlay, start=(400, 420), end=(480, 480))

    image = overlay.grab().toImage()

    # Border pixels lie outside the raw strokes and cannot pass with freehand alone.
    source = image.pixelColor(92, 330)
    destination = image.pixelColor(488, 450)
    assert source.red() > 200 and source.green() < 100
    assert destination.green() > 150 and destination.red() < 100
    # The two disjoint strokes cannot produce this middle connector pixel.
    assert image.pixelColor(290, 390).alpha() > 100


def test_continuous_move_gesture_reaches_saved_image_crops_and_prompt(overlay, tmp_path):
    from PIL import Image

    from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
    from arrow.capture.screenshot_service import ScreenshotService
    from arrow.capture.session import CaptureSession
    from arrow.context.orchestrator import AnchorResolution, ContextOrchestrator
    from arrow.ui.notch import format_change_request

    def loop(cx, cy, rx, ry):
        return [(cx + rx * math.cos(i * math.pi / 24), cy + ry * math.sin(i * math.pi / 24))
                for i in range(49)]

    source_loop = loop(120, 220, 40, 30)
    destination_loop = loop(600, 530, 50, 40)
    sx, sy = source_loop[-1]
    dx, dy = destination_loop[0]
    points = source_loop + [(sx + (dx - sx) * i / 20, sy + (dy - sy) * i / 20)
                            for i in range(1, 20)] + destination_loop
    mouse(overlay, QEvent.Type.MouseButtonPress, *points[0])
    for point in points[1:]:
        mouse(overlay, QEvent.Type.MouseMove, *point)
    mouse(overlay, QEvent.Type.MouseButtonRelease, *points[-1])
    selection = capture(overlay)[0]
    scene = [Annotation.model_validate(item) for item in selection["annotations"]]
    assert [a.role for a in scene[:2]] == ["source", "destination"]
    assert scene[0].geometry["width"] < 120
    assert scene[1].geometry["width"] < 140

    mapper = CoordinateMapper([ScreenInfo("desktop", (0, 0, 800, 800), 1)])
    pipeline = ContextOrchestrator(screenshots_dir=str(tmp_path))
    instruction = "yah wali chij Mujhe Yahan per chahie"
    session = CaptureSession(annotations=scene, annotation_scene_frozen=True)
    result = pipeline.run(
        session, selection["source"], instruction,
        raw_img=Image.new("RGB", (800, 800), (24, 24, 24)),
        screen_info=mapper.screens[0], mapper=mapper,
        resolved_anchors=(AnchorResolution(role="source", source="visual_fallback"),
                          AnchorResolution(role="destination", source="visual_fallback")),
    )

    assert result.error is None
    assert result.change_request["normalized_intent"] == "move_element"
    assert result.change_request["clarification_required"] is False
    for path in (result.annotated_path, result.source_path, result.destination_path):
        assert path and os.path.isfile(path)
    assert Image.open(result.source_path).width < 140
    assert Image.open(result.destination_path).width < 160
    saved = Image.open(result.annotated_path)
    _, source_rect = mapper.virtual_rect_to_physical_rect(
        *(scene[0].geometry[k] for k in ("x", "y", "width", "height"))
    )
    assert saved.getpixel((source_rect["x"], source_rect["y"] + source_rect["height"] // 2)) == (239, 68, 68)
    prompt = format_change_request(result.change_request)
    assert "**Intent:** Move element" in prompt
    assert "1 Source" in prompt and "2 Destination" in prompt
    assert instruction in prompt
    # The reusable service renders exactly the same canonical exported scene.
    assert ScreenshotService().render_annotations(
        Image.new("RGB", (800, 800), (24, 24, 24)), scene, mapper
    ).tobytes() == saved.tobytes()


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
