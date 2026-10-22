"""Agent pointer motion: spring behaviour, stability and cleanup.

Pure physics, no Qt and no screen access, so these assertions are about the
motion model itself rather than about what happened to be painted.
"""

from __future__ import annotations

import math

import pytest

from arrow.ui.agent_pointer import (
    MAX_TIMESTEP,
    AgentPointerMotion,
    max_overshoot,
    simulate,
)

START = (0.0, 0.0)
TARGET = (400.0, 0.0)


def _run_to_settle(motion, target, dt=1 / 60.0, seconds=6.0):
    for _ in range(int(seconds / dt)):
        motion.step(*target, dt)
    return motion


# -- convergence ------------------------------------------------------------


def test_pointer_converges_on_its_target():
    motion = _run_to_settle(AgentPointerMotion(x=0, y=0), TARGET)
    assert motion.x == pytest.approx(TARGET[0], abs=1.0)
    assert motion.y == pytest.approx(TARGET[1], abs=1.0)


def test_pointer_reports_settled_at_rest():
    motion = _run_to_settle(AgentPointerMotion(x=0, y=0), TARGET)
    assert motion.is_settled is True


def test_pointer_is_not_settled_while_moving():
    motion = AgentPointerMotion(x=0, y=0)
    motion.step(400, 0, 1 / 60.0)
    assert motion.is_settled is False


def test_settle_places_it_exactly_on_target():
    motion = AgentPointerMotion(x=0, y=0)
    motion.settle(123.5, -77.25)
    assert motion.x == pytest.approx(123.5)
    assert motion.y == pytest.approx(-77.25)
    assert motion.velocity_x == 0.0
    assert motion.angular_velocity == 0.0


def test_snap_to_does_not_animate():
    motion = AgentPointerMotion(x=0, y=0)
    motion.snap_to(-1900, -900)
    assert (motion.x, motion.y) == (-1900.0, -900.0)
    assert motion.velocity_x == 0.0


# -- stability --------------------------------------------------------------


def test_motion_is_frame_rate_independent_enough():
    """60 Hz and 120 Hz must land in the same place."""
    a = _run_to_settle(AgentPointerMotion(x=0, y=0), TARGET, dt=1 / 60.0)
    b = _run_to_settle(AgentPointerMotion(x=0, y=0), TARGET, dt=1 / 120.0)
    assert a.x == pytest.approx(b.x, abs=1.0)
    assert a.y == pytest.approx(b.y, abs=1.0)


def test_a_huge_frame_gap_does_not_explode():
    """A 5 second stall must clamp, not explode."""
    motion = AgentPointerMotion(x=0, y=0)
    motion.step(400, 0, 5.0)
    assert math.isfinite(motion.x)
    assert math.isfinite(motion.velocity_x)
    assert abs(motion.x) < 100_000


def test_timestep_is_clamped_to_the_documented_bound():
    motion = AgentPointerMotion(x=0, y=0)
    before = motion.x
    motion.step(400, 0, 100.0)
    # A single clamped step is bounded: the spring may accelerate hard but it
    # must not teleport past the target or blow up.
    assert abs(motion.x - before) < 400.0
    assert math.isfinite(motion.x)
    # ...and the next steps still converge.
    _run_to_settle(motion, TARGET)
    assert motion.x == pytest.approx(TARGET[0], abs=1.0)


def test_zero_and_negative_timesteps_are_safe():
    motion = AgentPointerMotion(x=10, y=10)
    motion.step(400, 0, 0.0)
    motion.step(400, 0, -1.0)
    assert math.isfinite(motion.x)


def test_no_nan_from_degenerate_targets():
    motion = AgentPointerMotion(x=5, y=5)
    for _ in range(50):
        motion.step(5, 5, 1 / 60.0)  # identical start and target
    assert not math.isnan(motion.x)
    assert not math.isnan(motion.rotation)


