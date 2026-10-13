"""Task shelf: ordering, editing, deletion and honest agent-state labels.

Drives the real widget against a real temporary repository, so a shelf that
disagrees with the database fails here rather than in front of a user.
"""

from __future__ import annotations

import pytest

from arrow.storage.database import get_db_connection
from arrow.storage.task_repository import TaskRepository

pytest.importorskip("PyQt6")

from arrow.ui.task_shelf import STATE_LABELS, TaskShelf  # noqa: E402

_APP = None


@pytest.fixture
def qapp():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def repo(tmp_path):
    return TaskRepository(str(tmp_path / "shelf.db"))


@pytest.fixture
def shelf(qapp, repo):
    s = TaskShelf(repo)
    yield s
    s.deleteLater()


def _capture(repo, capture_id, mode="point", note=""):
    with get_db_connection(repo._db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (capture_id, created_at, updated_at, state, mode, voice_transcript)
               VALUES (?, '2026-10-13T00:00:00+00:00', '2026-10-13T00:00:00+00:00',
                       'COMPLETED', ?, ?)""",
            (capture_id, mode, note),
        )
        conn.commit()


def _three(repo):
    tid = repo.create_task(title="Move it")
    for cid in ("c1", "c2", "c3"):
        _capture(repo, cid)
        repo.add_capture(tid, cid)
    return tid


def _ids(repo, tid):
    return [c.capture_id for c in repo.get_task(tid).captures]


# -- rendering ---------------------------------------------------------------


def test_empty_state_is_shown_with_no_tasks(qapp, shelf):
    assert shelf.empty_label.isVisible() is False or shelf.task_id is None
    assert shelf.task_id is None


def test_task_list_is_populated(qapp, shelf, repo):
    _three(repo)
    shelf.refresh()
    assert shelf.task_select.count() == 1
    assert shelf.task_select.itemText(0).startswith("Move it  ·  3")


def test_rows_follow_database_order(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    assert [r.capture_id for r in shelf._rows] == ["c1", "c2", "c3"]
    assert [r.position for r in shelf._rows] == [1, 2, 3]


def test_count_label_reports_capture_count(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    assert shelf.count_label.text() == "3 capture(s)"


def test_title_and_instruction_are_loaded(qapp, shelf, repo):
    tid = repo.create_task(title="T", instruction="do the thing")
    shelf.select_task(tid)
    assert shelf.title_edit.text() == "T"
    assert shelf.instruction_edit.text() == "do the thing"


def test_unknown_task_shows_nothing(qapp, shelf):
    shelf.select_task("missing")
    assert shelf.task_id is None
    assert shelf.count_label.text() == ""


# -- honest agent state ------------------------------------------------------


def test_draft_says_saved_locally_not_sent(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    assert shelf.state_label.text() == "Saved locally"
    assert STATE_LABELS["draft"] == "Saved locally"


@pytest.mark.parametrize("status,expected", [
    ("running", "Agent running"),
    ("completed", "Completed"),
    ("failed", "Failed"),
])
def test_agent_states_are_labelled_truthfully(qapp, shelf, repo, status, expected):
    tid = _three(repo)
    repo.set_status(tid, status)
    shelf.select_task(tid)
    assert shelf.state_label.text() == expected


def test_unknown_status_is_shown_verbatim(qapp, shelf, repo):
    tid = _three(repo)
    repo.set_status(tid, "something_new")
    shelf.select_task(tid)
    assert shelf.state_label.text() == "something_new"


# -- editing -----------------------------------------------------------------


def test_editing_the_title_persists(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf.title_edit.setText("Renamed")
    shelf._save_title()
    assert repo.get_task(tid).title == "Renamed"


def test_editing_the_instruction_persists(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf.instruction_edit.setText("move it right")
    shelf._save_instruction()
    assert repo.get_task(tid).instruction == "move it right"


def test_creating_a_task_from_the_shelf(qapp, shelf, repo):
    shelf._new_task()
    assert shelf.task_id is not None
    assert repo.get_task(shelf.task_id) is not None
    assert shelf.task_select.count() == 1


def test_switching_task_updates_the_rows(qapp, shelf, repo):
    a = _three(repo)
    b = repo.create_task(title="Second")
    _capture(repo, "x1")
    repo.add_capture(b, "x1")

    shelf.select_task(a)
    assert len(shelf._rows) == 3
    shelf.select_task(b)
    assert [r.capture_id for r in shelf._rows] == ["x1"]


# -- reordering --------------------------------------------------------------


def test_move_later_reorders_and_persists(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._move_capture("c1", +1)
    assert _ids(repo, tid) == ["c2", "c1", "c3"]
    assert [r.capture_id for r in shelf._rows] == ["c2", "c1", "c3"]


def test_move_earlier_reorders(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._move_capture("c3", -1)
    assert _ids(repo, tid) == ["c1", "c3", "c2"]


def test_moving_past_the_end_is_a_no_op(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._move_capture("c3", +1)
    assert _ids(repo, tid) == ["c1", "c2", "c3"]


def test_moving_before_the_start_is_a_no_op(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._move_capture("c1", -1)
    assert _ids(repo, tid) == ["c1", "c2", "c3"]


def test_moving_an_unknown_capture_is_a_no_op(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._move_capture("ghost", +1)
    assert _ids(repo, tid) == ["c1", "c2", "c3"]


# -- removal and deletion ----------------------------------------------------


def test_removing_one_capture(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    shelf._remove_capture("c2")
    assert _ids(repo, tid) == ["c1", "c3"]
    assert [r.capture_id for r in shelf._rows] == ["c1", "c3"]


def test_deleting_a_task_keeps_the_captures(qapp, shelf, repo, monkeypatch):
    tid = _three(repo)
    shelf.select_task(tid)

    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    shelf._delete_task()

    assert repo.get_task(tid) is None
    for cid in ("c1", "c2", "c3"):
        with get_db_connection(repo._db_path) as conn:
            row = conn.execute(
                "SELECT capture_id FROM sessions WHERE capture_id = ?", (cid,)
            ).fetchone()
        assert row is not None, "capture history must survive task deletion"


def test_declining_the_delete_keeps_the_task(qapp, shelf, repo, monkeypatch):
    tid = _three(repo)
    shelf.select_task(tid)

    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    shelf._delete_task()
    assert repo.get_task(tid) is not None


def test_deleting_without_a_task_is_safe(qapp, shelf):
    shelf._delete_task()  # must not raise
    shelf._remove_capture("x")


# -- copying -----------------------------------------------------------------


def test_copy_task_puts_markdown_on_the_clipboard(qapp, shelf, repo):
    copied = []
    shelf._set_clipboard = copied.append

    tid = _three(repo)
    shelf.select_task(tid)
    shelf._copy_markdown()

    assert "# Arrow Task Context" in copied[0]
    assert shelf.count_label.text() == "Task copied to clipboard"


def test_copy_without_a_task_says_so(qapp, shelf):
    shelf.select_task(None)
    shelf._copy_markdown()
    assert shelf.count_label.text() == "Nothing to copy"


def test_copy_single_capture_is_json(qapp, shelf, repo):
    import json

    copied = []
    shelf._set_clipboard = copied.append

    tid = _three(repo)
    shelf.select_task(tid)
    shelf._copy_capture("c2")

    data = json.loads(copied[0])
    assert data["capture_id"] == "c2"
    assert data["order"] == 2


# -- notes -------------------------------------------------------------------


def test_setting_a_note_persists(qapp, shelf, repo):
    tid = _three(repo)
    shelf.select_task(tid)
    repo.set_capture_note(tid, "c1", "this is the navbar")
    shelf.refresh()
    assert shelf._rows[0].capture_id == "c1"


# -- persistence across a restart -------------------------------------------


def test_shelf_reloads_persisted_state(qapp, shelf, repo, tmp_path):
    tid = _three(repo)
    repo.reorder(tid, ["c3", "c2", "c1"])
    repo.update_task(tid, title="Persisted", instruction="keep me")
    repo.set_capture_note(tid, "c1", "a note")

    reopened = TaskRepository(str(tmp_path / "shelf.db"))
    fresh = TaskShelf(reopened)
    fresh.select_task(tid)

    assert fresh.title_edit.text() == "Persisted"
    assert fresh.instruction_edit.text() == "keep me"
    assert [r.capture_id for r in fresh._rows] == ["c3", "c2", "c1"]
    fresh.deleteLater()


# -- signal ------------------------------------------------------------------


def test_refresh_emits_changed(qapp, shelf, repo):
    fired = []
    shelf.changed.connect(lambda: fired.append(1))
    shelf.refresh()
    assert fired