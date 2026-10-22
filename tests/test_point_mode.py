"""Point Mode: one click produces a useful capture.

Covers the cases that silently corrupt screen coordinates — negative monitor
origins, mixed DPI and edge clicks — plus the honesty rule that an unresolved
target must never be reported as a detected element.
"""

from __future__ import annotations

import pytest

from arrow.context.native_resolver import NativeElementContext, Rect
from arrow.context.point_target import (
    FALLBACK_HALF,
    PointTarget,
    clip_rect,
    fallback_rect,
    resolve_point_target,
)

# Virtual desktop with a 1920x1080 primary at the origin, a monitor to its
# left starting at x=-1920, and one above starting at y=-1080.
LEFT = {"x": -1920, "y": 0, "width": 1920, "height": 1080}
ABOVE = {"x": 0, "y": -1080, "width": 1920, "height": 1080}
PRIMARY = {"x": 0, "y": 0, "width": 1920, "height": 1080}
DESKTOP = {"x": -1920, "y": -1080, "width": 3840, "height": 2160}


def _element(left, top, width, height, **kw):
    return NativeElementContext(
        bounding_rect=Rect(left=left, top=top, right=left + width, bottom=top + height),
        **kw,
    )


class _StubResolver:
    def __init__(self, result=None, raises=False):
        self._result = result
        self._raises = raises
        self.calls = []

    def resolve_point(self, x, y):
        self.calls.append((x, y))
        if self._raises:
            raise RuntimeError("UIA exploded")
        return self._result


# -- clip_rect ---------------------------------------------------------------


def test_clip_rect_leaves_interior_untouched():
    r = clip_rect({"x": 10, "y": 20, "width": 100, "height": 50}, DESKTOP)
    assert r == {"x": 10, "y": 20, "width": 100, "height": 50}


def test_clip_rect_clamps_at_negative_left_edge():
    # -2000..-1700 requested; the left edge moves to -1920, right edge is
    # already inside, so 220px of the original 300px survives.
    r = clip_rect({"x": -2000, "y": 100, "width": 300, "height": 100}, DESKTOP)
    assert r["x"] == -1920
    assert r["width"] == 220


def test_clip_rect_clamps_at_negative_top_edge():
    # -1300..-1000 requested; the top edge moves to -1080, leaving 80px.
    r = clip_rect({"x": 100, "y": -1300, "width": 100, "height": 300}, DESKTOP)
    assert r["y"] == -1080
    assert r["height"] == 80


def test_clip_rect_never_negative_extent():
    r = clip_rect({"x": 5000, "y": 5000, "width": 100, "height": 100}, DESKTOP)
    assert r["width"] == 0 and r["height"] == 0


def test_clip_rect_without_bounds_is_a_noop():
    r = clip_rect({"x": -5000, "y": -5000, "width": 10, "height": 10}, None)
    assert r == {"x": -5000, "y": -5000, "width": 10, "height": 10}


# -- fallback_rect -----------------------------------------------------------


def test_fallback_rect_is_centred_when_there_is_room():
    r = fallback_rect(500, 500, DESKTOP)
    assert r == {
        "x": 500 - FALLBACK_HALF,
        "y": 500 - FALLBACK_HALF,
        "width": FALLBACK_HALF * 2,
        "height": FALLBACK_HALF * 2,
    }


def test_fallback_rect_on_negative_monitor_keeps_room_on_one_side():
    """A click at the far left of a left-hand monitor must not collapse."""
    # Requests -2020..-1780; the left edge clips to -1920, leaving 140px that
    # still fully contains the click at -1900.
    r = fallback_rect(-1900, 540, DESKTOP)
    assert r["x"] == -1920
    assert r["width"] == 140
    assert r["x"] <= -1900 < r["x"] + r["width"]
    assert r["height"] == FALLBACK_HALF * 2


def test_fallback_rect_above_primary_is_clipped_at_top():
    r = fallback_rect(960, -1070, DESKTOP)
    assert r["y"] == -1080
    assert r["height"] == 130
    assert r["y"] <= -1070 < r["y"] + r["height"]


def test_fallback_rect_on_tiny_desktop_still_yields_usable_crop():
    tiny = {"x": 0, "y": 0, "width": 4, "height": 4}
    r = fallback_rect(2, 2, tiny)
    assert r["width"] >= 16 and r["height"] >= 16


