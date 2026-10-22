"""
Context orchestrator (Phase 5).

Runs the full capture pipeline in one place so the application no longer keeps
separate, disconnected capture flows:

    Capture session
    → Freeze annotation scene
    → Capture raw screenshot
    → Resolve source anchor (browser DOM → native UIA/window-title → visual)
    → Resolve destination anchor (same cascade)
    → Collect repository context
    → Render annotated screenshot
    → Generate crops
    → Compile structured change request
    → Persist capture + assets

The orchestrator is UI-agnostic: it never touches Qt widgets or state-machine
transitions. The caller (app.py) owns the session state machine and may pass a
raw screenshot captured on the UI thread (needed because the overlay must be
hidden by the Qt main thread before capture).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from pydantic import BaseModel, Field

from arrow.capture.context_file import build_context_md, mirror_latest
from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.screenshot_service import SCREENSHOTS_DIR, ScreenshotService
from arrow.capture.session import Annotation, CaptureSession
from arrow.context.highlight_resolver import HighlightResolver
from arrow.context.repo_context import collect_repository_context
from arrow.intent.compiler import CompilerInput, IntentCompiler
from arrow.intent.schemas import ChangeRequest
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord

log = logging.getLogger("arrow.context.orchestrator")


class AnchorResolution(BaseModel):
    """Resolved context for one spatial anchor (source or destination)."""

    role: str
    context: dict = Field(default_factory=dict)
    mapping: dict = Field(default_factory=dict)
    source: str = "none"       # browser_dom | native | visual_fallback | none
    confidence: float = 0.0
    resolved: bool = False

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class PipelineResult(BaseModel):
    """Typed output of one full capture-pipeline run."""

    capture_id: str
    application_mode: str = "desktop"   # web | native | desktop
    raw_path: Optional[str] = None
    annotated_path: Optional[str] = None
    context_path: Optional[str] = None
    source_path: Optional[str] = None
    destination_path: Optional[str] = None
    source: Optional[AnchorResolution] = None
    destination: Optional[AnchorResolution] = None
    repository: dict = Field(default_factory=dict)
    change_request: Optional[dict] = None
    record: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class ContextOrchestrator:
    """One pipeline for capture → context → change request → persistence.

    All dependencies are injectable so tests can run the full pipeline without
    a display, a browser extension, or a real database.
    """

    def __init__(
        self,
        screenshot_service: Optional[ScreenshotService] = None,
        resolver: Optional[HighlightResolver] = None,
        compiler: Optional[IntentCompiler] = None,
        store: Optional[CaptureStore] = None,
        ws_bridge: Any = None,
        project_dir: Optional[str] = None,
        screenshots_dir: str = SCREENSHOTS_DIR,
        task_repo: Any = None,
    ):
        self.screenshot_service = screenshot_service or ScreenshotService()
        self.resolver = resolver or HighlightResolver(ws_bridge=ws_bridge)
        self.compiler = compiler or IntentCompiler()
        self.store = store
        self.ws_bridge = ws_bridge
        self.project_dir = project_dir
        self.screenshots_dir = screenshots_dir
        # Optional TaskBundle grouping; None keeps capture-only behaviour.
        self.task_repo = task_repo
        self.active_task_id: Optional[str] = None

    def set_active_task(self, task_id: Optional[str]) -> None:
        """Subsequent captures join this task. None detaches."""
        self.active_task_id = task_id

    def set_project_dir(self, path: Optional[str]) -> None:
        """Update the selected repository for subsequent captures."""
        self.project_dir = path

    # ------------------------------------------------------------------
    # Public pipeline
    # ------------------------------------------------------------------

    def run(
        self,
        session: CaptureSession,
        rect: dict,
        instruction: str = "",
        cursor: Optional[Tuple[int, int]] = None,
        window_title: str = "",
        raw_img: Any = None,
        screen_info: Optional[ScreenInfo] = None,
        mapper: Optional[CoordinateMapper] = None,
        overlay: Any = None,
        target: Optional[dict] = None,
    ) -> PipelineResult:
        """Execute the capture pipeline for a session.

        Args:
            session: The active capture session (annotations may be pre-frozen).
            rect: Selection rectangle in virtual-desktop coordinates
                (``{"x", "y", "width", "height"}``).
            instruction: Raw user instruction (voice or typed).
            cursor: Cursor position at capture time, if available.
            window_title: Foreground window title at capture time, if available.
            raw_img / screen_info / mapper: A screenshot already captured on the
                UI thread (overlay hiding requires the Qt main thread). When
                omitted, the orchestrator captures the raw screenshot itself.
            overlay: Optional overlay widget to hide while capturing (used only
                when ``raw_img`` is not provided).
        """
        try:
            if raw_img is None or screen_info is None or mapper is None:
                raw_img, screen_info, mapper = self.screenshot_service.capture_raw(overlay)

            # 1. Freeze annotation scene (prefer pre-frozen session annotations).
            annotations = self._freeze_annotations(session, rect)

            # 2. Resolve source + destination anchors.
            source_ann = next((a for a in annotations if a.role == "source"), None)
            dest_ann = next((a for a in annotations if a.role == "destination"), None)

            source = self._resolve_anchor("source", source_ann) if source_ann else None
            destination = self._resolve_anchor("destination", dest_ann) if dest_ann else None

            # 3. Repository context (dev-server URL inferred from the page).
            page_url = ((source.context if source is not None else None) or {}).get("pageUrl")
            repo = collect_repository_context(self.project_dir, page_url=page_url)

            # 4. Render annotated screenshot + crops (off-screen, pure PIL).
            annotated_img = self.screenshot_service.render_annotations(raw_img, annotations, mapper)
            source_crop, dest_crop, context_crop = self.screenshot_service.generate_crops(
                raw_img, annotations, mapper
            )

            # 4b. Agent-optimized copies (≤1568px long edge, ~2K tokens each).
            agent_annotated = self.screenshot_service.downscale_for_agent(annotated_img)
            agent_crop = self.screenshot_service.downscale_for_agent(context_crop)

            # 5. Persist assets.
            assets = self._save_assets(
                session.capture_id,
                raw_img=raw_img,
                annotated_img=annotated_img,
                context_crop=context_crop,
                source_crop=source_crop,
                dest_crop=dest_crop,
                agent_annotated=agent_annotated,
                agent_crop=agent_crop,
            )

            # 6. Compile the structured change request.
            application_mode = "web" if source and source.source == "browser_dom" else "native"
            compiler_input = CompilerInput(
                capture_id=session.capture_id,
                application_mode=application_mode,
                project=repo.to_dict(),
                raw_instruction=instruction,
                voice_transcript=instruction,
                annotations=[a.model_dump() for a in annotations],
                source_context=(source.context if source else {}),
                destination_context=(destination.context if destination else {}),
                source_mapping=(source.mapping if source else {}),
                destination_mapping=(destination.mapping if destination else {}),
                assets=assets,
            )
            change_request: ChangeRequest = self.compiler.compile(compiler_input)

            # 7. Persist the capture record (change request included).
            record = self._build_record(
                session=session,
                rect=rect,
                instruction=instruction,
                cursor=cursor,
                window_title=window_title,
                annotated_path=assets["annotated"],
                assets=assets,
                source=source,
                change_request=change_request,
                target=target,
            )
            if self.store is not None:
                self.store.add(record)

            # 7b. Attach to the active task, if the user is building one.
            if self.task_repo is not None and self.active_task_id:
                try:
                    self.task_repo.add_capture(self.active_task_id, record.id)
                except Exception as e:  # noqa: BLE001 - task grouping is not fatal
                    log.warning("Could not attach capture to task: %s", e)

            # 8. Mirror results back onto the session object.
            session.assets = list(assets.values())
            session.source_anchor = (source.context if source else None)
            session.destination_anchor = (destination.context if destination else None)
            session.raw_instruction = instruction
            session.context = {
                "repository": repo.to_dict(),
                "change_request": change_request.to_dict(),
                "source": (source.to_dict() if source else None),
                "destination": (destination.to_dict() if destination else None),
            }

            # 9. Build context.md and mirror to ~/.arrow/latest/.
            context_md = build_context_md(
                capture_id=session.capture_id,
                instruction=instruction,
                source_context=(source.context if source else None),
                destination_context=(destination.context if destination else None),
                repository=repo.to_dict(),
                change_request=change_request.to_dict(),
                annotated_path=assets["annotated"],
                agent_annotated_path=assets.get("agent-annotated"),
            )
            try:
                mirror_latest(
                    annotated_path=assets.get("agent-annotated", assets["annotated"]),
                    context_md=context_md,
                    capture_id=session.capture_id,
                    assets=assets,
                )
            except Exception:
                log.warning("Failed to mirror latest capture", exc_info=True)

            return PipelineResult(
                capture_id=session.capture_id,
                application_mode=application_mode,
                raw_path=assets["raw"],
                annotated_path=assets["annotated"],
                context_path=assets["context_crop"],
                source_path=assets.get("source_crop"),
                destination_path=assets.get("destination_crop"),
                source=source,
                destination=destination,
                repository=repo.to_dict(),
                change_request=change_request.to_dict(),
                record=record.to_dict(),
            )
        except Exception as e:  # noqa: BLE001 - pipeline must surface errors typed
            log.exception("Capture pipeline failed for session %s", session.capture_id)
            return PipelineResult(
                capture_id=session.capture_id,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Annotation freezing
    # ------------------------------------------------------------------

    def _freeze_annotations(self, session: CaptureSession, rect: dict) -> list[Annotation]:
        if session.annotations:
            return session.annotations

        source_ann = Annotation(
            id=f"ann_src_{session.capture_id}",
            type="rectangle",
            role="source",
            label="Source selection",
            geometry={
                "x": rect.get("x", 0),
                "y": rect.get("y", 0),
                "width": rect.get("width", 0),
                "height": rect.get("height", 0),
            },
        )
        return [source_ann]

    # ------------------------------------------------------------------
    # Anchor resolution cascade: browser DOM → native UIA/title → visual
    # ------------------------------------------------------------------

    def _resolve_anchor(self, role: str, ann: Annotation) -> AnchorResolution:
        x, y, w, h = (
            ann.geometry.get("x", 0.0),
            ann.geometry.get("y", 0.0),
            ann.geometry.get("width", 0.0),
            ann.geometry.get("height", 0.0),
        )
        cx, cy = int(x + w / 2), int(y + h / 2)

        # Tier 1: browser extension DOM inspection (richest, exact).
        element = self._browser_inspect(cx, cy)
        if element is not None:
            return AnchorResolution(
                role=role,
                context=self._browser_context(element),
                mapping=self._browser_mapping(element),
                source="browser_dom",
                confidence=0.9,
                resolved=True,
            )

        # Tier 2: native UIA / window-title / URL resolution.
        native = self._native_resolve((x, y, w, h))
        if native is not None:
            return AnchorResolution(
                role=role,
                context=native,
                source=native.get("source", "native"),
                confidence=native.get("confidence", 0.0),
                resolved=native.get("resolved", False),
            )

        # Tier 3: visual-only fallback (kept as resolved=False, low confidence).
        return AnchorResolution(
            role=role,
            context={"source": "visual_fallback", "confidence": 0.25},
            source="visual_fallback",
            confidence=0.25,
            resolved=False,
        )

    def _browser_inspect(self, x: int, y: int) -> Optional[dict]:
        bridge = self.ws_bridge
        if bridge is None or not getattr(bridge, "connected", False):
            return None
        try:
            element = bridge.inspect(x, y, timeout=3.0)
        except Exception as e:  # noqa: BLE001 - bridge may be mid-disconnect
            log.debug("Browser inspect failed at (%d, %d): %s", x, y, e)
            return None
        if not isinstance(element, dict) or element.get("error"):
            return None
        return element

    @staticmethod
    def _browser_context(element: dict) -> dict:
        a11y = element.get("accessibility") or {}
        return {
            "source": "browser_dom",
            "tag": element.get("tagName", ""),
            "text": element.get("text", "") or "",
            "name": a11y.get("name", "") or "",
            "role": a11y.get("role", ""),
            "selector": element.get("selector", ""),
            "elementPath": element.get("elementPath", ""),
            "id": element.get("id", "") or "",
            "className": element.get("className", "") or "",
            "href": element.get("href", "") or "",
            "arrowId": element.get("arrowId", "") or "",
            "testId": element.get("testId", "") or "",
            "boundingBox": element.get("boundingBox", {}),
            "pageUrl": element.get("pageUrl", ""),
            "route": element.get("route", ""),
            "viewport": element.get("viewport", {}),
            "computedStyles": element.get("computedStyles", {}),
            "reactComponents": element.get("reactComponents", "") or "",
            "confidence": 0.9,
        }

    @staticmethod
    def _browser_mapping(element: dict) -> dict:
        """Map a DOM element to a likely source file via React debug metadata."""
        react = element.get("reactSource")
        if react and react.get("fileName"):
            components = (element.get("reactComponents") or "").split(" > ")
            return {
                "resolved": True,
                "source_file": react["fileName"],
                "source_line": react.get("lineNumber"),
                "component": components[-1] if components else None,
                "confidence": 0.8,
                "evidence": ["Browser React debug source"],
            }
        return {}

    def _native_resolve(self, rect: Tuple[float, float, float, float]) -> Optional[dict]:
        try:
            resolution = self.resolver.resolve(
                (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            )
        except Exception as e:  # noqa: BLE001 - resolver never blocks the pipeline
            log.debug("Native resolve failed: %s", e)
            return None
        if resolution is None:
            return None

        d = resolution.to_dict()
        resolved = bool(d.get("ok")) and d.get("kind") != "screenshot_only"
        ctx = {
            "source": d.get("source", "native"),
            "kind": d.get("kind"),
            "file_path": d.get("file_path"),
            "source_url": d.get("source_url"),
            "window_title": d.get("window_title"),
            "selected_text": d.get("selected_text"),
            "content_category": d.get("content_category"),
            "confidence": d.get("confidence", 0.25),
            "resolved": resolved,
        }
        return ctx

    # ------------------------------------------------------------------
    # Asset persistence
    # ------------------------------------------------------------------

    def _save_assets(self, capture_id: str, raw_img, annotated_img, context_crop,
                     source_crop, dest_crop,
                     agent_annotated=None, agent_crop=None) -> dict:
        os.makedirs(self.screenshots_dir, exist_ok=True)
        safe_id = capture_id.replace(":", "_")
        paths = {
            "raw": os.path.join(self.screenshots_dir, f"raw_{safe_id}.png"),
            "annotated": os.path.join(self.screenshots_dir, f"annotated_{safe_id}.png"),
            "context_crop": os.path.join(self.screenshots_dir, f"context_crop_{safe_id}.png"),
        }
        raw_img.save(paths["raw"], "PNG")
        annotated_img.save(paths["annotated"], "PNG")
        context_crop.save(paths["context_crop"], "PNG")

        if source_crop is not None:
            paths["source_crop"] = os.path.join(self.screenshots_dir, f"source_crop_{safe_id}.png")
            source_crop.save(paths["source_crop"], "PNG")
        if dest_crop is not None:
            paths["destination_crop"] = os.path.join(self.screenshots_dir, f"destination_crop_{safe_id}.png")
            dest_crop.save(paths["destination_crop"], "PNG")

        # Agent-optimized assets (≤1568px, served via MCP by default).
        if agent_annotated is not None:
            paths["agent-annotated"] = os.path.join(self.screenshots_dir, f"agent_annotated_{safe_id}.png")
            agent_annotated.save(paths["agent-annotated"], "PNG")
        if agent_crop is not None:
            paths["agent-crop"] = os.path.join(self.screenshots_dir, f"agent_crop_{safe_id}.png")
            agent_crop.save(paths["agent-crop"], "PNG")

        return paths

    # ------------------------------------------------------------------
    # Record persistence
    # ------------------------------------------------------------------

    def _build_record(
        self,
        session: CaptureSession,
        rect: dict,
        instruction: str,
        cursor: Optional[Tuple[int, int]],
        window_title: str,
        annotated_path: str,
        source: Optional[AnchorResolution],
        change_request: Optional[ChangeRequest] = None,
        assets: Optional[dict] = None,
        target: Optional[dict] = None,
    ) -> CaptureRecord:
        source_ctx = (source.context if source else {}) or {}

        computed_styles = ""
        a11y = ""
        element = self._last_browser_element(source_ctx)
        if element:
            try:
                computed_styles = json.dumps(element.get("computedStyles", {}))
            except (TypeError, ValueError):
                computed_styles = ""
            try:
                a11y = json.dumps(element.get("accessibility", {}))
            except (TypeError, ValueError):
                a11y = ""

        return CaptureRecord(
            id=session.capture_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            screenshot_path=annotated_path,
            assets=assets or {},
            target=target,
            annotation_text=instruction,
            cursor_x=(cursor[0] if cursor else 0),
            cursor_y=(cursor[1] if cursor else 0),
            element_selector=source_ctx.get("selector", "") or "",
            element_path=source_ctx.get("elementPath", "") or "",
            react_components=source_ctx.get("reactComponents", "") or "",
            computed_styles=computed_styles,
            accessibility=a11y,
            selected_text=source_ctx.get("selected_text", "") or "",
            bounding_box=rect,
            window_title=window_title or source_ctx.get("window_title", "") or "",
            change_request=change_request.to_dict() if change_request else None,
        )

    @staticmethod
    def _last_browser_element(source_ctx: dict) -> Optional[dict]:
        return source_ctx if source_ctx.get("source") == "browser_dom" else None


__all__ = ["ContextOrchestrator", "PipelineResult", "AnchorResolution"]
