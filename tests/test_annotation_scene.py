"""Semantic scene geometry is separate from the complete recorded ink."""

import math

import pytest

from arrow.capture.annotation_scene import build_annotation_scene


def oval(cx, cy, rx=30, ry=20, count=32):
    return [{"x": cx + rx * math.cos(2 * math.pi * i / count),
             "y": cy + ry * math.sin(2 * math.pi * i / count)} for i in range(count + 1)]


def connected_loops():
    source = oval(80, 70)
    destination = oval(350, 260, 40, 25)
    start, end = source[-1], destination[0]
    connector = [{"x": start["x"] + (end["x"] - start["x"]) * i / 20,
                  "y": start["y"] + (end["y"] - start["y"]) * i / 20} for i in range(1, 20)]
    return source + connector + destination


def connected_arcs(sweep=300, start=-90, *, scale=1, dx=0, dy=0, noise=0):
    def arc(cx, cy, rx, ry):
        points = [{"x": cx + rx * math.cos(math.radians(start + sweep * i / 48)),
                   "y": cy + ry * math.sin(math.radians(start + sweep * i / 48))} for i in range(49)]
        return [{"x": (p["x"] + noise * math.sin(i * 1.7)) * scale + dx,
                 "y": (p["y"] + noise * math.cos(i * 1.3)) * scale + dy} for i, p in enumerate(points)]
    source, destination = arc(160, 140, 60, 40), arc(700, 520, 80, 50)
    a, b = source[-1], destination[0]
    connector = [{"x": a["x"] + (b["x"] - a["x"]) * i / 50,
                  "y": a["y"] + (b["y"] - a["y"]) * i / 50} for i in range(1, 50)]
    return source + connector + destination


def semantic(scene, role):
    return next(a for a in scene if a.role == role)


def test_explicit_regions_precede_preserved_ink_and_border_arrow():
    source = [{"x": -40, "y": -15, "t": 1}, {"x": -20, "y": 5, "t": 2}]
    destination = [{"x": 100, "y": 90}, {"x": 130, "y": 120}]
    scene = build_annotation_scene([{"role": "destination", "points": destination},
                                    {"role": "source", "points": source}])

    assert [(a.type, a.role, a.label) for a in scene[:2]] == [
        ("rectangle", "source", "1 Source"), ("rectangle", "destination", "2 Destination")]
    assert scene[0].geometry == {"x": -48, "y": -23, "width": 36, "height": 36}
    assert scene[1].geometry == {"x": 92, "y": 82, "width": 46, "height": 46}
    ink = [a for a in scene if a.type == "freehand"]
    assert [a.geometry["points"] for a in ink] == [destination, source]
    assert all(a.role == "supporting" for a in ink)
    assert [a.style for a in ink] == [{"color": "#22c55e", "semantic_role": "destination"},
                                    {"color": "#ef4444", "semantic_role": "source"}]
    arrow = scene[-1]
    assert (arrow.type, arrow.role) == ("arrow", "informational")
    assert arrow.geometry["x1"] == pytest.approx(-12)
    assert arrow.geometry["x2"] == pytest.approx(92)
    assert [a.order for a in scene] == list(range(1, len(scene) + 1))


def test_one_continuous_gesture_recovers_two_tight_regions_and_keeps_every_point():
    points = connected_loops()
    for i, point in enumerate(points):
        point["t"] = i / 100
    scene = build_annotation_scene([{"role": "source", "points": points}])

    source, destination = semantic(scene, "source"), semantic(scene, "destination")
    assert source.geometry == pytest.approx({"x": 42, "y": 42, "width": 76, "height": 56})
    assert destination.geometry == pytest.approx({"x": 302, "y": 227, "width": 96, "height": 66})
    assert next(a for a in scene if a.type == "freehand").geometry["points"] == points
    assert scene[-1].type == "arrow"


@pytest.mark.parametrize("scale,dx,dy", [(0.2, -1000, -500), (4, 2500, -1300)])
def test_loop_recognition_is_independent_of_scale_and_desktop_origin(scale, dx, dy):
    points = [{"x": p["x"] * scale + dx, "y": p["y"] * scale + dy} for p in connected_loops()]
    scene = build_annotation_scene([{"role": "source", "points": points}])
    destination = semantic(scene, "destination")
    assert destination.geometry["x"] == pytest.approx(310 * scale + dx - 8)
    assert destination.geometry["y"] == pytest.approx(235 * scale + dy - 8)


@pytest.mark.parametrize("start", [-90, 0, 45, 90, 180])
@pytest.mark.parametrize("scale,dx,dy,noise", [(1, 0, 0, 0), (0.2, -1000, -500, 0.15)])
def test_nearly_complete_simple_arcs_identify_both_regions(start, scale, dx, dy, noise):
    points = connected_arcs(start=start, scale=scale, dx=dx, dy=dy, noise=noise)
    scene = build_annotation_scene([{"role": "source", "points": points}])
    assert semantic(scene, "source").geometry["width"] < 150 * scale + 16
    assert semantic(scene, "destination").geometry["width"] < 180 * scale + 16
    assert scene[-1].type == "arrow"
    assert next(a for a in scene if a.type == "freehand").geometry["points"] == points


