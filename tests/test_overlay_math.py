"""Tests for the overlay move-tool math (no GUI needed)."""

import time

from PyQt6.QtCore import QPointF

from arrow.ui.overlay import SelectionOverlay, Stroke, StrokePoint, stroke_center, stroke_rect


def test_stroke_rect_basic():
    pts = [QPointF(10, 20), QPointF(30, 40)]
    r = stroke_rect(pts, QPointF(100, 200), pad=100)
    assert r == {"x": 10, "y": 120, "width": 220, "height": 220}


def test_stroke_rect_preserves_negative_origin():
    pts = [QPointF(10, 10)]
    r = stroke_rect(pts, QPointF(-500, -500), pad=100)
    assert r["x"] == -590  # 10 + (-500) - 100, no clamping to 0
    assert r["y"] == -590
    assert r["width"] == 200  # single point: 0 + 2 * pad
    assert r["height"] == 200


def test_stroke_rect_preserves_negative_multi_point():
    pts = [QPointF(10, 20), QPointF(30, 40)]
    r = stroke_rect(pts, QPointF(-1920, -200), pad=100)
    assert r["x"] == -2010
    assert r["y"] == -280
    assert r["width"] == 220
    assert r["height"] == 220


def test_stroke_rect_empty_is_none():
    assert stroke_rect([], QPointF(0, 0)) is None


def test_stroke_center_midpoint():
    pts = [QPointF(10, 20), QPointF(30, 60)]
    c = stroke_center(pts)
    assert c.x() == 20
    assert c.y() == 40
    assert stroke_center([]) is None


def test_next_role_sequence():
    o = SelectionOverlay.__new__(SelectionOverlay)
    o._strokes = []
    assert o._next_role() == "source"

    s = Stroke("source")
    s.locked = True
    o._strokes = [s]
    assert o._next_role() == "destination"

    # Re-drawing replaces the destination, keeps the source.
    d = Stroke("destination")
    d.locked = True
    o._strokes = [s, d]
    assert o._next_role() == "destination"


def test_build_trail_smooths_and_fades():
    o = SelectionOverlay.__new__(SelectionOverlay)
    o.SUBDIVISION = 6
    o.TRAIL_SECONDS = 2.0

    t0 = time.time()
    pts = [StrokePoint(QPointF(i * 3.0, 0.0)) for i in range(5)]
    for i, p in enumerate(pts):
        p.timestamp = t0 - (4 - i) * 0.1  # oldest first

    trail = o._build_trail(pts, t0 + 1.0, 2.0)
    assert len(trail) > len(pts)  # Catmull-Rom subdivides each segment

    alphas = [a for _, a in trail]
    assert alphas[-1] > alphas[0]  # head (newest) is brighter than the tail

    # Locked strokes render at full opacity (huge trail window).
    full = o._build_trail(pts, t0 + 1.0, 1e9)
    assert all(a > 0.99 for _, a in full)
