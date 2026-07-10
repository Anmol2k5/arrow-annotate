import pytest
from PIL import Image

from arrow.capture.session import Annotation
from arrow.context.orchestrator import ContextOrchestrator


class MockBrowserAdapter:
    def __init__(self, succeeds=True, active=True):
        self.succeeds = succeeds
        self.active = active

    def is_browser_active(self, exe_name):
        return self.active

    def inspect_element(self, x, y):
        if self.succeeds:
            return {
                "selector": ".btn-primary",
                "path": "//button",
                "reactComponent": "PrimaryBtn",
                "selectedText": "Click Me",
                "url": "https://example.com/test",
                "tagName": "BUTTON"
            }
        return None

class MockUIAAdapter:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds

    def inspect_at_point(self, x, y):
        if self.succeeds:
            return {
                "name": "SubmitButton",
                "type": "Button",
                "automation_id": "submit-btn"
            }
        return None

class MockOCRAdapter:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds

    def run_ocr(self, img):
        if self.succeeds:
            return [
                {
                    "text": "Login",
                    "confidence": 0.95,
                    "bounding_box": (10, 10, 100, 100) # Contains center (50, 50)
                }
            ]
        return []


def test_orchestrator_browser_success():
    orchestrator = ContextOrchestrator()
    orchestrator.browser_adapter = MockBrowserAdapter(succeeds=True, active=True)
    orchestrator.uia_adapter = MockUIAAdapter(succeeds=False)
    orchestrator.ocr_adapter = MockOCRAdapter(succeeds=False)

    ann = Annotation(
        id="a1",
        type="rectangle",
        role="source",
        geometry={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    
    anchor = orchestrator.resolve_annotation_anchor(ann, "session_123")
    
    assert anchor["status"] == "resolved"
    assert anchor["confidence"] == 0.95
    assert anchor["source"] == "browser_dom"
    assert "DOM element successfully resolved" in anchor["evidence"][1]
    assert anchor["metadata"]["element_selector"] == ".btn-primary"
    assert anchor["metadata"]["react_components"] == "PrimaryBtn"


def test_orchestrator_browser_fallback_to_uia():
    orchestrator = ContextOrchestrator()
    # Browser is active, but DOM inspection fails, should fall back to UIA
    orchestrator.browser_adapter = MockBrowserAdapter(succeeds=False, active=True)
    orchestrator.uia_adapter = MockUIAAdapter(succeeds=True)
    orchestrator.ocr_adapter = MockOCRAdapter(succeeds=False)

    ann = Annotation(
        id="a1",
        type="rectangle",
        role="source",
        geometry={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    
    anchor = orchestrator.resolve_annotation_anchor(ann, "session_123")
    
    assert anchor["status"] == "resolved"
    assert anchor["confidence"] == 0.85
    assert anchor["source"] == "uia"
    assert any("UIA matched node of type Button" in ev for ev in anchor["evidence"])
    assert anchor["metadata"]["element_name"] == "SubmitButton"


def test_orchestrator_native_uia_success():
    orchestrator = ContextOrchestrator()
    # Not a browser, so browser adapter is inactive. UIA succeeds.
    orchestrator.browser_adapter = MockBrowserAdapter(succeeds=False, active=False)
    orchestrator.uia_adapter = MockUIAAdapter(succeeds=True)
    orchestrator.ocr_adapter = MockOCRAdapter(succeeds=False)

    ann = Annotation(
        id="a1",
        type="rectangle",
        role="source",
        geometry={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    
    anchor = orchestrator.resolve_annotation_anchor(ann, "session_123")
    
    assert anchor["status"] == "resolved"
    assert anchor["confidence"] == 0.85
    assert anchor["source"] == "uia"
    assert anchor["metadata"]["element_name"] == "SubmitButton"


def test_orchestrator_native_fallback_to_ocr():
    orchestrator = ContextOrchestrator()
    orchestrator.browser_adapter = MockBrowserAdapter(succeeds=False, active=False)
    orchestrator.uia_adapter = MockUIAAdapter(succeeds=False)
    orchestrator.ocr_adapter = MockOCRAdapter(succeeds=True)

    ann = Annotation(
        id="a1",
        type="rectangle",
        role="source",
        geometry={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    
    # Needs raw_img to trigger OCR
    raw_img = Image.new("RGB", (1920, 1080))
    anchor = orchestrator.resolve_annotation_anchor(ann, "session_123", raw_img=raw_img)
    
    assert anchor["status"] == "resolved"
    # confidence = 0.70 * 0.95 = 0.665
    assert pytest.approx(anchor["confidence"], 0.001) == 0.665
    assert anchor["source"] == "ocr"
    assert anchor["metadata"]["element_name"] == "Login"


def test_orchestrator_visual_fallback():
    orchestrator = ContextOrchestrator()
    orchestrator.browser_adapter = MockBrowserAdapter(succeeds=False, active=False)
    orchestrator.uia_adapter = MockUIAAdapter(succeeds=False)
    orchestrator.ocr_adapter = MockOCRAdapter(succeeds=False)

    ann = Annotation(
        id="a1",
        type="rectangle",
        role="source",
        geometry={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    
    raw_img = Image.new("RGB", (1920, 1080))
    anchor = orchestrator.resolve_annotation_anchor(ann, "session_123", raw_img=raw_img)
    
    assert anchor["status"] == "unresolved"
    assert anchor["confidence"] == 0.25
    assert anchor["source"] == "screenshot_only"
    assert len(anchor["metadata"]) == 0
