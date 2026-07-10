from typing import Dict

import pytest
from pydantic import BaseModel, Field, ValidationError


# Versioned JSON Protocol Pydantic Schema for validation on the Python side
class ViewportSchema(BaseModel):
    width: int
    height: int
    scrollX: float
    scrollY: float
    devicePixelRatio: float
    zoom: float

class ElementSchema(BaseModel):
    tagName: str
    id: str
    className: str
    selector: str
    elementPath: str
    boundingBox: Dict[str, int]
    text: str
    accessibleName: str
    role: str
    reactComponents: str
    shadowPath: str
    computedStyles: Dict[str, str]

class TabSchema(BaseModel):
    id: int
    title: str
    url: str
    screenshot: str

class PageSchema(BaseModel):
    route: str
    shadowDomExists: bool
    iframes: list


class BrowserExtensionResponse(BaseModel):
    protocolVersion: int = Field(..., ge=1, le=1) # Restrict strictly to version 1
    requestId: str
    captureId: str
    status: str
    tab: TabSchema
    viewport: ViewportSchema
    element: ElementSchema
    page: PageSchema


def test_extension_protocol_valid():
    valid_data = {
        "protocolVersion": 1,
        "requestId": "req-123",
        "captureId": "cap-456",
        "status": "ok",
        "tab": {
            "id": 1,
            "title": "React App",
            "url": "https://localhost:3000/",
            "screenshot": "iVBORw0KGgoAAAANSUhEUgAA..."
        },
        "viewport": {
            "width": 1024,
            "height": 768,
            "scrollX": 0.0,
            "scrollY": 100.0,
            "devicePixelRatio": 1.0,
            "zoom": 1.0
        },
        "element": {
            "tagName": "button",
            "id": "submit-btn",
            "className": "btn btn-primary",
            "selector": "#submit-btn",
            "elementPath": "body > button",
            "boundingBox": {"x": 10, "y": 20, "width": 80, "height": 30},
            "text": "Submit Form",
            "accessibleName": "Submit Form",
            "role": "button",
            "reactComponents": "Form > Button",
            "shadowPath": "",
            "computedStyles": {"position": "relative"}
        },
        "page": {
            "route": "/home",
            "shadowDomExists": False,
            "iframes": []
        }
    }
    
    resp = BrowserExtensionResponse(**valid_data)
    assert resp.protocolVersion == 1
    assert resp.status == "ok"
    assert resp.element.tagName == "button"
    assert resp.tab.title == "React App"


def test_extension_protocol_invalid_version():
    invalid_data = {
        "protocolVersion": 2, # Version 2 is unsupported
        "requestId": "req-123",
        "captureId": "cap-456",
        "status": "ok",
        "tab": {
            "id": 1,
            "title": "React App",
            "url": "https://localhost:3000/",
            "screenshot": "iVBORw0KGgoAAAANSUhEUgAA..."
        },
        "viewport": {
            "width": 1024,
            "height": 768,
            "scrollX": 0.0,
            "scrollY": 100.0,
            "devicePixelRatio": 1.0,
            "zoom": 1.0
        },
        "element": {
            "tagName": "button",
            "id": "submit-btn",
            "className": "btn btn-primary",
            "selector": "#submit-btn",
            "elementPath": "body > button",
            "boundingBox": {"x": 10, "y": 20, "width": 80, "height": 30},
            "text": "Submit Form",
            "accessibleName": "Submit Form",
            "role": "button",
            "reactComponents": "Form > Button",
            "shadowPath": "",
            "computedStyles": {"position": "relative"}
        },
        "page": {
            "route": "/home",
            "shadowDomExists": False,
            "iframes": []
        }
    }
    
    with pytest.raises(ValidationError):
        BrowserExtensionResponse(**invalid_data)


def test_extension_protocol_missing_field():
    incomplete_data = {
        "protocolVersion": 1,
        "requestId": "req-123",
        "status": "ok"
        # missing tab, viewport, element, page
    }
    
    with pytest.raises(ValidationError):
        BrowserExtensionResponse(**incomplete_data)
