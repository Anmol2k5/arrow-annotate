from PIL import Image

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation


def test_coordinate_mapper_synthetic_monitors():
    # Setup synthetic mixed-monitor layout:
    # 1. Secondary Left: (-1920, 0, 1920, 1080), scale=1.5 (High-DPI left)
    # 2. Primary Center: (0, 0, 1920, 1080), scale=1.0
    # 3. Secondary Right: (1920, 0, 1280, 720), scale=1.25
    # 4. Secondary Above: (0, -1080, 1920, 1080), scale=1.0
    
    screens = [
        ScreenInfo("LeftScreen", (-1920, 0, 1920, 1080), 1.5),
        ScreenInfo("PrimaryScreen", (0, 0, 1920, 1080), 1.0),
        ScreenInfo("RightScreen", (1920, 0, 1280, 720), 1.25),
        ScreenInfo("AboveScreen", (0, -1080, 1920, 1080), 1.0)
    ]
    
    mapper = CoordinateMapper(screens)
    
    # Test primary screen mapping
    scr = mapper.find_screen(500, 500)
    assert scr.name == "PrimaryScreen"
    
    scr, lx, ly = mapper.virtual_to_monitor_local(500, 500)
    assert lx == 500
    assert ly == 500
    
    _, px, py = mapper.virtual_to_physical(500, 500)
    assert px == 500
    assert py == 500
    
    # Test left monitor negative coordinates mapping
    scr = mapper.find_screen(-500, 500)
    assert scr.name == "LeftScreen"
    
    scr, lx, ly = mapper.virtual_to_monitor_local(-500, 500)
    # virtual -500 is local 1420 (-500 - (-1920))
    assert lx == 1420
    assert ly == 500
    
    # Physical = 1420 * 1.5 = 2130, 500 * 1.5 = 750
    _, px, py = mapper.virtual_to_physical(-500, 500)
    assert px == 2130
    assert py == 750
    
    # Test above monitor negative coordinates mapping (does not clamp)
    scr = mapper.find_screen(500, -500)
    assert scr.name == "AboveScreen"
    
    scr, lx, ly = mapper.virtual_to_monitor_local(500, -500)
    assert lx == 500
    assert ly == 580 # -500 - (-1080)
    
    _, px, py = mapper.virtual_to_physical(500, -500)
    assert px == 500
    assert py == 580

    # Test right monitor mapping (mixed DPI)
    scr = mapper.find_screen(2000, 100)
    assert scr.name == "RightScreen"
    
    scr, lx, ly = mapper.virtual_to_monitor_local(2000, 100)
    assert lx == 80 # 2000 - 1920
    assert ly == 100
    
    _, px, py = mapper.virtual_to_physical(2000, 100)
    assert px == 100 # 80 * 1.25
    assert py == 125 # 100 * 1.25


def test_coordinate_mapper_rect():
    screens = [
        ScreenInfo("PrimaryScreen", (0, 0, 1920, 1080), 1.5),
    ]
    mapper = CoordinateMapper(screens)
    
    screen, rect = mapper.virtual_rect_to_physical_rect(10, 20, 100, 200)
    assert screen.name == "PrimaryScreen"
    assert rect["x"] == 15 # 10 * 1.5
    assert rect["y"] == 30 # 20 * 1.5
    assert rect["width"] == 150 # 100 * 1.5
    assert rect["height"] == 300 # 200 * 1.5


def test_offscreen_rendering():
    screens = [
        ScreenInfo("PrimaryScreen", (0, 0, 1920, 1080), 1.0),
    ]
    mapper = CoordinateMapper(screens)
    
    # Create mock 1920x1080 screenshot
    raw_img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    
    # Create different annotations
    annotations = [
        Annotation(id="a1", type="rectangle", role="source", label="Button", geometry={"x": 50, "y": 50, "width": 100, "height": 40}),
        Annotation(id="a2", type="highlight", role="destination", label="Drop target", geometry={"x": 300, "y": 300, "width": 150, "height": 150}),
        Annotation(id="a3", type="pointer", role="supporting", geometry={"x": 100, "y": 70}),
        Annotation(id="a4", type="arrow", role="supporting", geometry={"x1": 100, "y1": 70, "x2": 375, "y2": 375}),
        Annotation(id="a5", type="freehand", role="informational", geometry={"points": [{"x": 10, "y": 10}, {"x": 20, "y": 20}, {"x": 30, "y": 15}]})
    ]
    
    service = ScreenshotService()
    annotated = service.render_annotations(raw_img, annotations, mapper)
    
    assert annotated.size == (1920, 1080)
    # Check that it returned an image and has some drawn contents (no longer pure white)
    assert annotated.getpixel((100, 70)) != (255, 255, 255)


def test_crops_generation():
    screens = [
        ScreenInfo("PrimaryScreen", (0, 0, 1920, 1080), 1.0),
    ]
    mapper = CoordinateMapper(screens)
    raw_img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    
    annotations = [
        Annotation(id="a1", type="rectangle", role="source", label="Btn", geometry={"x": 50, "y": 50, "width": 100, "height": 40}),
        Annotation(id="a2", type="rectangle", role="destination", label="Tar", geometry={"x": 300, "y": 300, "width": 100, "height": 100})
    ]
    
    service = ScreenshotService()
    source_crop, dest_crop, context_crop = service.generate_crops(raw_img, annotations, mapper)
    
    assert source_crop is not None
    assert source_crop.size == (100, 40)
    
    assert dest_crop is not None
    assert dest_crop.size == (100, 100)
    
    assert context_crop is not None
    # Combined rect: (50, 50, 100, 40) + (300, 300, 100, 100)
    # Xs range: 50 to 400. Ys range: 50 to 400.
    # With 100px padding: Xs range 50 - 100 = 0 to 400 + 100 = 500. Ys range 0 to 500.
    # Expected size: 500x500
    assert context_crop.size == (500, 500)


def test_capture_composes_monitors_in_one_coordinate_space(monkeypatch):
    from types import SimpleNamespace

    from arrow.capture import screenshot_service as module
    from arrow.capture.session import Annotation

    screens = [ScreenInfo('left', (-100, 0, 100, 100), 1),
               ScreenInfo('right', (0, 0, 100, 100), 2)]
    monkeypatch.setattr(CoordinateMapper, 'from_qt', lambda: CoordinateMapper(screens))

    class FakeMSS:
        monitors = [{'left': -100, 'top': 0, 'width': 300, 'height': 200},
                    {'left': -100, 'top': 0, 'width': 100, 'height': 100},
                    {'left': 0, 'top': 0, 'width': 200, 'height': 200}]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, monitor):
            color = (255, 0, 0) if monitor['left'] < 0 else (0, 255, 0)
            image = Image.new('RGB', (monitor['width'], monitor['height']), color)
            return SimpleNamespace(size=image.size, bgra=image.tobytes('raw', 'BGRX'))

    monkeypatch.setattr(module.mss, 'mss', FakeMSS)
    service = ScreenshotService()
    raw, screen, mapper = service.capture_raw()
    assert raw.size == (400, 200)
    annotations = [Annotation(id='a', type='rectangle', role=role,
                              geometry={'x': x, 'y': 10, 'width': 10, 'height': 10})
                   for role, x in [('source', -90), ('destination', 10)]]
    source, destination, _ = service.generate_crops(raw, annotations, mapper)
    assert source.getpixel((0, 0)) == (255, 0, 0)
    assert destination.getpixel((0, 0)) == (0, 255, 0)
    assert source.size == destination.size == (20, 20)
