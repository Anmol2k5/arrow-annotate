"""Tests for the Phase-5 ContextOrchestrator capture pipeline."""

import os

from PIL import Image

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import ScreenshotService
from arrow.capture.session import Annotation, CaptureSession
from arrow.context.orchestrator import ContextOrchestrator
from arrow.storage.capture_store import CaptureStore

W, H = 1920, 1080


def make_mapper() -> CoordinateMapper:
    return CoordinateMapper([ScreenInfo("Screen_1", (0, 0, W, H), 1.0)])


def make_raw() -> Image.Image:
    return Image.new("RGB", (W, H), (240, 240, 240))


def source_annotation(capture_id: str, x=100, y=100, w=200, h=60) -> Annotation:
    return Annotation(
        id=f"ann_src_{capture_id}",
        type="rectangle",
        role="source",
        label="Source selection",
        geometry={"x": x, "y": y, "width": w, "height": h},
    )


def dest_annotation(capture_id: str, x=400, y=100, w=200, h=60) -> Annotation:
    return Annotation(
        id=f"ann_dst_{capture_id}",
        type="rectangle",
        role="destination",
        label="Destination",
        geometry={"x": x, "y": y, "width": w, "height": h},
    )


BROWSER_ELEMENT = {
    "selector": "button#pricing-cta",
    "elementPath": "html > body > main > div > button#pricing-cta",
    "tagName": "button",
    "id": "pricing-cta",
    "className": "btn btn-primary",
    "boundingBox": {"x": 100, "y": 100, "width": 200, "height": 60},
    "computedStyles": {"position": "static", "display": "inline-block"},
    "reactComponents": "App > PricingSection > PricingCTA",
    "reactSource": {
        "fileName": "src/components/pricing/PricingCTA.tsx",
        "lineNumber": 47,
        "columnNumber": 1,
    },
    "arrowId": "pricing-primary-cta",
    "testId": "cta",
    "route": "/pricing",
    "pageUrl": "http://localhost:3000/pricing",
    "accessibility": {"role": "button", "name": "Get started", "keyboardInteractable": True},
    "viewport": {"width": 1440, "height": 900, "scrollX": 0, "scrollY": 0},
    "text": "Get started",
    "href": "",
    "src": "",
    "innerHtml": "",
}


class FakeBridge:
    connected = True

    def __init__(self, element: dict):
        self._element = element

    def inspect(self, x: int, y: int, timeout: float = 5.0) -> dict:
        return self._element


def make_orchestrator(tmp_path, bridge=None, store=None, project_dir=None) -> ContextOrchestrator:
    return ContextOrchestrator(
        screenshot_service=ScreenshotService(),
        ws_bridge=bridge,
        store=store,
        project_dir=project_dir,
        screenshots_dir=str(tmp_path / "shots"),
    )


def make_store(tmp_path) -> CaptureStore:
    return CaptureStore(db_path=str(tmp_path / "test.db"))


