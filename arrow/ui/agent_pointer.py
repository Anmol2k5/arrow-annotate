"""Agent pointer motion model.

The visual AI pointer is a *separate actor* from the human annotation trail.
It must never share mutable gesture-capture state, and it must never move the
physical system mouse — it is a picture drawn on an overlay.

The motion is a critically-ish damped spring integrated with a **bounded**
timestep. The bound is the important part: Qt can deliver an arbitrarily long
frame gap after a stall or a breakpoint, and an unbounded integration step
turns a spring into an explosion.

This module holds no Qt state so the physics can be tested directly.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

# Reference values from the SupaMaus cursor simulation, tuned for PyQt6.
POSITION_STIFFNESS = 400.0
POSITION_DAMPING = 45.0
ROTATION_STIFFNESS = 300.0
ROTATION_DAMPING = 60.0

# Never integrate more than this in one step, whatever the frame gap was.
MAX_TIMESTEP = 1.0 / 30.0
# Smaller steps are pointless; they only burn CPU without changing anything.
MIN_TIMESTEP = 1.0 / 1000.0


@dataclass
class AgentPointerMotion:
    """Spring-driven position and heading for the agent pointer.

    Coordinates are virtual-desktop pixels and may be negative on a monitor
    left of or above the primary display.
    """

    x: float = 0.0
    y: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    rotation: float = 0.0
    angular_velocity: float = 0.0

    # Settled when both translation and rotation are effectively still.
    REST_POSITION_EPSILON = 0.05
    REST_VELOCITY_EPSILON = 0.5

    @property
    def is_settled(self) -> bool:
        """At rest: no visible jitter, no endless repaints."""
        return (
            abs(self.velocity_x) < self.REST_VELOCITY_EPSILON
            and abs(self.velocity_y) < self.REST_VELOCITY_EPSILON
            and abs(self.angular_velocity) < self.REST_VELOCITY_EPSILON
        )

    def step(
        self,
        target_x: float,
        target_y: float,
        dt: float,
        rotation_target: float | None = None,
    ) -> None:
        """Advance toward the target by ``dt`` seconds.

        The timestep is clamped, so a long frame gap degrades to a slightly
        slower approach instead of an unstable one.
        """
        dt = max(MIN_TIMESTEP, min(float(dt), MAX_TIMESTEP))

        # Semi-implicit Euler: stable for damped springs at these gains and
        # cheap enough to run every frame.
        ax = POSITION_STIFFNESS * (target_x - self.x) - POSITION_DAMPING * self.velocity_x
        ay = POSITION_STIFFNESS * (target_y - self.y) - POSITION_DAMPING * self.velocity_y
        self.velocity_x += ax * dt
        self.velocity_y += ay * dt
        self.x += self.velocity_x * dt
        self.y += self.velocity_y * dt

        if rotation_target is None:
            # Face the direction of travel; keeps the cursor oriented while
            # moving and settles flat once it stops.
            rotation_target = self._heading_towards(target_x, target_y)

        # Take the short way round rather than unwinding a full turn.
        delta = (rotation_target - self.rotation + math.pi) % (2 * math.pi) - math.pi
        angular_accel = (
            ROTATION_STIFFNESS * delta - ROTATION_DAMPING * self.angular_velocity
        )
        self.angular_velocity += angular_accel * dt
        self.rotation += self.angular_velocity * dt

    def _heading_towards(self, target_x: float, target_y: float) -> float:
        dx, dy = target_x - self.x, target_y - self.y
        if math.hypot(dx, dy) < 1e-3:
            return self.rotation
        return math.atan2(dy, dx)

    def snap_to(self, x: float, y: float) -> None:
        """Place the pointer without animating (first target, or a teleport)."""
        self.x = float(x)
        self.y = float(y)
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.angular_velocity = 0.0

    def settle(self, x: float, y: float, iterations: int = 400) -> None:
        """Run the spring out so a parked pointer is exactly on its target."""
        for _ in range(iterations):
            self.step(x, y, MAX_TIMESTEP)
        self.velocity_x = self.velocity_y = 0.0
        self.angular_velocity = 0.0


def simulate(
    start: tuple[float, float],
    target: tuple[float, float],
    dt: float = 1.0 / 60.0,
    max_seconds: float = 5.0,
) -> list[tuple[float, float]]:
    """Run a motion to completion, returning the sampled path.

    Exposed so tests can assert on the whole trajectory rather than trusting
    whatever the widget happened to paint.
    """
    motion = AgentPointerMotion(x=start[0], y=start[1])
    path = [(motion.x, motion.y)]
    steps = int(max_seconds / dt)
    for _ in range(steps):
        motion.step(target[0], target[1], dt)
        path.append((motion.x, motion.y))
        if motion.is_settled and abs(motion.x - target[0]) < 0.5 and abs(
            motion.y - target[1]
        ) < 0.5:
            break
    return path


def max_overshoot(
    start: tuple[float, float],
    target: tuple[float, float],
    dt: float = 1.0 / 60.0,
    max_seconds: float = 5.0,
) -> float:
    """How far past the target the pointer travels along the travel axis."""
    path = simulate(start, target, dt, max_seconds)
    axis = 0 if abs(target[0] - start[0]) >= abs(target[1] - start[1]) else 1
    destination = target[axis]
    direction = 1.0 if destination >= start[axis] else -1.0
    overshoot = 0.0
    for point in path:
        overshoot = max(overshoot, (point[axis] - destination) * direction)
    return overshoot


__all__ = [
    "AgentPointerMotion",
    "AgentPointerWindow",
    "MAX_TIMESTEP",
    "POSITION_DAMPING",
    "POSITION_STIFFNESS",
    "ROTATION_DAMPING",
    "ROTATION_STIFFNESS",
    "max_overshoot",
    "simulate",
]


class AgentPointerWindow(QWidget):  # pragma: no cover - requires a desktop
    """A click-through overlay that paints the agent cursor.

    Deliberately isolated from :class:`~arrow.ui.overlay.SelectionOverlay`:
    the human trail owns gesture-capture state and this owns none of it, so
    neither can corrupt the other.

    It is ``WA_TransparentForMouseEvents`` at all times — only an explicit
    approval panel may take input. It never moves the physical cursor; it
    draws a picture of one.
    """

    FRAME_MS = 16  # ~60 Hz while moving; the timer stops at rest.

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        # Click-through: an agent pointer must never swallow a real click.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._motion = AgentPointerMotion()
        self._target: tuple[float, float] | None = None
        self._highlight: tuple[int, int, int, int] | None = None
        self._running = False
        self._last_tick = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._on_tick)

    @property
    def is_animating(self) -> bool:
        return self._running

    @property
    def motion(self) -> AgentPointerMotion:
        return self._motion

    def _update_geometry(self) -> None:
        screens = QApplication.screens()
        if screens:
            geom = screens[0].geometry()
            for s in screens[1:]:
                geom = geom.united(s.geometry())
            self.setGeometry(geom)

    def point_at(self, x: float, y: float, highlight: tuple | None = None) -> None:
        """Animate toward a target. Does not click anything."""
        self._update_geometry()
        self._target = (float(x), float(y))
        self._highlight = highlight
        if not self._running:
            self._motion.snap_to(x, y)
        self.show()
        self.raise_()
        self._start()

    def _start(self) -> None:
        self._running = True
        self._last_tick = time.monotonic()
        self._timer.start()

    def hide_pointer(self) -> None:
        """Stop everything. Safe to call when already hidden."""
        self._timer.stop()
        self._running = False
        self._target = None
        self._highlight = None
        self.hide()

    def _on_tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        if self._target is None:
            self.hide_pointer()
            return

        self._motion.step(self._target[0], self._target[1], dt)
        if (
            self._motion.is_settled
            and abs(self._motion.x - self._target[0]) < 1.0
            and abs(self._motion.y - self._target[1]) < 1.0
        ):
            # Settled: stop repainting so idle CPU stays flat.
            self._timer.stop()
            self._running = False
            self.update()
            return
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - needs a desktop
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self._motion.x, self._motion.y)
        painter.rotate(math.degrees(self._motion.rotation))

        if self._highlight:
            x, y, w, h = self._highlight
            painter.setBrush(QColor(79, 142, 247, 22))
            painter.setPen(QPen(QColor(79, 142, 247, 150), 2.0))
            painter.drawRect(QRectF(float(x - self._motion.x), float(y - self._motion.y),
                              float(w), float(h)))
            painter.resetTransform()
            painter.translate(self._motion.x, self._motion.y)

        # Restrained blue glow, then a saturated core arrow.
        tip = QPointF(0, 0)
        left = QPointF(-16, 11)
        right = QPointF(-6, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(79, 142, 247, 90))
        painter.drawPolygon(QPolygonF([tip, left, right]))
        painter.setBrush(QColor(226, 243, 255, 245))
        painter.setPen(QPen(QColor(79, 142, 247, 220), 1.2))
        painter.drawPolygon(QPolygonF([tip, left, right]))
        painter.end()