"""Agent action approvals: Allow/Deny, expiry, revalidation, fail-closed.

Every test here is about a way an agent could get something done that the user
did not authorise. The invariants are:

* nothing executes without a live, matching, unexpired approval;
* an approval authorises exactly one action on exactly one target;
* Deny, Stop, expiry, a changed window and a moved target all execute
  nothing;
* a preview is never permission to click;
* a payload cannot smuggle in a command.
"""

from __future__ import annotations

import time

import pytest

from arrow.server.agent_actions import (
    ActionRequest,
    AgentActionError,
    AgentActions,
    parse_action,
    sanitise_highlight,
)

CLICK = {"click_target", "scroll_target"}
ALL_ACTIONS = CLICK | {"preview_target", "highlight_target", "capture_screenshot"}


@pytest.fixture
def performed():
    return []


@pytest.fixture
def actions(performed):
    return AgentActions(
        executor=lambda req: performed.append(req.action_type) or {"ok": True},
        current_window=lambda: "Example App",
        ttl_seconds=60.0,
    )


@pytest.fixture
def watching(performed):
    """Actions that also observe the live target, like the real app does."""
    state = {"obs": {"x": 100, "y": 200}, "window": "Example App"}
    a = AgentActions(
        executor=lambda req: performed.append(req.action_type) or {"ok": True},
        current_window=lambda: state["window"],
        observe=lambda x, y: state["obs"],
    )
    a.state = state  # type: ignore[attr-defined]
    return a


def _request(**kw):
    base = dict(action_id="a1", action_type="click_target", x=100, y=200,
                window_title="Example App")
    base.update(kw)
    return ActionRequest(**base)


# -- the happy path, and only via approval ---------------------------------


def test_nothing_executes_before_approval(actions, performed):
    actions.request(_request())
    assert performed == []
    assert actions.status("a1")["state"] == "awaiting_approval"
    assert actions.status("a1")["executed"] is False


def test_allow_once_executes_exactly_once(actions, performed):
    actions.request(_request())
    result = actions.decide("a1", allow=True)
    assert result["state"] == "executed"
    assert result["executed"] is True
    assert performed == ["click_target"]


def test_approval_is_single_use(actions, performed):
    actions.request(_request())
    actions.decide("a1", allow=True)
    with pytest.raises(AgentActionError):
        actions.decide("a1", allow=True)
    assert performed == ["click_target"], "a replay must not fire a second click"


def test_deny_executes_nothing(actions, performed):
    actions.request(_request())
    result = actions.decide("a1", allow=False)
    assert result["state"] == "denied"
    assert result["executed"] is False
    assert performed == []


def test_deny_then_allow_still_does_nothing(actions, performed):
    actions.request(_request())
    actions.decide("a1", allow=False)
    with pytest.raises(AgentActionError):
        actions.decide("a1", allow=True)
    assert performed == []


# -- expiry ------------------------------------------------------------------


def test_expired_approval_refuses(performed):
    a = AgentActions(
        executor=lambda r: performed.append(r.action_type),
        ttl_seconds=0.01,
    )
    a.request(_request())
    time.sleep(0.05)
    with pytest.raises(AgentActionError) as exc:
        a.decide("a1", allow=True)
    assert exc.value.reason == "expired"
    assert performed == []


def test_status_reports_expiry_without_deciding(performed):
    a = AgentActions(executor=lambda r: None, ttl_seconds=0.01)
    a.request(_request())
    time.sleep(0.05)
    state = a.status("a1")
    assert state["state"] == "expired"
    assert state["executed"] is False


# -- revalidation ------------------------------------------------------------


def test_changed_window_aborts(performed):
    focus = {"title": "Example App"}
    a = AgentActions(
        executor=lambda r: performed.append(r.action_type),
        current_window=lambda: focus["title"],
    )
    a.request(_request())
    focus["title"] = "Someone Else"  # focus moved while the user decided
    with pytest.raises(AgentActionError) as exc:
        a.decide("a1", allow=True)
    assert exc.value.reason == "window_changed"
    assert performed == []


