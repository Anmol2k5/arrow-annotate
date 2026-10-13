"""Allow/Deny approval panel for agent-requested actions.

An approval authorises exactly one bounded action. Deny, timeout, Stop and a
changed target all execute nothing. The panel never blocks: the agent waits on
:mod:`arrow.server.agent_actions`, and the user answers whenever they see it.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger("arrow.ui.approval_panel")

PANEL_W = 420


class ApprovalPanel(QFrame):
    """A small card asking the user to allow or deny one action."""

    decided = None  # populated per-instance below

    def __init__(
        self,
        decide: Callable[[str, bool], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._decide = decide
        self._action_id: Optional[str] = None
        self.setFixedWidth(PANEL_W)
        self.setObjectName("approvalCard")
        self.setStyleSheet("""
            #approvalCard {
                background: #101B2D;
                border: 1px solid #2A3A55;
                border-radius: 12px;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(8)

        title = QLabel("Arrow AI Assist", self)
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #DCEBFF; background: transparent;")
        outer.addWidget(title)

        self._what = QLabel("", self)
        self._what.setWordWrap(True)
        self._what.setFont(QFont("Segoe UI", 9))
        self._what.setStyleSheet("color: #E6EEF9; background: transparent;")
        outer.addWidget(self._what)

        self._detail = QLabel("", self)
        self._detail.setWordWrap(True)
        self._detail.setFont(QFont("Segoe UI", 8))
        self._detail.setStyleSheet("color: #93A8C7; background: transparent;")
        outer.addWidget(self._detail)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.allow_btn = QPushButton("Allow once", self)
        self.allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.allow_btn.setStyleSheet("""
            QPushButton {
                color: #06121F; background: #66A6FF; border: none;
                border-radius: 10px; padding: 7px 14px;
                font-size: 12px; font-weight: 700;
            }
            QPushButton:hover { background: #3075D5; }
            QPushButton:disabled { background: #2A3A55; color: #6B7C93; }
        """)
        self.allow_btn.clicked.connect(lambda: self._answer(True))

        self.deny_btn = QPushButton("Deny", self)
        self.deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deny_btn.setStyleSheet("""
            QPushButton {
                color: #DCEBFF; background: transparent;
                border: 1px solid #2A3A55; border-radius: 10px;
                padding: 7px 14px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background: rgba(239,68,68,36); }
            QPushButton:disabled { color: #55637A; }
        """)
        self.deny_btn.clicked.connect(lambda: self._answer(False))

        row.addWidget(self.allow_btn)
        row.addWidget(self.deny_btn)
        row.addStretch()
        outer.addLayout(row)

        self.hide()

    # -- API ---------------------------------------------------------------

    @property
    def action_id(self) -> Optional[str]:
        return self._action_id

    def request(
        self,
        action_id: str,
        action_type: str,
        x: int,
        y: int,
        reason: str = "",
        expected_outcome: str = "",
    ) -> None:
        """Show a pending decision. Called on the GUI thread only."""
        self._action_id = action_id
        self._what.setText(f"An agent wants to <b>{_friendly(action_type)}</b>")
        detail = f"at ({x}, {y})"
        if reason:
            detail += f"\n{reason.strip()}"
        if expected_outcome:
            detail += f"\nExpected: {expected_outcome.strip()}"
        self._detail.setText(detail)
        self.allow_btn.setEnabled(True)
        self.deny_btn.setEnabled(True)
        self.show()
        self.raise_()

    def _answer(self, allow: bool) -> None:
        action_id = self._action_id
        self.reset()
        if action_id is None:
            return
        try:
            self._decide(action_id, allow)
        except Exception as e:  # noqa: BLE001 - never let the UI slot die
            log.warning("approval decision failed: %s", e)

    def reset(self) -> None:
        """Clear the panel without deciding anything."""
        self._action_id = None
        self.allow_btn.setEnabled(False)
        self.deny_btn.setEnabled(False)
        self.hide()

    def deny_all(self, decide: Optional[Callable[[str, bool], None]] = None) -> None:
        """Used by Stop: refuse whatever is on screen right now."""
        action_id = self._action_id
        self.reset()
        if action_id is not None:
            target = decide or self._decide
            try:
                target(action_id, False)
            except Exception as e:  # noqa: BLE001
                log.warning("deny-all failed: %s", e)


_FRIENDLY = {
    "click_target": "click on this element",
    "scroll_target": "scroll here",
    "preview_target": "show you this element",
    "highlight_target": "highlight this element",
    "capture_screenshot": "take a screenshot",
}


def _friendly(action_type: str) -> str:
    return _FRIENDLY.get(action_type, action_type.replace("_", " "))


__all__ = ["ApprovalPanel"]