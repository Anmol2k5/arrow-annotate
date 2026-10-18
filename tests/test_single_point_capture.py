from PIL import Image, ImageChops

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation


def test_single_click_is_visible_in_annotated_image():
    raw = Image.new('RGB', (200, 200), 'white')
    mapper = CoordinateMapper([ScreenInfo('screen', (0, 0, 200, 200), 1)])
    annotation = Annotation(id='click', type='freehand', role='source',
                            geometry={'points': [{'x': 100, 'y': 100}]})
    annotated = ScreenshotService().render_annotations(raw, [annotation], mapper).convert('RGB')
    assert ImageChops.difference(annotated, raw).getbbox() is not None
    assert annotated.getpixel((100, 100)) != raw.getpixel((100, 100))