# -- resolve_point_target: resolved ------------------------------------------


def test_resolved_uia_target_uses_real_element_bounds():
    element = _element(300, 200, 120, 40, name="Search", control_type="Button")
    result = resolve_point_target(
        360, 220, DESKTOP, resolver=_StubResolver(_resolved(element))
    )
    assert result.method == "windows_uia"
    assert result.is_fallback is False
    assert result.rect == {"x": 300, "y": 200, "width": 120, "height": 40}
    assert result.label == "Search"
    assert result.confidence > 0.5


def test_resolved_target_on_negative_monitor_keeps_negative_coordinates():
    element = _element(-1500, 300, 200, 60, name="Back", control_type="Button")
    result = resolve_point_target(
        -1400, 330, DESKTOP, resolver=_StubResolver(_resolved(element))
    )
    assert result.rect["x"] == -1500
    assert result.rect["width"] == 200


def test_low_confidence_still_reports_its_confidence():
    element = _element(10, 10, 40, 20, name="x", control_type="Text")
    resolver = _StubResolver(_resolved(element, status="low_confidence", confidence=0.4))
    result = resolve_point_target(30, 20, DESKTOP, resolver=resolver)
    assert result.method == "windows_uia"
    assert result.confidence == pytest.approx(0.4)
    assert result.to_dict()["confidence_kind"] == "heuristic"


def test_element_bounds_are_clipped_to_the_desktop():
    element = _element(1880, 1060, 400, 400, name="edge")
    result = resolve_point_target(
        1900, 1070, DESKTOP, resolver=_StubResolver(_resolved(element))
    )
    assert result.rect["x"] == 1880
    assert result.rect["width"] == 40


# -- resolve_point_target: honest degradation --------------------------------


def test_unresolved_target_falls_back_and_says_so():
    resolver = _StubResolver(_resolved(None, status="unresolved", source="visual"))
    result = resolve_point_target(640, 360, DESKTOP, resolver=resolver)
    assert result.is_fallback is True
    assert result.method == "fallback"
    assert result.confidence == 0.0
    assert result.to_dict()["confidence_kind"] == "none"
    assert any("Falling back" in e for e in result.evidence)


def test_failed_resolver_still_produces_a_capture():
    result = resolve_point_target(640, 360, DESKTOP, resolver=_StubResolver(raises=True))
    assert result.is_fallback is True
    assert result.rect["width"] > 0
    assert any("resolver raised" in e for e in result.evidence)


def test_zero_sized_element_is_not_trusted_as_a_detection():
    element = _element(500, 500, 0, 0, name="ghost")
    result = resolve_point_target(500, 500, DESKTOP, resolver=_StubResolver(_resolved(element)))
    assert result.is_fallback is True


def test_unknown_resolution_never_invents_an_element():
    """No fabricated selector/app identity when nothing was identified."""
    resolver = _StubResolver(_resolved(None, status="unresolved", source="none"))
    result = resolve_point_target(100, 100, DESKTOP, resolver=resolver)
    assert result.element is None
    assert result.label == ""


def test_resolver_receives_the_exact_click_point():
    resolver = _StubResolver(_resolved(None))
    resolve_point_target(-1234.7, 88.2, DESKTOP, resolver=resolver)
    assert resolver.calls == [(-1234, 88)]


# -- PointTarget serialisation ----------------------------------------------


def test_to_dict_reports_coordinate_space_independently_of_the_rect():
    """Callers need to know these are virtual-desktop, possibly negative."""
    target = PointTarget(
        x=-500, y=-200, rect={"x": -620, "y": -320, "width": 240, "height": 240},
        method="fallback", confidence=0.0,
    )
    d = target.to_dict()
    assert d["point"] == {"x": -500, "y": -200}
    assert d["bounds"]["x"] == -620
    assert d["resolution_method"] == "fallback"


def _resolved(element, status="resolved", source="windows_uia", confidence=0.9):
    class R:
        pass

    r = R()
    r.status = status
    r.source = source
    r.confidence = confidence
    r.evidence = ["UIA resolved an element at the point."]
    r.monitor = "primary"
    r.element = element
    return r