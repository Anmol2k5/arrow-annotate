"""Crop geometry for multi-monitor setups with nonzero/negative origins.

Regression cover for the audit finding that cropping used absolute desktop
coordinates on a monitor-local image.
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("ARROW_HOME", tempfile.mkdtemp(prefix="arrow_crop_"))

from arrow.server.screenshots import (  # noqa: E402
    crop_box_for_monitors,
    crop_box_in_monitor,
    monitor_for_rect,
)

# Synthetic monitors, MSS style (no virtual monitor 0). Monitors do not overlap:
# LEFT ends exactly where PRIMARY begins.
PRIMARY = {"left": 0, "top": 0, "width": 1920, "height": 1080}
LEFT = {"left": -2560, "top": 0, "width": 2560, "height": 1440}
ABOVE = {"left": 0, "top": -1080, "width": 1920, "height": 1080}
MONITORS = [LEFT, PRIMARY, ABOVE]


def test_monitor_for_rect_picks_containing_monitor():
    rect = {"x": -500, "y": 100, "width": 200, "height": 50}
    assert monitor_for_rect(rect, MONITORS) is LEFT
    rect = {"x": 100, "y": 100, "width": 200, "height": 50}
    assert monitor_for_rect(rect, MONITORS) is PRIMARY
    rect = {"x": 100, "y": -500, "width": 200, "height": 50}
    assert monitor_for_rect(rect, MONITORS) is ABOVE


def test_crop_is_relative_to_monitor_origin_negative_x():
    # Regression: cropping used absolute desktop coords on a monitor image.
    rect = {"x": -1500, "y": 200, "width": 300, "height": 100}
    monitor, box = crop_box_for_monitors(rect, MONITORS)
    assert monitor is LEFT
    # image origin is at -2560 → local x = -1500 - (-2560) = 1060
    assert box == (1060, 200, 1360, 300)


def test_crop_is_relative_to_monitor_origin_negative_y():
    rect = {"x": 100, "y": -900, "width": 50, "height": 50}
    monitor, box = crop_box_for_monitors(rect, MONITORS)
    assert monitor is ABOVE
    assert box == (100, 180, 150, 230)


def test_crop_primary_monitor_identity():
    rect = {"x": 300, "y": 400, "width": 100, "height": 80}
    _, box = crop_box_for_monitors(rect, MONITORS)
    assert box == (300, 400, 400, 480)


def test_crop_clamps_rect_hanging_off_monitor():
    rect = {"x": 1800, "y": 1000, "width": 300, "height": 300}
    _, box = crop_box_for_monitors(rect, MONITORS)
    assert box == (1800, 1000, 1920, 1080)


def test_crop_rejects_empty_rect():
    with pytest.raises(ValueError):
        crop_box_in_monitor({"x": 0, "y": 0, "width": 0, "height": 10}, PRIMARY)


def test_crop_rejects_rect_off_all_monitors():
    with pytest.raises(ValueError):
        crop_box_for_monitors({"x": 99999, "y": 99999, "width": 10, "height": 10}, [PRIMARY])


def test_monitor_for_rect_uses_overlap_when_center_off_screen():
    rect = {"x": 1900, "y": 500, "width": 400, "height": 200}
    # Center at 2100 is off the primary; overlaps nothing else → falls back
    # to largest overlap, which is the primary monitor.
    monitor = monitor_for_rect(rect, MONITORS)
    assert monitor is PRIMARY