def test_full_pipeline_with_browser_dom_resolution(tmp_path):
    store = make_store(tmp_path)
    project = tmp_path / "project"
    source = project / BROWSER_ELEMENT["reactSource"]["fileName"]
    source.parent.mkdir(parents=True)
    source.write_text("\n" * 46 + "export function PricingCTA() { return <button />; }\n")
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT), store=store,
                             project_dir=str(project))

    session = CaptureSession()
    session.annotations = [source_annotation(session.capture_id)]
    rect = {"x": 100, "y": 100, "width": 200, "height": 60}

    result = orch.run(
        session=session,
        rect=rect,
        instruction="Move this button here and make it slightly wider.",
        cursor=(250, 130),
        window_title="Pricing - Google Chrome",
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    assert result.application_mode == "web"
    assert result.source is not None
    assert result.source.source == "browser_dom"
    assert result.source.resolved is True
    assert result.source.context["selector"] == "button#pricing-cta"
    assert result.source.mapping["source_file"] == "src/components/pricing/PricingCTA.tsx"
    assert result.source.mapping["source_line"] == 47

    # Assets written to disk
    assert result.raw_path and result.raw_path.endswith(".png")
    assert result.annotated_path and result.annotated_path.endswith(".png")
    assert result.context_path and result.context_path.endswith(".png")
    for p in (result.raw_path, result.annotated_path, result.context_path):
        assert os.path.isfile(p)

    # Change request compiled with browser evidence
    cr = result.change_request
    assert cr["normalized_intent"] == "move_element"
    # The annotation label has priority; the DOM accessible name is carried in the element.
    assert cr["source"]["label"] == "Source selection"
    assert cr["source"]["element"]["name"] == "Get started"
    assert cr["source"]["resolution_source"] == "dev_instrumentation"
    assert any(c["operation"] == "resize" for c in cr["requested_changes"])
    assert cr["likely_files"][0]["source_file"] == "src/components/pricing/PricingCTA.tsx"

    # Repository context picked up dev-server URL from the page
    assert result.repository["dev_server_url"] == "http://localhost:3000"
    assert result.repository["active_route"] == "/pricing"

    # Record persisted (change request included and round-trips)
    records = store.get_all()
    assert len(records) == 1
    assert records[0].id == session.capture_id
    assert records[0].annotation_text == "Move this button here and make it slightly wider."
    assert records[0].element_selector == "button#pricing-cta"
    assert records[0].change_request is not None
    assert records[0].change_request["normalized_intent"] == "move_element"
    assert records[0].change_request["source"]["element"]["name"] == "Get started"

    # Session mirrors the pipeline results
    assert session.context["change_request"]["normalized_intent"] == "move_element"
    assert session.context["repository"]["active_route"] == "/pricing"


def test_pipeline_with_source_and_destination(tmp_path):
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT))

    session = CaptureSession()
    session.annotations = [
        source_annotation(session.capture_id, x=100, y=100),
        dest_annotation(session.capture_id, x=400, y=100),
    ]
    rect = {"x": 100, "y": 100, "width": 200, "height": 60}

    result = orch.run(
        session=session,
        rect=rect,
        instruction="Move this button here.",
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    assert result.source is not None and result.source.source == "browser_dom"
    assert result.destination is not None and result.destination.resolved is True
    assert result.destination_path is not None

    cr = result.change_request
    # Geometry-based move relationship: destination is right of source.
    assert cr["normalized_intent"] == "move_element"
    assert cr["move_relationship"] == "right_of"
    # With both anchors, no blocking destination ambiguity.
    assert cr["clarification_required"] is False


class ScreenshotOnlyResolver:
    """Deterministic stand-in for HighlightResolver: always visual fallback."""

    def resolve(self, rect):
        return _ScreenshotOnlyResolution()


class _ScreenshotOnlyResolution:
    def to_dict(self) -> dict:
        return {
            "ok": False,
            "kind": "screenshot_only",
            "source": "highlight_screenshot",
            "file_path": None,
            "source_url": None,
            "window_title": None,
            "selected_text": None,
            "content_category": "visual",
            "confidence": 0.25,
        }


def test_pipeline_falls_back_when_browser_offline(tmp_path):
    store = make_store(tmp_path)
    # No bridge and a resolver that always reports visual-only -> honest fallback.
    orch = ContextOrchestrator(
        screenshot_service=ScreenshotService(),
        resolver=ScreenshotOnlyResolver(),  # type: ignore[arg-type]
        store=store,
        screenshots_dir=str(tmp_path / "shots"),
    )

    session = CaptureSession()
    session.annotations = [source_annotation(session.capture_id)]
    rect = {"x": 100, "y": 100, "width": 200, "height": 60}

    result = orch.run(
        session=session,
        rect=rect,
        instruction="Make this wider.",
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    assert result.application_mode == "native"
    assert result.source is not None
    assert result.source.source == "highlight_screenshot"
    assert result.source.resolved is False

    cr = result.change_request
    assert cr["normalized_intent"] == "resize_element"
    # Source annotation exists (so no blocking ambiguity), but the low
    # confidence and visual-only source are surfaced honestly.
    assert cr["source"]["resolution_confidence"] == 0.25
    assert cr["source"]["resolution_source"] == "highlight_screenshot"
    assert cr["clarification_required"] is False
    assert len(store.get_all()) == 1


def test_pre_frozen_annotations_are_used_verbatim(tmp_path):
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT))

    session = CaptureSession()
    custom = Annotation(
        id="custom-1",
        type="rectangle",
        role="source",
        label="My custom source",
        geometry={"x": 10, "y": 20, "width": 30, "height": 40},
    )
    session.annotations = [custom]

    result = orch.run(
        session=session,
        rect={"x": 100, "y": 100, "width": 200, "height": 60},
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    cr = result.change_request
    assert cr["source"]["geometry"] == {"x": 10, "y": 20, "width": 30, "height": 40}


def test_pipeline_error_is_surfaced(tmp_path):
    class BoomService:
        def render_annotations(self, *args, **kwargs):
            raise RuntimeError("boom")

    orch = ContextOrchestrator(
        screenshot_service=BoomService(),  # type: ignore[arg-type]
        screenshots_dir=str(tmp_path / "shots"),
    )

    session = CaptureSession()
    session.annotations = [source_annotation(session.capture_id)]

    result = orch.run(
        session=session,
        rect={"x": 100, "y": 100, "width": 200, "height": 60},
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is not None
    assert "boom" in result.error
    assert result.annotated_path is None


def test_orchestrator_uses_selected_project_dir(tmp_path):
    import json

    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()  # marker so repo_context treats it as a repository
    (repo / "package.json").write_text(
        json.dumps({"dependencies": {"react": "18.0.0"}}), encoding="utf-8"
    )

    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT), project_dir=str(repo))
    orch.set_project_dir(str(repo))  # explicit wire check

    session = CaptureSession()
    session.annotations = [source_annotation(session.capture_id)]

    result = orch.run(
        session=session,
        rect={"x": 100, "y": 100, "width": 200, "height": 60},
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    assert result.repository["repository_root"] == str(repo)
    assert result.repository["framework"] == "react"
    assert result.change_request["project"]["repository_root"] == str(repo)

    # Clearing the selection is safe.
    orch.set_project_dir(None)


def test_store_optional(tmp_path):
    # No store wired -> pipeline still completes without crashing.
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT), store=None)

    session = CaptureSession()
    session.annotations = [source_annotation(session.capture_id)]

    result = orch.run(
        session=session,
        rect={"x": 100, "y": 100, "width": 200, "height": 60},
        raw_img=make_raw(),
        screen_info=make_mapper().screens[0],
        mapper=make_mapper(),
    )

    assert result.error is None
    assert result.record is not None
    assert result.record["id"] == session.capture_id