@pytest.mark.parametrize("sweep", [180, 240, 270])
@pytest.mark.parametrize("start", [-90, 0, 45, 90, 180])
@pytest.mark.parametrize("noise", [0, 0.15])
def test_open_u_arcs_do_not_become_regions_by_borrowing_the_straight_connector(sweep, start, noise):
    scene = build_annotation_scene([{"role": "source", "points": connected_arcs(sweep=sweep, start=start,
                                                                                 noise=noise)}])
    assert not any(a.role == "destination" or a.type == "arrow" for a in scene)


def test_nearly_complete_loops_also_work_in_reverse_drawing_direction():
    scene = build_annotation_scene([{"role": "source", "points": connected_arcs(sweep=-300)}])
    assert semantic(scene, "destination").geometry["width"] < 196
    assert scene[-1].type == "arrow"


@pytest.mark.parametrize("points", [
    [{"x": x, "y": x / 2} for x in range(0, 401, 10)],
    [{"x": i * 4, "y": 100 + 50 * math.sin(i * math.pi / 50)} for i in range(101)],
    oval(100, 100),
    [{"x": 0, "y": 0}, {"x": 0, "y": 100}, {"x": 100, "y": 100}, {"x": 100, "y": 0}],
    # Figure eight: neither half may become a separate target.
    [{"x": 100 + 60 * math.sin(i * math.pi / 32), "y": 100 + 40 * math.sin(i * math.pi / 16)}
     for i in range(129)],
    oval(100, 100) + oval(120, 100),
])
def test_ambiguous_gestures_do_not_invent_a_destination(points):
    scene = build_annotation_scene([{"role": "source", "points": points}])
    assert not any(a.role == "destination" or a.type == "arrow" for a in scene)


def test_a_closed_source_loop_can_remain_tight_before_an_unfinished_connector():
    points = oval(80, 70) + [{"x": 200, "y": 150}, {"x": 350, "y": 260}]
    scene = build_annotation_scene([{"role": "source", "points": points}])
    assert semantic(scene, "source").geometry == pytest.approx({"x": 42, "y": 42, "width": 76, "height": 56})
    assert not any(a.role == "destination" for a in scene)


def test_a_self_crossing_connector_is_ambiguous_even_between_separate_loops():
    points = oval(80, 70) + [{"x": x, "y": y} for x, y in
                            [(150, 100), (200, 140), (205, 140), (200, 145),
                             (200, 140), (250, 180), (330, 220)]] + oval(350, 260, 40, 25)
    scene = build_annotation_scene([{"role": "source", "points": points}])
    assert not any(a.role == "destination" or a.type == "arrow" for a in scene)


@pytest.mark.parametrize("count,position,vertical_first", [(113, 54, True), (400, 20, False), (900, 20, False)])
def test_dense_connector_cannot_hide_a_small_crossing_during_downsampling(count, position, vertical_first):
    connector = [{"x": 110 + 280 * i / count, "y": 70 + 190 * i / count} for i in range(1, count)]
    point = connector[position]
    first_corner = {"x": point["x"] + (0 if vertical_first else 4),
                    "y": point["y"] + (4 if vertical_first else 0)}
    connector[position + 1:position + 1] = [first_corner,
                                          {"x": point["x"] + 4, "y": point["y"] + 4}, dict(point)]
    points = oval(80, 70) + connector + oval(350, 260, 40, 25)
    scene = build_annotation_scene([{"role": "source", "points": points}])
    assert not any(a.role == "destination" or a.type == "arrow" for a in scene)
    assert next(a for a in scene if a.type == "freehand").geometry["points"] == points


def test_empty_gestures_add_no_origin_box_and_a_click_gets_a_small_source_box():
    assert build_annotation_scene([]) == []
    assert build_annotation_scene([{"role": "source", "points": []}]) == []
    scene = build_annotation_scene([{"role": "source", "points": [{"x": -4, "y": 9}]}])
    assert semantic(scene, "source").geometry == {"x": -12, "y": 1, "width": 16, "height": 16}
    assert not any(a.role == "destination" or a.type == "arrow" for a in scene)


def test_explicit_overlapping_regions_do_not_produce_a_backwards_arrow():
    scene = build_annotation_scene([
        {"role": "source", "points": [{"x": 0, "y": 0}, {"x": 100, "y": 100}]},
        {"role": "destination", "points": [{"x": 80, "y": 40}, {"x": 140, "y": 80}]},
    ])
    assert len([a for a in scene if a.type == "rectangle"]) == 2
    assert not any(a.type == "arrow" for a in scene)


def test_dense_gesture_preserves_all_points_while_analysis_is_bounded():
    source, destination = oval(80, 70, count=600), oval(350, 260, 40, 25, count=900)
    connector = [{"x": 110 + 280 * i / 700, "y": 70 + 190 * i / 700} for i in range(1, 700)]
    dense = [dict(point, t=i / 1000) for i, point in enumerate(source + connector + destination)]
    scene = build_annotation_scene([{"role": "source", "points": dense}])
    assert semantic(scene, "destination").geometry["width"] < 120
    assert next(a for a in scene if a.type == "freehand").geometry["points"] == dense
