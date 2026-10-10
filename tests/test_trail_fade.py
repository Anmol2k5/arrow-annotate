"""Regression tests for the pointer-trail fade and painter, without a GUI session."""

import time

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter

from arrow.ui.overlay import ACTIVE_RGB, SelectionOverlay, StrokePoint


def _overlay_math():
    # The rendering helpers do not need a live QWidget or QApplication.
    instance = SelectionOverlay.__new__(SelectionOverlay)
    instance.SUBDIVISION = 7
    instance.FADE_BUCKETS = 24
    return instance


def _points(now):
    points = [StrokePoint(QPointF(float(15 + i * 12), 40.0)) for i in range(6)]
    for point in points:
        point.timestamp = now
    return points


def test_blue_pointer_palette():
    assert ACTIVE_RGB[2] > ACTIVE_RGB[0]
    assert ACTIVE_RGB[2] > ACTIVE_RGB[1]


def test_trail_stays_visible_then_fades_after_release():
    overlay = _overlay_math()
    t0 = time.time()
    points = _points(t0)

    fresh = overlay._build_trail(points, t0 + 0.2, 3.2)
    lingering = overlay._build_trail(points, t0 + 2.5, 3.2)
    expired = overlay._build_trail(points, t0 + 3.3, 3.2)

    assert len(fresh) > len(points)
    assert all(0.0 < a <= 1.0 for _, a in fresh)
    assert 0 < lingering[-1][1] < fresh[-1][1]
    assert all(alpha == 0.0 for _, alpha in expired)


def test_trail_renderer_does_not_paint_expired_segments():
    overlay = _overlay_math()
    t0 = time.time()
    points = _points(t0)
    color = (231, 246, 255)

    image = QImage(128, 88, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    overlay._stroke_trail(
        painter, overlay._build_trail(points, t0 + 0.5, 3.2), ACTIVE_RGB, color
    )
    painter.end()
    assert image.pixelColor(40, 40).alpha() > 0

    expired_image = QImage(128, 88, QImage.Format.Format_ARGB32_Premultiplied)
    expired_image.fill(0)
    painter = QPainter(expired_image)
    overlay._stroke_trail(
        painter, overlay._build_trail(points, t0 + 3.5, 3.2), ACTIVE_RGB, color
    )
    painter.end()
    assert expired_image.pixelColor(40, 40).alpha() == 0


def test_focus_trail_holds_then_fades_for_seven_seconds():
    overlay = _overlay_math()
    now = time.time()
    points = _points(now)

    just_released = overlay._focus_trail(points, now + 1.2, now)
    late_fade = overlay._focus_trail(points, now + 6.6, now)
    expired = overlay._focus_trail(points, now + 9.0, now)

    assert len(just_released) > len(points)
    assert just_released[-1][1] > 0.99
    assert just_released[0][1] == 0.0
    assert 0.0 < late_fade[-1][1] < 1.0
    assert expired == []


def test_focus_trail_is_capped_for_rendering_but_not_storage():
    overlay = _overlay_math()
    now = time.time()
    points = [StrokePoint(QPointF(i * 4.0, 4.0)) for i in range(500)]
    for point in points:
        point.timestamp = now
    overlay.MAX_VISIBLE_TRAIL_POINTS = 220
    trail = overlay._focus_trail(points, now + 0.5, now)

    assert len(trail) <= 220 * overlay.SUBDIVISION + 1
    assert len(points) == 500


def test_focus_outline_paints_color_on_selected_region():
    from arrow.ui.overlay import Stroke

    overlay = _overlay_math()
    now = time.time()
    stroke = Stroke("source")
    stroke.points = [
        StrokePoint(QPointF(24, 24)),
        StrokePoint(QPointF(76, 24)),
        StrokePoint(QPointF(76, 58)),
    ]

    image = QImage(128, 88, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    overlay._draw_focus_outline(painter, stroke, now)
    painter.end()

    assert image.pixelColor(27, 15).alpha() > 0
