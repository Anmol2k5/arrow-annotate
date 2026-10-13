"""Agent-facing control surface: visual pointer preview and approved actions.

Design rules this module enforces:

* **Visual preview is not permission to click.** A preview request can only
  ever draw. Clicking lives behind :class:`AgentActions`, which requires a
  live, single-use, unexpired approval bound to one action and one target.
* **Fail closed.** If the pointer window, the approval store, or the expected
  foreground window cannot be verified, the answer is a refusal, never a
  best-effort action.
* The approval payload never carries a shell command. Only a fixed set of
  typed, bounded actions exists.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("arrow.server.agent_actions")

# Approvals are deliberately short-lived and single use.
DEFAULT_TTL_SECONDS = 45.0
# Bounds on an agent-supplied highlight rectangle, to stop absurd payloads.
MAX_HIGHLIGHT = 20000
# How far an element may sit from the approved point before we call it moved.
# Small enough to catch a re-laid-out UI, large enough to absorb sub-pixel
# rounding between two resolutions of the same element.
TARGET_DRIFT_TOLERANCE = 8


class AgentActionError(Exception):
    """Refusal. Carries a machine-readable reason code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail

    def to_dict(self) -> dict:
        return {"ok": False, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class ActionRequest:
    """A validated request for one bounded action.

    Frozen: it is compared against the approval later, and nothing may
    mutate it in between.
    """

    action_id: str
    action_type: str
    x: int
    y: int
    reason: str = ""
    expected_outcome: str = ""
    window_title: Optional[str] = None
    task_id: Optional[str] = None
    capture_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def identity(self) -> tuple:
        """What an approval must match exactly."""
        return (
            self.action_id,
            self.action_type,
            int(self.x),
            int(self.y),
            self.window_title,
        )


@dataclass
class Approval:
    """A single-use, expiring permission for exactly one action."""

    action_id: str
    action_type: str
    x: int
    y: int
    window_title: Optional[str]
    granted_at: float
    expires_at: float
    consumed: bool = False

    def matches(self, request: ActionRequest) -> tuple[bool, str]:
        if self.consumed:
            return False, "already_used"
        if time.time() > self.expires_at:
            return False, "expired"
        if request.action_id != self.action_id:
            return False, "action_mismatch"
        if request.action_type != self.action_type:
            return False, "action_type_mismatch"
        if (int(request.x), int(request.y)) != (self.x, self.y):
            return False, "target_moved"
        if request.window_title != self.window_title:
            return False, "window_changed"
        return True, ""

    def consume(self) -> None:
        self.consumed = True


def parse_action(payload: Any, allowed: set[str]) -> ActionRequest:
    """Validate an agent payload into an ActionRequest, or raise."""
    if not isinstance(payload, dict):
        raise AgentActionError("malformed_payload", "expected a JSON object")

    action_type = payload.get("action_type")
    if not isinstance(action_type, str) or action_type not in allowed:
        raise AgentActionError(
            "unsupported_action",
            f"action_type must be one of {sorted(allowed)}",
        )

    x, y = payload.get("x"), payload.get("y")
    if not isinstance(x, int) or not isinstance(y, int):
        raise AgentActionError("malformed_payload", "x and y must be integers")
    if isinstance(x, bool) or isinstance(y, bool):
        raise AgentActionError("malformed_payload", "x and y must be integers")

    for key in ("command", "shell", "script", "args", "argv"):
        if key in payload:
            raise AgentActionError(
                "forbidden_field",
                f"{key!r} is not accepted; Arrow never executes commands",
            )

    window_title = payload.get("window_title")
    if window_title is not None and not isinstance(window_title, str):
        raise AgentActionError("malformed_payload", "window_title must be a string")

    return ActionRequest(
        action_id=str(payload.get("action_id") or uuid.uuid4()),
        action_type=action_type,
        x=int(x),
        y=int(y),
        reason=str(payload.get("reason") or "")[:500],
        expected_outcome=str(payload.get("expected_outcome") or "")[:500],
        window_title=window_title,
        task_id=payload.get("task_id"),
        capture_id=payload.get("capture_id"),
    )


def sanitise_highlight(raw: Any) -> Optional[tuple[int, int, int, int]]:
    """Validate an agent-supplied highlight rectangle."""
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise AgentActionError("malformed_payload", "highlight must be [x,y,w,h]")
    values = []
    for v in raw:
        if not isinstance(v, int) or isinstance(v, bool):
            raise AgentActionError("malformed_payload", "highlight values must be ints")
        if abs(v) > MAX_HIGHLIGHT:
            raise AgentActionError("out_of_range", f"highlight value {v} out of range")
        values.append(int(v))
    x, y, w, h = values
    if w <= 0 or h <= 0:
        raise AgentActionError("malformed_payload", "highlight width/height must be positive")
    return (x, y, w, h)


class AgentActions:
    """Approval store plus execution, with revalidation before acting.

    ``executor`` is injected and receives only ``(request,)``. The default is
    ``None``, which means *no action can ever execute* — a safe default that
    keeps this class inert until a caller deliberately wires it up.
    """

    def __init__(
        self,
        executor: Optional[Callable[[ActionRequest], dict]] = None,
        current_window: Optional[Callable[[], Optional[str]]] = None,
        observe: Optional[Callable[[int, int], Optional[dict]]] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_pending: int = 32,
    ) -> None:
        self._executor = executor
        self._current_window = current_window or (lambda: None)
        # observe(x, y) -> {"x", "y", ...} for the element currently under the
        # approved point, or None if it cannot be identified right now. It is
        # what makes 'the target moved' a real check rather than a tautology:
        # rebuilding the request from the approval would always match.
        self._observe = observe
        self._approvals: dict[str, Approval] = {}
        self._outcomes: dict[str, dict] = {}
        self._ttl = ttl_seconds
        self._max_pending = max_pending

    def status(self, action_id: str) -> Optional[dict]:
        """Current state of an action, or None if it is unknown.

        Live approval state wins over the recorded outcome, so an approval
        that has since expired reports 'expired' rather than a stale
        'awaiting_approval'.
        """
        approval = self._approvals.get(action_id)
        if approval is not None:
            if time.time() > approval.expires_at:
                return {
                    "ok": True,
                    "action_id": action_id,
                    "state": "expired",
                    "executed": False,
                }
            return {
                "ok": True,
                "action_id": action_id,
                "action_type": approval.action_type,
                "state": "awaiting_approval",
                "executed": False,
                "expires_in": max(0.0, approval.expires_at - time.time()),
            }
        return self._outcomes.get(action_id)

    def _record(self, action_id: str, result: dict) -> dict:
        # Bounded: an agent must not be able to grow this without limit.
        if len(self._outcomes) >= self._max_pending * 4:
            self._outcomes.clear()
        self._outcomes[action_id] = result
        return result

    # -- lifecycle --------------------------------------------------------

    @property
    def has_executor(self) -> bool:
        return self._executor is not None

    def _prune(self) -> None:
        now = time.time()
        for key in [k for k, a in self._approvals.items()
                    if a.consumed or now > a.expires_at]:
            self._approvals.pop(key, None)

    def stop(self) -> int:
        """Cancel everything outstanding. Always safe to call."""
        count = len(self._approvals)
        self._approvals.clear()
        return count

    def request(self, request: ActionRequest) -> dict:
        """Record a pending action awaiting the user's decision."""
        self._prune()
        if len(self._approvals) >= self._max_pending:
            raise AgentActionError("too_many_pending", "too many pending approvals")
        approval = Approval(
            action_id=request.action_id,
            action_type=request.action_type,
            x=request.x,
            y=request.y,
            window_title=request.window_title,
            granted_at=time.time(),
            expires_at=time.time() + self._ttl,
        )
        self._approvals[request.action_id] = approval
        # Deliberately not recorded as an outcome: 'awaiting' is a live state,
        # not a terminal result, and caching it would hide later expiry.
        return {
            "ok": True,
            "state": "awaiting_approval",
            "action_id": request.action_id,
            "action_type": request.action_type,
            "executed": False,
            "expires_in": self._ttl,
        }

    def decide(self, action_id: str, allow: bool) -> dict:
        """The user pressed Allow or Deny.

        Returns what actually happened. Deny is final and executes nothing.
        """
        # Look the action up *before* pruning so an expired one still reports
        # 'expired' rather than being indistinguishable from 'never existed'.
        approval = self._approvals.get(action_id)
        if approval is None:
            self._prune()
            raise AgentActionError("unknown_action", f"no pending action {action_id}")
        self._prune()
        if approval.action_id not in self._approvals:
            # Pruned as expired between the lookup and now.
            raise self._refuse(
                action_id, "expired", "the approval expired before it was used"
            )

        if not allow:
            self._approvals.pop(action_id, None)
            return self._record(action_id, {
                "ok": True, "state": "denied", "action_id": action_id,
                "executed": False, "reason": "user_denied",
            })

        if time.time() > approval.expires_at:
            self._approvals.pop(action_id, None)
            raise self._refuse(
                action_id, "expired",
                "the approval expired before it was used",
            )

        # Revalidate the window at the moment of execution.
        if approval.window_title is not None:
            current = self._current_window()
            if current != approval.window_title:
                self._approvals.pop(action_id, None)
                raise self._refuse(
                    action_id, "window_changed",
                    f"focused window is {current!r}, expected "
                    f"{approval.window_title!r}",
                )

        # Revalidate the target against the live screen. Failing to observe it
        # is a refusal, not a licence to click the recorded coordinates.
        if self._observe is not None:
            try:
                observed = self._observe(approval.x, approval.y)
            except Exception as e:  # noqa: BLE001 - observation must not crash
                raise self._refuse(
                    action_id, "target_unverified",
                    f"could not re-check the target: {e}",
                ) from None
            if observed is None:
                self._approvals.pop(action_id, None)
                raise self._refuse(
                    action_id, "target_unverified",
                    "the approved element is no longer identifiable at that point",
                )
            if abs(int(observed.get("x", approval.x)) - approval.x) > TARGET_DRIFT_TOLERANCE \
               or abs(int(observed.get("y", approval.y)) - approval.y) > TARGET_DRIFT_TOLERANCE:
                self._approvals.pop(action_id, None)
                raise self._refuse(
                    action_id, "target_moved",
                    "the element moved since you approved it",
                )

        request = ActionRequest(
            action_id=approval.action_id,
            action_type=approval.action_type,
            x=approval.x,
            y=approval.y,
            window_title=approval.window_title,
        )
        ok, reason = approval.matches(request)
        if not ok:
            self._approvals.pop(action_id, None)
            raise self._refuse(action_id, reason,
                               "approval no longer matches the target")

        # Single use: burn it before executing so a retry cannot re-fire.
        approval.consume()
        self._approvals.pop(action_id, None)

        if self._executor is None:
            raise self._refuse(
                action_id, "no_executor",
                "no action executor is configured; nothing was performed",
            )

        try:
            outcome = self._executor(request)
        except Exception as e:
            # The executor refused (e.g. target could not be re-identified).
            # Report truthfully: submitted is not the same as performed.
            reason = getattr(e, "reason", "executor_refused")
            raise self._refuse(action_id, reason, str(e)) from None

        return self._record(action_id, {
            "ok": True,
            "state": "executed",
            "action_id": action_id,
            "executed": True,
            "outcome": outcome,
        })

    def _refuse(self, action_id: str, reason: str, detail: str) -> AgentActionError:
        self._record(action_id, {
            "ok": False,
            "action_id": action_id,
            "state": "refused",
            "executed": False,
            "reason": reason,
            "detail": detail,
        })
        return AgentActionError(reason, detail)


__all__ = [
    "ActionRequest",
    "AgentActionError",
    "AgentActions",
    "Approval",
    "DEFAULT_TTL_SECONDS",
    "parse_action",
    "sanitise_highlight",
]