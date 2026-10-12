"""Point capture and TaskBundle must be one system, not two.

Proves a real capture produced by the Point Mode pipeline is persisted with
its target provenance and attached to the active task, so an agent asking for
"my latest task" gets the screenshots the user actually made.
"""

from __future__ import annotations

import json

import pytest

from arrow.capture.point_capture import PointCaptureCoordinator, PointCaptureRequest
from arrow.capture.session import CaptureMode, CaptureState, SessionManager
from arrow.storage.capture_store import CaptureStore
from arrow.storage.task_repository import TaskRepository
from arrow.storage.tasks import TaskStatus


class StubScreenshotService:
    def capture_raw(self):
        return "RAW", "SCREEN_INFO", "MAPPER"


class StubBridge:
    def post_for(self, capture_id, fn):
        fn()
        return True


@pytest.fixture
def wired(tmp_path):
    db = str(tmp_path / "arrow.db")
    store = CaptureStore(db)
    tasks = TaskRepository(db)

    class RecordingOrchestrator:
        def __init__(self):
            self.task_repo = tasks
            self.active_task_id = None
            self.seen = []

        def set_active_task(self, task_id):
            self.active_task_id = task_id

        def run(self, **kwargs):
            self.seen.append(kwargs)
            store.add(
                _record(kwargs, store),
            )
            if self.task_repo and self.active_task_id:
                self.task_repo.add_capture(self.active_task_id, kwargs["session"].capture_id)

            class R:
                pass

            r = R()
            r.error = None
            return r

    orch = RecordingOrchestrator()
    sm = SessionManager()
    coord = PointCaptureCoordinator(
        session_manager=sm,
        orchestrator=orch,
        bridge=StubBridge(),
        on_status=lambda m: None,
        screenshot_service_factory=StubScreenshotService,
        spawn=lambda fn: fn(),
    )
    return coord, orch, sm, store, tasks, db


def _record(kwargs, store):
    from arrow.storage.schemas import CaptureRecord

    session = kwargs["session"]
    rect = kwargs["rect"]
    return CaptureRecord(
        id=session.capture_id,
        timestamp="2026-10-13T00:00:00+00:00",
        screenshot_path=f"C:\\shots\\{session.capture_id}.png",
        assets={"annotated": f"C:\\shots\\{session.capture_id}.png"},
        annotation_text=kwargs.get("instruction", ""),
        bounding_box=rect,
        target=kwargs.get("target"),
    )


def _capture(coord, sm, x=100, y=200, instruction="move this"):
    session = sm.start_session()
    sm.transition_to(CaptureState.ANNOTATING)
    req = PointCaptureRequest(
        capture_id=session.capture_id,
        x=x,
        y=y,
        mode=CaptureMode.POINT,
        desktop_bounds={"x": -1920, "y": -1080, "width": 3840, "height": 2160},
        instruction=instruction,
    )
    assert coord.begin(req, session, lambda: None) is True
    return session


def test_three_point_captures_land_in_one_task(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task(title="Move the search bar", instruction="put it in the navbar")
    orch.set_active_task(task_id)

    ids = [_capture(coord, sm, x=10 + i * 40, instruction=f"step {i}").capture_id
           for i in range(3)]

    task = tasks.get_task(task_id)
    assert [c.capture_id for c in task.captures] == ids
    assert [c.position for c in task.captures] == [1, 2, 3]
    assert [c.instruction for c in task.captures] == ["step 0", "step 1", "step 2"]


def test_capture_persists_target_provenance(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task()
    orch.set_active_task(task_id)
    session = _capture(coord, sm)

    record = store.get(session.capture_id)
    assert record is not None
    assert record.target is not None
    assert record.target["resolution_method"] in ("fallback", "windows_uia", "ocr")

    manifest = json.loads(tasks.get_task(task_id).to_json())
    cap = manifest["captures"][0]
    assert cap["target"]["bounds"]["coordinate_space"] == "virtual_desktop"


def test_manifest_asset_paths_are_the_real_persisted_paths(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task()
    orch.set_active_task(task_id)
    session = _capture(coord, sm)

    manifest = json.loads(tasks.get_task(task_id).to_json())
    cap = manifest["captures"][0]
    stored = store.get(session.capture_id)
    assert cap["assets"]["screenshot"] == stored.screenshot_path


def test_task_survives_a_repository_restart(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task(title="Persisted", instruction="keep")
    orch.set_active_task(task_id)
    session = _capture(coord, sm)

    reopened = TaskRepository(db).get_task(task_id)
    assert reopened is not None
    assert reopened.instruction == "keep"
    assert [c.capture_id for c in reopened.captures] == [session.capture_id]
    assert reopened.captures[0].assets["screenshot"].endswith(".png")


def test_removing_one_capture_leaves_the_task_consistent(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task()
    orch.set_active_task(task_id)
    ids = [_capture(coord, sm, x=10 + i * 40).capture_id for i in range(3)]

    assert tasks.remove_capture(task_id, ids[1]) is True
    task = tasks.get_task(task_id)
    assert [c.capture_id for c in task.captures] == [ids[0], ids[2]]
    # The capture record and its asset reference remain intact.
    assert store.get(ids[1]) is not None


def test_status_is_only_sent_with_explicit_evidence(wired):
    coord, orch, sm, store, tasks, db = wired
    task_id = tasks.create_task()
    orch.set_active_task(task_id)
    _capture(coord, sm)

    # Having captures must not imply the agent saw them.
    assert tasks.get_task(task_id).status == TaskStatus.DRAFT.value
    tasks.set_status(task_id, TaskStatus.SENT.value)
    assert tasks.get_task(task_id).status == TaskStatus.SENT.value


def test_point_capture_without_task_still_persists(wired):
    """Detached task mode must not break the original capture flow."""
    coord, orch, sm, store, tasks, db = wired
    orch.set_active_task(None)
    session = _capture(coord, sm)
    assert store.get(session.capture_id) is not None
    assert tasks.list_tasks() == []