def test_moved_target_aborts(watching, performed):
    watching.request(_request())
    # The element is now somewhere else on screen.
    watching.state["obs"] = {"x": 900, "y": 800}
    with pytest.raises(AgentActionError) as exc:
        watching.decide("a1", allow=True)
    assert exc.value.reason == "target_moved"
    assert performed == []


def test_vanished_target_aborts(watching, performed):
    """Cannot re-identify the element -> fail closed, do not click blind."""
    watching.request(_request())
    watching.state["obs"] = None
    with pytest.raises(AgentActionError) as exc:
        watching.decide("a1", allow=True)
    assert exc.value.reason == "target_unverified"
    assert performed == []


def test_observation_raising_aborts(watching, performed):
    def boom(x, y):
        raise RuntimeError("uiautomation crashed")

    watching._observe = boom
    watching.request(_request())
    with pytest.raises(AgentActionError) as exc:
        watching.decide("a1", allow=True)
    assert exc.value.reason == "target_unverified"
    assert performed == []


def test_small_drift_within_tolerance_is_allowed(watching, performed):
    watching.request(_request())
    watching.state["obs"] = {"x": 104, "y": 203}
    result = watching.decide("a1", allow=True)
    assert result["executed"] is True
    assert performed == ["click_target"]


def test_unknown_action_is_refused(actions, performed):
    with pytest.raises(AgentActionError) as exc:
        actions.decide("never-existed", allow=True)
    assert exc.value.reason == "unknown_action"
    assert performed == []


# -- stop --------------------------------------------------------------------


def test_stop_cancels_everything(actions, performed):
    actions.request(_request(action_id="a1"))
    actions.request(_request(action_id="a2"))
    assert actions.stop() == 2
    with pytest.raises(AgentActionError):
        actions.decide("a1", allow=True)
    with pytest.raises(AgentActionError):
        actions.decide("a2", allow=True)
    assert performed == []


def test_stop_mid_flight_leaves_nothing_pending(actions):
    actions.request(_request(action_id="a1"))
    actions.stop()
    assert actions.status("a1") is None


# -- preview is never permission to click -----------------------------------


def test_preview_does_not_become_an_execution(performed):
    """A preview may be allowed, but must not route through a click."""
    a = AgentActions(
        executor=lambda r: performed.append(r.action_type),
        current_window=lambda: "Example App",
    )
    a.request(_request(action_type="preview_target"))
    result = a.decide("a1", allow=True)
    assert result["executed"] is True
    assert performed == ["preview_target"]
    assert "click_target" not in performed


def test_default_has_no_executor_so_nothing_can_run():
    a = AgentActions(current_window=lambda: "Example App")
    assert a.has_executor is False
    a.request(_request())
    with pytest.raises(AgentActionError) as exc:
        a.decide("a1", allow=True)
    assert exc.value.reason == "no_executor"


def test_executor_refusal_is_reported_truthfully():
    def refusing(req):
        raise AgentActionError("target_unverified", "element moved")

    a = AgentActions(executor=refusing, current_window=lambda: "Example App")
    a.request(_request())
    with pytest.raises(AgentActionError) as exc:
        a.decide("a1", allow=True)
    assert exc.value.reason == "target_unverified"
    status = a.status("a1")
    assert status["state"] == "refused"
    assert status["executed"] is False, "submitted must not be reported as performed"


# -- payload validation ------------------------------------------------------


def test_command_field_is_rejected():
    with pytest.raises(AgentActionError) as exc:
        parse_action(
            {"action_type": "click_target", "x": 1, "y": 2, "command": "rm -rf /"},
            ALL_ACTIONS,
        )
    assert exc.value.reason == "forbidden_field"