def test_pipeline_maps_explicit_dom_id_through_repository_source(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'state'))
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'Button.tsx').write_text('<button data-arrow-id="pricing-primary-cta">Get started</button>')
    element = {**BROWSER_ELEMENT, 'reactSource': None}
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(element), project_dir=str(project))
    result = orch.run(CaptureSession(), {'x': 100, 'y': 100, 'width': 200, 'height': 60},
                      raw_img=make_raw(), screen_info=make_mapper().screens[0], mapper=make_mapper())
    assert result.error is None
    assert result.source.mapping['source_file'] == 'Button.tsx'
    assert result.source.mapping['method'] == 'data_arrow_id'


def test_pipeline_does_not_claim_missing_react_file_is_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'state'))
    orch = make_orchestrator(tmp_path, bridge=FakeBridge(BROWSER_ELEMENT), project_dir=str(tmp_path))
    result = orch.run(CaptureSession(), {'x': 100, 'y': 100, 'width': 200, 'height': 60},
                      raw_img=make_raw(), screen_info=make_mapper().screens[0], mapper=make_mapper())
    assert result.error is None
    assert result.source.mapping.get('resolved') is False
    assert result.change_request['likely_files'] == []


def test_explicit_empty_scene_saves_clean_screenshot_without_fake_rectangle(tmp_path):
    session = CaptureSession(annotation_scene_frozen=True)
    orch = make_orchestrator(tmp_path)
    raw = make_raw()
    result = orch.run(session=session, rect={'x': 0, 'y': 0, 'width': W, 'height': H},
                      instruction='Explain this screen', raw_img=raw,
                      screen_info=make_mapper().screens[0], mapper=make_mapper())
    assert result.error is None
    assert result.source is None
    assert session.annotations == []
    with Image.open(result.annotated_path) as annotated:
        assert annotated.convert('RGB').tobytes() == raw.tobytes()


def test_resolution_captured_at_release_is_used_after_speech_finishes(tmp_path):
    bridge = FakeBridge(BROWSER_ELEMENT)
    orch = make_orchestrator(tmp_path, bridge=bridge)
    session = CaptureSession(annotation_scene_frozen=True)
    session.annotations = [source_annotation(session.capture_id)]
    resolved = orch.resolve_annotations(session.annotations)
    bridge._element = {**BROWSER_ELEMENT, 'selector': 'button#different-page'}
    result = orch.run(session=session, rect={'x': 100, 'y': 100, 'width': 200, 'height': 60},
                      instruction='Move the original button', raw_img=make_raw(),
                      screen_info=make_mapper().screens[0], mapper=make_mapper(),
                      resolved_anchors=resolved)
    assert result.error is None
    assert result.source.context['selector'] == 'button#pricing-cta'
