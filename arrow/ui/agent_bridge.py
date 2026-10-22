"""Qt bridge for agent-requested visuals.

The local HTTP server runs on a background thread; Qt widgets belong to the
GUI thread. Every agent request that touches a widget is marshalled through a
queued signal here, so the server thread never calls into Qt directly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class AgentPointerBridge(QObject):
    """Marshals agent preview/hide requests onto the Qt main thread."""

    # Emitted from any thread; delivered on the main thread by Qt.
    preview_requested = pyqtSignal(int, int, object, str)
    hide_requested = pyqtSignal()
    # (action_id, action_type, x, y, reason, expected_outcome)
    approval_requested = pyqtSignal(str, str, int, int, str, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pointer: Any = None
        self._on_approval: Optional[Callable[..., None]] = None

    def attach(self, pointer: Any, on_approval: Callable[..., None]) -> None:
        self._pointer = pointer
        self._on_approval = on_approval
        self.preview_requested.connect(self._show)
        self.hide_requested.connect(self._hide)
        self.approval_requested.connect(self._ask)

    # -- safe to call from the server thread ------------------------------

    def request_preview(
        self, x: int, y: int, highlight: Optional[tuple] = None, label: str = ""
    ) -> None:
        self.preview_requested.emit(int(x), int(y), highlight, label)

    def request_hide(self) -> None:
        self.hide_requested.emit()

    def request_approval(
        self,
        action_id: str,
        action_type: str,
        x: int,
        y: int,
        reason: str = "",
        expected_outcome: str = "",
    ) -> None:
        self.approval_requested.emit(
            action_id, action_type, int(x), int(y), reason, expected_outcome
        )

    # -- main thread only -------------------------------------------------

    @pyqtSlot(int, int, object, str)
    def _show(self, x: int, y: int, highlight, label: str) -> None:
        if self._pointer is not None:
            self._pointer.point_at(x, y, highlight=highlight)

    @pyqtSlot()
    def _hide(self) -> None:
        if self._pointer is not None:
            self._pointer.hide_pointer()

    @pyqtSlot(str, str, int, int, str, str)
    def _ask(self, action_id, action_type, x, y, reason, expected_outcome) -> None:
        if self._on_approval is not None:
            self._on_approval(
                action_id, action_type, x, y, reason, expected_outcome
            )


__all__ = ["AgentPointerBridge"]