def test_overshoot_is_small_and_settles():
    over = max_overshoot(START, TARGET)
    assert over < 25.0, f"pointer overshot by {over}px"
    motion = _run_to_settle(AgentPointerMotion(x=0, y=0), TARGET)
    assert motion.x == pytest.approx(TARGET[0], abs=1.0)


def test_moving_target_does_not_diverge():
    """Chasing a target that keeps moving must stay bounded."""
    motion = AgentPointerMotion(x=0, y=0)
    for i in range(240):
        motion.step(float(i), float(i % 7), 1 / 60.0)
        assert math.isfinite(motion.x)
        assert abs(motion.x) < 10_000


# -- negative coordinates ---------------------------------------------------


def test_pointer_handles_negative_monitor_coordinates():
    motion = AgentPointerMotion(x=-1900.0, y=-1000.0)
    motion.settle(-1500.0, -900.0)
    assert motion.x == pytest.approx(-1500.0)
    assert motion.y == pytest.approx(-900.0)
    assert motion.x < 0 and motion.y < 0


def test_path_stays_on_the_correct_side_of_a_negative_origin():
    path = simulate((-1900, -1000), (-1000, -1000))
    assert all(x <= -1000.0 + 1.0 for x, _ in path)
    assert all(y == pytest.approx(-1000.0, abs=1.0) for _, y in path)


# -- rotation ---------------------------------------------------------------


def test_rotation_follows_direction_of_travel():
    motion = AgentPointerMotion(x=0, y=0)
    _run_to_settle(motion, (0, 300))  # straight down
    # atan2(+300, 0) == +pi/2, i.e. pointing down the screen.
    assert motion.rotation == pytest.approx(math.pi / 2, abs=0.1)

    right = AgentPointerMotion(x=0, y=0)
    _run_to_settle(right, (300, 0))
    assert right.rotation == pytest.approx(0.0, abs=0.1)


def test_rotation_takes_the_short_way_round():
    """A 10 degree step must not unwind 350 degrees backwards."""
    motion = AgentPointerMotion(x=0, y=0)
    motion.rotation = math.radians(170)
    motion.step(0, 0, 1 / 60.0, rotation_target=math.radians(-170))
    assert abs(motion.rotation) < math.pi


def test_rotation_settles_without_wobble():
    motion = AgentPointerMotion(x=0, y=0)
    for _ in range(300):
        motion.step(400, 0, 1 / 60.0, rotation_target=0.0)
    assert abs(motion.angular_velocity) < 0.5
    assert motion.rotation == pytest.approx(0.0, abs=0.05)


def test_rotation_target_can_be_pinned():
    motion = AgentPointerMotion(x=0, y=0)
    for _ in range(300):
        motion.step(0, 0, 1 / 60.0, rotation_target=math.radians(90))
    assert motion.rotation == pytest.approx(math.radians(90), abs=0.05)


# -- repeated / cancelled targets ------------------------------------------


def test_repeated_identical_targets_produce_no_drift():
    motion = AgentPointerMotion(x=0, y=0)
    motion.settle(200, 200)
    for _ in range(120):
        motion.step(200, 200, 1 / 60.0)
    assert motion.x == pytest.approx(200.0, abs=0.1)
    assert motion.y == pytest.approx(200.0, abs=0.1)


def test_target_switching_mid_flight_is_smooth():
    motion = AgentPointerMotion(x=0, y=0)
    for _ in range(30):
        motion.step(1000, 0, 1 / 60.0)
    for _ in range(120):
        motion.step(0, 1000, 1 / 60.0)
    assert math.isfinite(motion.x) and math.isfinite(motion.y)


def test_simulate_stops_early_once_settled():
    path = simulate(START, TARGET)
    # Far shorter than the 5 second budget it was allowed.
    assert len(path) < 300
    assert path[-1][0] == pytest.approx(TARGET[0], abs=1.0)


def test_max_timestep_is_a_sane_bound():
    assert 0 < MAX_TIMESTEP <= 1 / 30.0