import json
from arrow.storage.schemas import CaptureRecord

def test_capture_record_serialization():
    data = {
        "id": "20260710_120000",
        "timestamp": "2026-07-10T12:00:00",
        "screenshot_path": "screenshots/capture_20260710_120000.png",
        "annotation_text": "Move button here",
        "cursor_x": 100,
        "cursor_y": 200,
        "element_selector": "#submit-btn",
        "element_path": "html > body > button",
        "react_components": "Button > App",
        "computed_styles": '{"color": "red"}',
        "accessibility": '{"role": "button", "name": "Submit"}',
        "selected_text": "Submit",
        "bounding_box": {"x": 50, "y": 60, "width": 80, "height": 30},
        "agentation_status": "pending",
        "window_title": "Test Window"
    }
    
    # Test from_dict
    record = CaptureRecord.from_dict(data)
    assert record.id == "20260710_120000"
    assert record.cursor_x == 100
    assert record.bounding_box["width"] == 80
    
    # Test to_dict
    dumped = record.to_dict()
    assert dumped["id"] == "20260710_120000"
    assert dumped["bounding_box"]["x"] == 50
    
    # Test formatted_context
    ctx = record.formatted_context()
    assert "Move button here" in ctx
    assert "(100, 200)" in ctx
    assert "#submit-btn" in ctx
    assert "color: red" in ctx
    assert "role: button" in ctx
