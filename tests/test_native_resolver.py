from arrow.context.native_resolver import (
    NativeContextResolver,
    NativeElementContext,
    OCRCandidate,
    Rect,
)


def _button_element():
    return NativeElementContext(
        process_name="notepad.exe",
        window_title="Untitled - Notepad",
        control_type="Button",
        name="Save",
        automation_id="saveBtn",
        class_name="Button",
        bounding_rect=Rect(left=10, top=20, right=110, bottom=60),
        parent_hierarchy=["ToolBar:", "Window:Untitled - Notepad"],
        enabled=True,
        focused=False,
        accessibility={"localized_control_type": "button"},
    )


def test_uia_resolved_interactive():
    resolver = NativeContextResolver(uia_provider=lambda x, y: _button_element())
    result = resolver.resolve_point(50, 40, capture_id="cap1", role="source")
    assert result.status == "resolved"
    assert result.source == "windows_uia"
    assert result.confidence >= 0.7
    assert result.capture_id == "cap1"
    assert result.role == "source"
    assert result.point == [50, 40]
    assert result.element.name == "Save"
    assert result.element.parent_hierarchy[-1].startswith("Window:")


def test_uia_low_confidence_generic_element():
    generic = NativeElementContext(control_type="Pane")  # no name/id, not interactive
    resolver = NativeContextResolver(uia_provider=lambda x, y: generic)
    result = resolver.resolve_point(5, 5)
    assert result.status == "low_confidence"
    assert result.source == "windows_uia"
    assert result.confidence < 0.7


def test_ocr_fallback_single_candidate():
    def no_uia(x, y):
        return None

    def ocr(x, y):
        return "monitor_1", [
            OCRCandidate(
                text="Submit",
                bounding_rect=Rect(left=0, top=0, right=80, bottom=30),
                confidence=0.9,
                monitor="monitor_1",
            )
        ]

    resolver = NativeContextResolver(uia_provider=no_uia, ocr_provider=ocr)
    result = resolver.resolve_point(40, 15, capture_id="c2")
    assert result.source == "ocr"
    assert result.status == "ocr"
    assert result.monitor == "monitor_1"
    assert result.coordinate_space == "monitor_local_pixels"
    assert len(result.ocr_candidates) == 1
    assert result.ocr_candidates[0].text == "Submit"


def test_ocr_fallback_ambiguous_returns_candidates():
    def ocr(x, y):
        return "monitor_2", [
            OCRCandidate(text="OK", bounding_rect=Rect(left=0, top=0, right=20, bottom=10),
                         confidence=0.8, monitor="monitor_2"),
            OCRCandidate(text="Cancel", bounding_rect=Rect(left=0, top=0, right=40, bottom=10),
                         confidence=0.75, monitor="monitor_2"),
        ]

    resolver = NativeContextResolver(uia_provider=lambda x, y: None, ocr_provider=ocr)
    result = resolver.resolve_point(5, 5)
    assert len(result.ocr_candidates) == 2
    assert any("ambiguous" in e for e in result.evidence)
    # Ambiguity lowers confidence relative to a clean single match.
    assert result.confidence < 0.8


def test_ocr_coordinates_stay_on_their_monitor():
    def ocr(x, y):
        return "monitor_2", [
            OCRCandidate(text="Right", bounding_rect=Rect(left=100, top=50, right=150, bottom=80),
                         confidence=0.9, monitor="monitor_2"),
        ]

    resolver = NativeContextResolver(uia_provider=lambda x, y: None, ocr_provider=ocr)
    result = resolver.resolve_point(2000, 100)
    cand = result.ocr_candidates[0]
    assert cand.monitor == "monitor_2"
    assert cand.coordinate_space == "monitor_local_pixels"
    # Coordinates are monitor-local, not translated into virtual space.
    assert cand.bounding_rect.left == 100


def test_unresolved_visual_fallback():
    resolver = NativeContextResolver(
        uia_provider=lambda x, y: None,
        ocr_provider=lambda x, y: (None, []),
    )
    result = resolver.resolve_point(1, 1, capture_id="c3")
    assert result.status == "unresolved"
    assert result.source == "visual"
    assert result.confidence == 0.0
    assert result.element is None


def test_uia_provider_exception_falls_back_to_ocr():
    def bad_uia(x, y):
        raise RuntimeError("uia boom")

    def ocr(x, y):
        return "monitor_1", [
            OCRCandidate(text="Fallback", bounding_rect=Rect(left=0, top=0, right=10, bottom=10),
                         confidence=0.95, monitor="monitor_1"),
        ]

    resolver = NativeContextResolver(uia_provider=bad_uia, ocr_provider=ocr)
    result = resolver.resolve_point(10, 10)
    assert result.source == "ocr"
    assert result.ocr_candidates[0].text == "Fallback"


def test_rect_contains():
    r = Rect(left=0, top=0, right=100, bottom=50)
    assert r.contains(50, 25)
    assert not r.contains(150, 25)
    assert r.width == 100
    assert r.height == 50
