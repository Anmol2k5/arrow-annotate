"""Pixel-level coverage for the exported annotation scene."""

import pytest
from PIL import Image, ImageChops

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation


def render(annotations, *, scale=1, size=(420, 300), origin=(0, 0), color=(255, 255, 255)):
    raw = Image.new("RGB", (round(size[0] * scale), round(size[1] * scale)), color)
    mapper = CoordinateMapper([ScreenInfo("desktop", (*origin, *size), scale)])
    return ScreenshotService().render_annotations(raw, annotations, mapper)


def glyph_pixels(image):
    return [(x, y) for y in range(image.height) for x in range(image.width)
            if min(image.getpixel((x, y))) > 200]


def test_scene_renders_both_boxes_raw_strokes_and_an_arrowhead():
    annotations = [
        Annotation(id="source", type="rectangle", role="source", label="1 Source", order=1,
                   geometry={"x": 30, "y": 55, "width": 90, "height": 70}),
        Annotation(id="destination", type="rectangle", role="destination", label="2 Destination", order=2,
                   geometry={"x": 285, "y": 130, "width": 100, "height": 80}),
        Annotation(id="raw-source", type="freehand", role="supporting", order=3,
                   style={"color": "#ef4444", "semantic_role": "source"},
                   geometry={"points": [{"x": 45, "y": 75}, {"x": 70, "y": 105}, {"x": 105, "y": 75}]}),
        Annotation(id="raw-destination", type="freehand", role="supporting", order=4,
                   style={"color": "#22c55e", "semantic_role": "destination"},
                   geometry={"points": [{"x": 300, "y": 180}, {"x": 330, "y": 195}, {"x": 370, "y": 180}]}),
        Annotation(id="connector", type="arrow", role="informational", order=5,
                   geometry={"x1": 120, "y1": 155, "x2": 285, "y2": 155}),
    ]

    image = render(annotations)

    assert image.getpixel((30, 95)) == (239, 68, 68)
    assert image.getpixel((385, 180)) == (34, 197, 94)
    red = image.getpixel((70, 105))
    green = image.getpixel((330, 195))
    assert red[0] > red[1] + 100 and red[0] > red[2] + 100
    assert green[1] > green[0] + 100 and green[1] > green[2] + 70
    assert image.getpixel((210, 155)) == (167, 139, 250)
    # This wing is outside the shaft, so a line without a head cannot pass.
    assert image.getpixel((273, 150)) == (167, 139, 250)


@pytest.mark.parametrize("location", [(255, 2), (255, 168), (-4, -4)])
def test_labels_are_fully_visible_at_image_edges(location):
    def label_at(x, y):
        return Annotation(id="destination", type="rectangle", role="destination", label="2 Destination",
                          geometry={"x": x, "y": y, "width": 6, "height": 6})

    center = render([label_at(70, 100)], size=(260, 170), color=(24, 24, 24))
    edge = render([label_at(*location)], size=(260, 170), color=(24, 24, 24))
    # White glyph coverage must be identical: no part of the label may be clipped.
    assert len(glyph_pixels(edge)) == len(glyph_pixels(center))
    assert len(glyph_pixels(edge)) > 100


def test_labels_and_borders_scale_with_device_pixel_ratio():
    annotation = Annotation(id="source", type="rectangle", role="source", label="1 Source",
                            geometry={"x": 40, "y": 65, "width": 90, "height": 45})
    images = [render([annotation], scale=scale, size=(220, 140), color=(24, 24, 24)) for scale in (1, 2)]
    glyph_bounds = []
    for image in images:
        pixels = glyph_pixels(image)
        glyph_bounds.append((max(x for x, _ in pixels) - min(x for x, _ in pixels),
                             max(y for _, y in pixels) - min(y for _, y in pixels)))
    assert glyph_bounds[1][0] >= glyph_bounds[0][0] * 1.7
    assert glyph_bounds[1][1] >= glyph_bounds[0][1] * 1.7
    # The left border remains four logical pixels wide at both scales.
    assert images[1].getpixel((86, 170)) == (239, 68, 68)


def test_scene_rendering_maps_negative_virtual_coordinates():
    annotation = Annotation(id="raw", type="freehand", role="supporting", style={"color": "#ef4444"},
                            geometry={"points": [{"x": -80, "y": -30}, {"x": -60, "y": -10}]})
    image = render([annotation], scale=2, size=(140, 100), origin=(-100, -50))
    pixel = image.getpixel((60, 60))
    assert pixel[0] > pixel[1] + 100


def test_empty_scene_preserves_the_screenshot_without_a_border():
    raw = Image.new("RGB", (120, 90), (32, 48, 64))
    mapper = CoordinateMapper([ScreenInfo("desktop", (0, 0, 120, 90), 1)])
    image = ScreenshotService().render_annotations(raw, [], mapper)
    assert ImageChops.difference(raw, image).getbbox() is None
