"""Point Mode capture lifecycle.

The click handler used to live as a closure inside ``app.main()``: it hid the
overlay with ``QTimer.singleShot(0, ...)`` while a worker thread began the
screenshot, and the worker then read ``overlay.geometry()`` from a non-GUI
thread. That made the captured pixels depend on scheduling, and made the whole
path untestable.

This module owns the lifecycle instead. The contract is deliberately narrow:

* Everything mutable is snapshotted on the GUI thread into a frozen
  :class:`PointCaptureRequest` **before** any worker starts.
* The overlay is torn down **synchronously on the GUI thread**; only then is
  the worker dispatched, so Arrow's own overlay cannot appear in the capture.
* The worker never touches a Qt widget. It only sees the frozen request.
* Every step re-checks session liveness, so a superseded or cancelled capture
  is never persisted and never reaches the UI.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

from arrow.capture.session import Annotation, CaptureMode, CaptureState, SessionManager

log = logging.getLogger("arrow.capture.point_capture")


@dataclass(frozen=True)
class PointCaptureRequest:
    """Immutable snapshot of one Point Mode click, taken on the GUI thread.

    Frozen because it is handed to a background thread: any field the worker
    can see must not change between the click and the capture.
    """

    capture_id: str
    x: int
    y: int
    mode: CaptureMode
    desktop_bounds: dict
    cursor: Tuple[int, int] = (0, 0)
    window_title: str = ""
    instruction: str = ""
    project_dir: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        # Frozen only stops rebinding; a shared dict would still be mutable
        # from the GUI thread after the worker starts.
        object.__setattr__(self, "desktop_bounds", dict(self.desktop_bounds))


class PointCaptureCoordinator:
    """Runs the Point Mode handoff: GUI-thread teardown, then worker pipeline."""

    def __init__(
        self,
        session_manager: SessionManager,
        orchestrator: Any,
        bridge: Any,
        on_status: Callable[[str], None],
        screenshot_service_factory: Callable[[], Any],
        resolver_factory: Optional[Callable[[], Any]] = None,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.sessions = session_manager
        self.orchestrator = orchestrator
        self.bridge = bridge
        self.on_status = on_status
        self._new_screenshot_service = screenshot_service_factory
        self._new_resolver = resolver_factory
        # Injectable so tests run synchronously and deterministically.
        self._spawn = spawn or (
            lambda fn: threading.Thread(target=fn, daemon=True).start()
        )
        self._in_flight: Optional[str] = None
        self._lock = threading.Lock()

    # -- GUI thread -------------------------------------------------------

    def is_capturing(self) -> bool:
        """True while a point capture owns the session (blocks double-clicks)."""
        with self._lock:
            return self._in_flight is not None

    def begin(
        self,
        request: PointCaptureRequest,
        session: Any,
        teardown_overlay: Callable[[], None],
    ) -> bool:
        """Snapshot phase. MUST be called on the GUI thread.

        Returns False when the capture was rejected (no session, wrong state,
        or a duplicate click while one is already running).
        """
        if session is None or session.capture_id != request.capture_id:
            return False

        with self._lock:
            # A second click in the same session must not start a second
            # capture; one click is one capture.
            if self._in_flight is not None:
                log.debug("Ignoring duplicate point click for %s", request.capture_id)
                return False
            self._in_flight = request.capture_id

        try:
            self.sessions.transition_to(CaptureState.COLLECTING_CONTEXT)
        except ValueError:
            self._clear_in_flight()
            return False

        # Synchronous GUI-thread teardown. By the time the worker runs, the
        # overlay is hidden and its fade timer has stopped, so it cannot
        # contaminate the screenshot.
        try:
            teardown_overlay()
        except Exception as e:  # pragma: no cover - defensive
            log.warning("Overlay teardown failed: %s", e)

        self._spawn(lambda: self._run(request, session))
        return True

    # -- worker thread ----------------------------------------------------

    def _clear_in_flight(self, capture_id: Optional[str] = None) -> None:
        with self._lock:
            if capture_id is None or self._in_flight == capture_id:
                self._in_flight = None

    def _resolve(self, request: PointCaptureRequest) -> Any:
        from arrow.context.point_target import resolve_point_target

        resolver = self._new_resolver() if self._new_resolver else None
        return resolve_point_target(
            request.x, request.y, desktop_bounds=request.desktop_bounds, resolver=resolver
        )

    def _run(self, request: PointCaptureRequest, session: Any) -> None:
        capture_id = request.capture_id
        try:
            if not self.sessions.is_active(capture_id):
                return  # cancelled before acquisition: never persist

            target = self._resolve(request)

            if not self.sessions.is_active(capture_id):
                return

            session.annotations = [
                Annotation(
                    id=f"ann_src_{capture_id}",
                    type="rectangle",
                    role="source",
                    label=target.label or "Pointed element",
                    geometry=dict(target.rect),
                )
            ]

            try:
                raw_img, screen_info, mapper = self._new_screenshot_service().capture_raw()
            except Exception as e:
                log.error("Point capture screenshot failed: %s", e)
                if self.sessions.fail_if_active(capture_id, f"screenshot failed: {e}"):
                    self._notify(capture_id, "Capture failed")
                return

            if not self.sessions.is_active(capture_id):
                return  # cancelled during acquisition: discard the image

            try:
                self.sessions.transition_to(CaptureState.PROCESSING)
                result = self.orchestrator.run(
                    session=session,
                    rect=target.rect,
                    instruction=request.instruction,
                    cursor=request.cursor,
                    window_title=request.window_title,
                    raw_img=raw_img,
                    screen_info=screen_info,
                    mapper=mapper,
                    target=target.to_dict(),
                )
            except Exception as e:
                log.error("Point capture pipeline failed: %s", e)
                if self.sessions.fail_if_active(capture_id, f"pipeline failed: {e}"):
                    self._notify(capture_id, "Capture failed")
                return

            if result.error:
                if self.sessions.fail_if_active(capture_id, str(result.error)):
                    self._notify(capture_id, "Capture failed")
                return

            # Final guard before the capture becomes visible anywhere.
            if not self.sessions.is_active(capture_id):
                return

            try:
                self.sessions.transition_to(CaptureState.PREVIEW)
                self.sessions.transition_to(CaptureState.READY)
            except ValueError:
                return

            self._notify(capture_id, "")
        finally:
            self._clear_in_flight(capture_id)

    def _notify(self, capture_id: str, message: str) -> None:
        """Post a status + refresh to the GUI thread, scoped to this capture."""
        if not message:
            return
        self.bridge.post_for(capture_id, lambda: self.on_status(message))


__all__ = ["PointCaptureRequest", "PointCaptureCoordinator"]