"""Thread-safety helpers for marshalling work onto the Qt main thread.

Background workers must never touch widgets directly. They post callables
through :class:`UiBridge`, which delivers them on the thread that owns the
bridge (the main thread) via a queued Qt connection.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger("arrow.core.threads")

__all__ = ["UiBridge"]


class UiBridge(QObject):
    """Posts callables from worker threads to the Qt main thread.

    ``post_for`` additionally discards callbacks whose capture session has
    been superseded (stale callbacks), so a slow pipeline for capture A can
    never poke the UI after capture B started.
    """

    _invoke = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # Auto connection: the slot runs in the bridge's thread (main), so a
        # worker emit is queued and a main-thread emit runs immediately —
        # either way the callable never executes on the worker.
        self._invoke.connect(self._run)
        self._current_capture_id: Optional[str] = None

    # -- capture tracking (written from the main thread) -----------------
    def begin_capture(self, capture_id: str) -> None:
        """Mark capture_id as current; callbacks for older captures go stale."""
        self._current_capture_id = capture_id

    @property
    def current_capture_id(self) -> Optional[str]:
        return self._current_capture_id

    # -- posting ----------------------------------------------------------
    def post(self, fn: Callable[[], None]) -> None:
        """Queue fn to run on the main thread."""
        self._invoke.emit(fn)

    def post_for(self, capture_id: str, fn: Callable[[], None]) -> bool:
        """Queue fn only when capture_id is still the current capture.

        Returns True when the callback was queued, False when it was dropped
        as stale. The check is inherently racy across threads, so handlers
        must still verify session liveness (defense in depth).
        """
        if not capture_id or capture_id != self._current_capture_id:
            logger.debug("Dropping stale UI callback for capture %s", capture_id)
            return False
        self._invoke.emit(fn)
        return True

    @pyqtSlot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            logger.exception("Main-thread UI callback failed")