@pytest.mark.parametrize("field", ["shell", "script", "args", "argv"])
def test_every_shell_field_is_rejected(field):
    with pytest.raises(AgentActionError) as exc:
        parse_action(
            {"action_type": "click_target", "x": 1, "y": 2, field: "anything"},
            ALL_ACTIONS,
        )
    assert exc.value.reason == "forbidden_field"


def test_unknown_action_type_is_rejected():
    with pytest.raises(AgentActionError) as exc:
        parse_action({"action_type": "run_shell", "x": 1, "y": 2}, ALL_ACTIONS)
    assert exc.value.reason == "unsupported_action"


def test_non_integer_coordinates_are_rejected():
    for bad in ({"x": "10", "y": 2}, {"x": 1.5, "y": 2}, {"x": True, "y": 2}, {}):
        payload = {"action_type": "click_target", **bad}
        with pytest.raises(AgentActionError) as exc:
            parse_action(payload, ALL_ACTIONS)
        assert exc.value.reason == "malformed_payload"


def test_non_dict_payload_is_rejected():
    with pytest.raises(AgentActionError) as exc:
        parse_action(["click", 1, 2], ALL_ACTIONS)
    assert exc.value.reason == "malformed_payload"


def test_reason_and_outcome_are_length_bounded():
    req = parse_action(
        {
            "action_type": "click_target", "x": 1, "y": 2,
            "reason": "r" * 5000, "expected_outcome": "e" * 5000,
        },
        ALL_ACTIONS,
    )
    assert len(req.reason) <= 500
    assert len(req.expected_outcome) <= 500


# -- highlight validation ----------------------------------------------------


def test_highlight_accepts_a_sane_rect():
    assert sanitise_highlight([10, 20, 100, 40]) == (10, 20, 100, 40)


def test_negative_highlight_coordinates_are_allowed():
    # Left/above monitors produce negative bounds.
    assert sanitise_highlight([-1920, -1080, 300, 200]) == (-1920, -1080, 300, 200)


@pytest.mark.parametrize("bad", [
    [1, 2, 3], [1, 2, 3, 4, 5], [1, 2, 0, 10], [1, 2, -5, 10],
    [1, 2, "a", 4], [1, 2, 3, 4.5], [1, 2, True, 4],
])
def test_malformed_highlight_is_rejected(bad):
    with pytest.raises(AgentActionError):
        sanitise_highlight(bad)


def test_absurd_highlight_is_rejected():
    with pytest.raises(AgentActionError) as exc:
        sanitise_highlight([0, 0, 999999, 10])
    assert exc.value.reason == "out_of_range"


def test_empty_highlight_is_simply_absent():
    assert sanitise_highlight(None) is None
    assert sanitise_highlight([]) is None


# -- boundedness -------------------------------------------------------------


def test_pending_approvals_are_bounded():
    a = AgentActions(current_window=lambda: "Example App", max_pending=8)
    for i in range(8):
        a.request(_request(action_id=f"a{i}"))
    with pytest.raises(AgentActionError) as exc:
        a.request(_request(action_id="overflow"))
    assert exc.value.reason == "too_many_pending"


def test_outcome_history_is_bounded(actions):
    for i in range(200):
        actions.request(_request(action_id=f"a{i}"))
        actions.decide(f"a{i}", allow=False)
    assert len(actions._outcomes) <= actions._max_pending * 4


# -- threading ---------------------------------------------------------------


def test_concurrent_decisions_fire_at_most_once(performed):
    import threading

    a = AgentActions(executor=lambda r: performed.append(r.action_type))
    a.request(_request())

    results = []
    lock = threading.Lock()

    def worker():
        try:
            r = a.decide("a1", allow=True)
            with lock:
                results.append(r.get("state"))
        except AgentActionError as e:
            with lock:
                results.append(e.reason)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert performed.count("click_target") <= 1, "a race must not double-click"
    assert len(results) == 8