"""Task shelf: the multi-capture view inside the notch.

Kept out of :mod:`arrow.ui.notch` so it can be built and tested on its own.
The notch hosts it; it does not re-implement the notch.

Every mutation here goes through :class:`TaskRepository`, so the shelf can
never show an order the database does not hold. Agent state is rendered from
the stored status only — the shelf never claims an agent has seen a task
because the shelf happens to be open.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger("arrow.ui.task_shelf")

# Human labels for stored task statuses. Anything unknown is shown verbatim
# rather than being dressed up as progress.
STATE_LABELS = {
    "draft": "Saved locally",
    "ready": "Task ready",
    "handoff_requested": "Handoff requested",
    "sent": "Sent to agent",
    "running": "Agent running",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


class CaptureRow(QFrame):
    """One capture in the shelf, in the user's order."""

    remove_requested = pyqtSignal(str)
    note_requested = pyqtSignal(str)
    move_requested = pyqtSignal(str, int)  # capture_id, delta (-1 left, +1 right)
    copy_requested = pyqtSignal(str)

    def __init__(self, artifact, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.capture_id = artifact.capture_id
        self.position = artifact.position
        self.setObjectName("captureRow")
        self.setFixedWidth(230)
        self.setStyleSheet("""
            #captureRow {
                background: #141B29;
                border: 1px solid rgba(130,168,232,30);
                border-radius: 12px;
            }
            #captureRow:hover { border: 1px solid rgba(102,166,255,105); }
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        order = QLabel(str(artifact.position))
        order.setFixedSize(18, 18)
        order.setAlignment(Qt.AlignmentFlag.AlignCenter)
        order.setStyleSheet(
            "background: #66A6FF; color: #06121F; border-radius: 9px;"
            "font-size: 11px; font-weight: 700;"
        )
        head.addWidget(order)

        label = QLabel(artifact.application or artifact.window_title or "Screen")
        label.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        label.setStyleSheet("color: #93A8C7; background: transparent;")
        label.setToolTip(artifact.window_title or "")
        head.addWidget(label, 1)
        v.addLayout(head)

        note = QLabel(artifact.note or artifact.instruction or "No instruction")
        note.setWordWrap(True)
        note.setFixedHeight(34)
        note.setFont(QFont("Segoe UI", 8))
        note.setStyleSheet("color: #DCEBFF; background: transparent;")
        note.setToolTip(artifact.note or artifact.instruction or "")
        v.addWidget(note)

        if artifact.target and artifact.target.get("resolution_method"):
            method = artifact.target["resolution_method"]
            text = ("target not identified" if method == "fallback"
                    else f"via {method}")
            tag = QLabel(text)
            tag.setFont(QFont("Segoe UI", 7))
            tag.setStyleSheet("color: #6B7C93; background: transparent;")
            v.addWidget(tag)

        btns = QHBoxLayout()
        btns.setSpacing(4)
        for text, slot, tip in (
            ("◀", lambda: self.move_requested.emit(self.capture_id, -1), "Move earlier"),
            ("▶", lambda: self.move_requested.emit(self.capture_id, +1), "Move later"),
            ("Edit", lambda: self.note_requested.emit(self.capture_id), "Edit note"),
            ("Copy", lambda: self.copy_requested.emit(self.capture_id), "Copy this capture"),
            ("✕", lambda: self.remove_requested.emit(self.capture_id), "Remove from task"),
        ):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setFixedHeight(20)
            b.setFont(QFont("Segoe UI", 7))
            b.setStyleSheet(_BTN_QSS)
            b.clicked.connect(slot)
            btns.addWidget(b)
        v.addLayout(btns)


_BTN_QSS = """
    QPushButton {
        color: #C7D6EA; background: #1B2436; border: 1px solid #2A3A55;
        border-radius: 6px; padding: 1px 5px; font-size: 11px;
    }
    QPushButton:hover { background: #24406B; color: white; }
"""


class TaskShelf(QWidget):
    """Shows one task's captures in order, and edits that task."""

    changed = pyqtSignal()

    def __init__(self, repository, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._repo = repository
        self._task_id: Optional[str] = None

        root = QVBoxLayout(self)
        # This shelf shares the notch window with the capture history, so it
        # must be willing to shrink in both axes: anything with a large
        # minimum is silently clipped at the window edge rather than scaled.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        # -- task selector + state -----------------------------------------
        top = QHBoxLayout()
        top.setSpacing(8)

        self.task_select = QComboBox()
        self.task_select.setMinimumWidth(60)
        # Ignored: a combo sized to its contents pushes the '+ Task' button
        # past the notch's right edge instead of giving up width.
        self.task_select.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.task_select.currentIndexChanged.connect(self._on_task_changed)
        top.addWidget(QLabel("Task", self))
        top.addWidget(self.task_select, 1)

        self.state_label = QLabel("", self)
        self.state_label.setMaximumWidth(120)
        self.state_label.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        self.state_label.setStyleSheet("color: #93A8C7; background: transparent;")
        top.addWidget(self.state_label)
        # No '+ Task' button here on purpose: the notch toolbar already has
        # one, and a second copy overflowed the panel's right edge.
        root.addLayout(top)

        # -- title + instruction -------------------------------------------
        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("Task title")
        self.title_edit.setStyleSheet(_EDIT_QSS)
        self.title_edit.editingFinished.connect(self._save_title)
        root.addWidget(self.title_edit)

        self.instruction_edit = QLineEdit(self)
        self.instruction_edit.setPlaceholderText(
            "What should the agent change? e.g. Move the search bar into the navbar"
        )
        self.instruction_edit.setStyleSheet(_EDIT_QSS)
        self.instruction_edit.editingFinished.connect(self._save_instruction)
        root.addWidget(self.instruction_edit)

        # -- capture shelf --------------------------------------------------
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumHeight(84)
        self._scroll.setMaximumHeight(132)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._strip = QWidget()
        self._strip.setStyleSheet("background: transparent;")
        self._hbox = QHBoxLayout(self._strip)
        self._hbox.setContentsMargins(0, 0, 0, 0)
        self._hbox.setSpacing(10)
        self._hbox.addStretch()
        self._scroll.setWidget(self._strip)
        root.addWidget(self._scroll)

        self.empty_label = QLabel("No captures in this task yet. Click Point and "
                                  "click an element on screen.", self)
        self.empty_label.setWordWrap(True)
        self.empty_label.setFont(QFont("Segoe UI", 9))
        self.empty_label.setStyleSheet("color: #6B7C93; background: transparent;")
        root.addWidget(self.empty_label)

        # -- footer ---------------------------------------------------------
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self.copy_btn = QPushButton("Copy task", self)
        self.copy_btn.setStyleSheet(_BTN_QSS)
        self.copy_btn.clicked.connect(self._copy_markdown)
        bottom.addWidget(self.copy_btn)

        self.delete_btn = QPushButton("Delete task", self)
        self.delete_btn.setStyleSheet(_BTN_QSS)
        self.delete_btn.clicked.connect(self._delete_task)
        bottom.addWidget(self.delete_btn)

        bottom.addStretch()
        self.count_label = QLabel("", self)
        self.count_label.setFont(QFont("Segoe UI", 8))
        self.count_label.setStyleSheet("color: #6B7C93; background: transparent;")
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

        self._rows: list[CaptureRow] = []
        self.refresh()

    # -- rendering ---------------------------------------------------------

    @property
    def task_id(self) -> Optional[str]:
        return self._task_id

    def select_task(self, task_id: Optional[str]) -> None:
        self._task_id = task_id
        self.refresh()

    def refresh(self) -> None:
        """Reload the task list and the current task's captures."""
        self.task_select.blockSignals(True)
        self.task_select.clear()
        tasks = self._repo.list_tasks(limit=50)
        for t in tasks:
            label = t["title"] or "(untitled)"
            self.task_select.addItem(f"{label}  ·  {t['capture_count']}", t["task_id"])
        index = next(
            (i for i, t in enumerate(tasks) if t["task_id"] == self._task_id), 0
        )
        if tasks:
            self.task_select.setCurrentIndex(index)
            self._task_id = tasks[index]["task_id"]
        else:
            self._task_id = None
        self.task_select.blockSignals(False)

        for row in self._rows:
            self._hbox.removeWidget(row)
            row.deleteLater()
        self._rows = []

        task = self._repo.get_task(self._task_id) if self._task_id else None
        if task is None:
            self.title_edit.clear()
            self.instruction_edit.clear()
            self.state_label.setText("")
            self.count_label.setText("")
            self.empty_label.setVisible(True)
            self.changed.emit()
            return

        self.title_edit.setText(task.title)
        self.instruction_edit.setText(task.instruction)
        self.state_label.setText(STATE_LABELS.get(task.status, task.status))
        self.count_label.setText(f"{len(task.captures)} capture(s)")
        self.empty_label.setVisible(not task.captures)

        for artifact in sorted(task.captures, key=lambda c: c.position):
            row = CaptureRow(artifact)
            row.remove_requested.connect(self._remove_capture)
            row.note_requested.connect(self._edit_note)
            row.move_requested.connect(self._move_capture)
            row.copy_requested.connect(self._copy_capture)
            self._hbox.insertWidget(self._hbox.count() - 1, row)
            self._rows.append(row)
        self.changed.emit()

    # -- edits -------------------------------------------------------------

    def _on_task_changed(self, index: int) -> None:
        item = self.task_select.itemData(index)
        if item:
            self._task_id = item
            self.refresh()

    def _new_task(self) -> None:
        self._task_id = self._repo.create_task()
        self.refresh()

    def _save_title(self) -> None:
        if self._task_id:
            self._repo.update_task(self._task_id, title=self.title_edit.text().strip())
            self.refresh()

    def _save_instruction(self) -> None:
        if self._task_id:
            self._repo.update_task(
                self._task_id, instruction=self.instruction_edit.text().strip()
            )
            self.refresh()

    def _remove_capture(self, capture_id: str) -> None:
        if self._task_id:
            self._repo.remove_capture(self._task_id, capture_id)
            self.refresh()

    def _move_capture(self, capture_id: str, delta: int) -> None:
        if not self._task_id:
            return
        task = self._repo.get_task(self._task_id)
        if task is None:
            return
        ids = [c.capture_id for c in sorted(task.captures, key=lambda c: c.position)]
        try:
            i = ids.index(capture_id)
        except ValueError:
            return
        j = i + delta
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            self._repo.reorder(self._task_id, ids)
            self.refresh()

    def _edit_note(self, capture_id: str) -> None:
        from PyQt6.QtWidgets import QInputDialog

        if not self._task_id:
            return
        task = self._repo.get_task(self._task_id)
        if task is None:
            return
        current = next(
            (c.note for c in task.captures if c.capture_id == capture_id), ""
        )
        note, ok = QInputDialog.getText(
            self, "Capture note", "What is this screenshot for?",
            text=current or "",
        )
        if ok:
            self._repo.set_capture_note(self._task_id, capture_id, note.strip())
            self.refresh()

    def _set_clipboard(self, text: str) -> None:
        """Single place the shelf writes the clipboard.

        A seam rather than an inline call so tests do not have to depend on
        Qt's process-global clipboard, which does not flush deterministically
        when the event loop is not spinning.
        """
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _copy_capture(self, capture_id: str) -> None:
        import json

        if not self._task_id:
            return
        task = self._repo.get_task(self._task_id)
        if task is None:
            return
        for cap in task.captures:
            if cap.capture_id == capture_id:
                self._set_clipboard(
                    json.dumps(cap.to_manifest(), indent=2, ensure_ascii=False)
                )
                self.count_label.setText(f"Copied {cap.capture_id[-6:]}")
                return

    def _copy_markdown(self) -> None:
        task = self._repo.get_task(self._task_id) if self._task_id else None
        if task is None:
            self.count_label.setText("Nothing to copy")
            return
        self._set_clipboard(task.to_markdown())
        self.count_label.setText("Task copied to clipboard")

    def _delete_task(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        if not self._task_id:
            return
        reply = QMessageBox.question(
            self,
            "Delete task",
            "Delete this task? The screenshots are kept in your capture history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._repo.delete_task(self._task_id)
        self._task_id = None
        self.refresh()


_EDIT_QSS = """
    QLineEdit {
        color: #E6EEF9; background: #141B29;
        border: 1px solid #2A3A55; border-radius: 8px;
        padding: 6px 9px; font-size: 11px;
    }
    QLineEdit:focus { border: 1px solid #66A6FF; }
"""


__all__ = ["CaptureRow", "STATE_LABELS", "TaskShelf"]