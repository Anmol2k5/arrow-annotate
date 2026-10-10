import math
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

# Role colors (mirror screenshot_service so the overlay matches the annotation)
SOURCE_RGB = (239, 68, 68)       # Red
DEST_RGB = (34, 197, 94)         # Green
ACTIVE_RGB = (65, 153, 255)       # Electric blue, matching the pointer trail
SOURCE_CORE = (255, 214, 214)
DEST_CORE = (214, 255, 228)
ACTIVE_CORE = (231, 246, 255)    # Ice-blue / white leading edge

MARKER_LABELS = {"source": "Current", "destination": "Move here"}


class StrokePoint:
    __slots__ = ("point", "timestamp")

    def __init__(self, point: QPointF):
        self.point = point
        self.timestamp = time.time()


class Stroke:
    """One freehand stroke; locked strokes form the persistent annotation scene."""

    __slots__ = ("role", "points", "locked", "committed_at")

    def __init__(self, role: str):
        self.role = role  # "source" | "destination"
        self.points: List[StrokePoint] = []
        self.locked = False
        self.committed_at: Optional[float] = None


def stroke_rect(points: List[QPointF], offset: QPointF, pad: int = 100) -> Optional[dict]:
    """Bounding box of a stroke, mapped to global screen coords, with padding.

    Returns ``None`` for an empty stroke. Coordinates are clamped so the box
    never starts above/left of the virtual desktop origin.
    """
    if not points:
        return None
    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    gx = min_x + offset.x()
    gy = min_y + offset.y()
    return {
        "x": max(0, int(gx - pad)),
        "y": max(0, int(gy - pad)),
        "width": int(max_x - min_x + pad * 2),
        "height": int(max_y - min_y + pad * 2),
    }


def stroke_center(points: List[QPointF]) -> Optional[QPointF]:
    if not points:
        return None
    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    return QPointF((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


class SelectionOverlay(QWidget):
    """
    Freehand neon drawing overlay with move-tool support.

    First stroke becomes the *source* (marker ``1``), the second becomes the
    *destination* (marker ``2``). A connecting arrow is drawn between them.
    Locked strokes persist until the capture is saved or cancelled — the comet
    tail fade only applies to the stroke currently being drawn.
    """

    # TipTour-inspired focus gesture timing (1.6s hold + 7s fade).
    # Glow fades, while source/destination semantics stay visible until capture.
    TRAIL_SECONDS = 3.2  # Live points age out as the pointer moves.
    FOCUS_HOLD_SECONDS = 1.6
    FOCUS_FADE_SECONDS = 7.0
    SUBDIVISION = 7
    FADE_BUCKETS = 28
    MAX_VISIBLE_TRAIL_POINTS = 220

    selection_complete = pyqtSignal(object)  # emits a pseudo-SelectionResult with bounding rect(s)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._strokes: List[Stroke] = []
        self._current_stroke: Optional[Stroke] = None
        self._is_drawing = False
        self._active = False

        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._update_fade)
        self._fade_timer.setInterval(16)  # ~60fps, only while overlay is open

        self._offset = QPointF(0, 0)

    def get_gesture_trail(self) -> list[dict]:
        """Export all locked strokes as serializable gesture data.

        Returns a list of ``{t, x, y, role}`` dicts, one per point,
        in chronological order.  Coordinates are in virtual-desktop space
        (offset already applied).
        """
        trail: list[dict] = []
        for stroke in self._strokes:
            if not stroke.locked:
                continue
            for sp in stroke.points:
                trail.append({
                    "t": sp.timestamp,
                    "x": sp.point.x() + self._offset.x(),
                    "y": sp.point.y() + self._offset.y(),
                    "role": stroke.role,
                })
        return trail

    def _update_geometry(self):
        screens = QApplication.screens()
        if screens:
            geom = screens[0].geometry()
            for s in screens[1:]:
                geom = geom.united(s.geometry())
            self.setGeometry(geom)
            self._offset = QPointF(geom.topLeft())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @pyqtSlot()
    def show_overlay(self):
        """Called when hotkey is pressed."""
        self._update_geometry()
        self._active = True
        self._strokes.clear()
        self._current_stroke = None
        self._is_drawing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._fade_timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    @pyqtSlot()
    def hide_overlay(self):
        """Called when hotkey is released; emits the completed selection."""
        self._active = False
        self._is_drawing = False
        self.unsetCursor()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._fade_timer.stop()
        self.hide()  # Remove the drawing surface before the raw screenshot.

        def _mock(result):
            class MockResult:
                def __init__(self, r): self.r = r
                def to_dict(self): return self.r
            return MockResult(result)

        locked = [s for s in self._strokes if s.locked]
        source = next((s for s in locked if s.role == "source"), None)

        if source is not None:
            source_rect = stroke_rect([p.point for p in source.points], self._offset)
            dest = next((s for s in locked if s.role == "destination"), None)

            result: dict = dict(source_rect or {})
            result["source"] = source_rect
            if dest is not None:
                dest_rect = stroke_rect([p.point for p in dest.points], self._offset)
                if dest_rect:
                    result["destination"] = dest_rect
            self.selection_complete.emit(_mock(result))
        else:
            # No stroke drawn → full screen fallback
            geom = self.geometry()
            rect = {"x": geom.x(), "y": geom.y(), "width": geom.width(), "height": geom.height()}
            self.selection_complete.emit(_mock(rect))

    # ------------------------------------------------------------------
    # Mouse input
    # ------------------------------------------------------------------

    def _next_role(self) -> str:
        has_source = any(s.role == "source" for s in self._strokes)
        return "destination" if has_source else "source"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = True
            role = self._next_role()
            # A new stroke replaces an earlier stroke of the same role
            # (e.g. re-drawing the destination) but never deletes the other.
            self._strokes = [s for s in self._strokes if s.role != role]
            self._current_stroke = Stroke(role)
            self._current_stroke.points = [StrokePoint(event.globalPosition() - self._offset)]
            self.update()

    def mouseMoveEvent(self, event):
        if not self._is_drawing or self._current_stroke is None:
            return
        pt = event.globalPosition() - self._offset

        if self._current_stroke.points:
            last_pt = self._current_stroke.points[-1].point
            dist = math.hypot(pt.x() - last_pt.x(), pt.y() - last_pt.y())
            if dist < 1.5:
                return
            # Gentle low-pass filtering removes mouse jitter without creating
            # a noticeable rubber-band delay. The spline handles curvature.
            pt = QPointF(last_pt.x() * 0.24 + pt.x() * 0.76,
                         last_pt.y() * 0.24 + pt.y() * 0.76)

        self._current_stroke.points.append(StrokePoint(pt))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = False
            if self._current_stroke is not None:
                self._current_stroke.locked = True
                self._current_stroke.committed_at = time.time()
                self._strokes.append(self._current_stroke)
                self._current_stroke = None
            self.update()

    # ------------------------------------------------------------------
    # Fade timer (comet tail applies only to the active stroke)
    # ------------------------------------------------------------------

    def _update_fade(self):
        has_live = self._current_stroke is not None and bool(self._current_stroke.points)
        if self._strokes or has_live or self._is_drawing or self._active:
            self.update()
        elif not self._active and not self._strokes:
            self.hide()

    # ------------------------------------------------------------------
    # Trail smoothing (Catmull-Rom)
    # ------------------------------------------------------------------

    @staticmethod
    def _catmull_rom(p0: QPointF, p1: QPointF, p2: QPointF, p3: QPointF, t: float) -> QPointF:
        """Uniform Catmull-Rom interpolation at parameter t in [0, 1]."""
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * (
            (2 * p1.x())
            + (-p0.x() + p2.x()) * t
            + (2 * p0.x() - 5 * p1.x() + 4 * p2.x() - p3.x()) * t2
            + (-p0.x() + 3 * p1.x() - 3 * p2.x() + p3.x()) * t3
        )
        y = 0.5 * (
            (2 * p1.y())
            + (-p0.y() + p2.y()) * t
            + (2 * p0.y() - 5 * p1.y() + 4 * p2.y() - p3.y()) * t2
            + (-p0.y() + 3 * p1.y() - 3 * p2.y() + p3.y()) * t3
        )
        return QPointF(x, y)

    def _build_trail(
        self, points: List[StrokePoint], now: float, trail_seconds: float
    ) -> List[Tuple[QPointF, float]]:
        """Smooth a stroke with Catmull-Rom and attach a per-point alpha.

        Returns a list of (point, alpha) pairs ordered from tail to head.
        ``trail_seconds`` controls how fast the alpha decays; a huge value
        (locked strokes) keeps everything at full opacity.
        """
        n = len(points)
        trail: List[Tuple[QPointF, float]] = []

        def alpha_of(p: StrokePoint) -> float:
            # Ease the opacity towards zero, rather than dropping abruptly
            # when the stroke locks. All points naturally expire with age.
            elapsed = max(0.0, now - p.timestamp)
            remaining = max(0.0, 1.0 - elapsed / trail_seconds)
            return remaining ** 1.35

        steps = self.SUBDIVISION
        for i in range(n - 1):
            p0 = points[max(0, i - 1)].point
            p1 = points[i].point
            p2 = points[i + 1].point
            p3 = points[min(n - 1, i + 2)].point
            a1 = alpha_of(points[i])
            a2 = alpha_of(points[i + 1])
            for s in range(steps):
                t = s / steps
                trail.append((self._catmull_rom(p0, p1, p2, p3, t),
                              a1 + (a2 - a1) * t))
        if n:
            last = points[-1]
            trail.append((last.point, alpha_of(last)))
        return trail

    @staticmethod
    def _focus_opacity(now: float, committed_at: Optional[float]) -> float:
        """Hold a finished gesture briefly, then linearly fade to zero."""
        if committed_at is None:
            return 0.0
        age = max(0.0, now - committed_at)
        if age <= SelectionOverlay.FOCUS_HOLD_SECONDS:
            return 1.0
        fraction = (age - SelectionOverlay.FOCUS_HOLD_SECONDS) / SelectionOverlay.FOCUS_FADE_SECONDS
        return max(0.0, 1.0 - fraction)

    def _focus_trail(self, points: List[StrokePoint], now: float, committed_at: Optional[float]) -> List[Tuple[QPointF, float]]:
        """A committed trail fades globally; its tail is naturally softer."""
        opacity = self._focus_opacity(now, committed_at)
        if opacity <= 0.0:
            return []
        # The full raw stroke remains available for the screenshot/gesture
        # contract; only the temporary glow is capped to bound frame cost.
        smoothed = self._build_trail(points[-self.MAX_VISIBLE_TRAIL_POINTS:], now, 1e9)
        last = max(1, len(smoothed) - 1)
        return [
            (pt, min(1.0, ((i / last) ** 1.8) * opacity))
            for i, (pt, _alpha) in enumerate(smoothed)
        ]

    def _stroke_trail(self, painter: QPainter, trail: List[Tuple[QPointF, float]],
                      rgb: Tuple[int, int, int], core_rgb: Tuple[int, int, int]):
        """Draw layered highlighter bands with flat caps instead of bead-like dots.

        TipTour draws smooth continuous paths with many trimmed opacity bands.
        In Qt we use smoothed, short subpaths in alpha buckets. Flat caps make
        neighboring segments abut cleanly rather than stacking round endcaps.
        """
        if not trail:
            return

        r, g, b = rgb
        if len(trail) == 1:
            point, alpha = trail[0]
            if alpha > 0.01:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(r, g, b, int(170 * alpha)))
                painter.drawEllipse(point, 6.5, 6.5)
            return

        buckets = [QPainterPath() for _ in range(self.FADE_BUCKETS)]
        occupied = set()
        for (prev_pt, prev_alpha), (pt, alpha) in zip(trail, trail[1:]):
            midpoint = (prev_alpha + alpha) * 0.5
            if midpoint <= 0.008:
                continue
            index = min(self.FADE_BUCKETS - 1, int(midpoint * self.FADE_BUCKETS))
            bucket = buckets[index]
            bucket.moveTo(prev_pt)
            bucket.lineTo(pt)
            occupied.add(index)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in sorted(occupied):
            alpha = (index + 0.5) / self.FADE_BUCKETS
            path = buckets[index]
            # Wide soft halo / middle bloom / saturated highlighter core.
            # QPainter lacks SwiftUI's per-layer gaussian blur; low-opacity
            # outer passes keep the effect lightweight and native on Windows.
            for width, opacity in ((42.0, 27), (26.0, 65), (14.0, 153)):
                painter.setPen(QPen(
                    QColor(r, g, b, int(opacity * alpha)),
                    width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.FlatCap,
                    Qt.PenJoinStyle.RoundJoin,
                ))
                painter.drawPath(path)

    def _draw_focus_outline(self, painter: QPainter, stroke: Stroke, now: float):
        """Quiet rounded focus frame and corner brackets, after TipTour's detector UX."""
        if len(stroke.points) < 2:
            return
        xs = [p.point.x() for p in stroke.points]
        ys = [p.point.y() for p in stroke.points]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        if width < 14.0 or height < 14.0:
            return
        rect = QRectF(min(xs) - 9, min(ys) - 9, width + 18, height + 18)
        rgb = SOURCE_RGB if stroke.role == "source" else DEST_RGB
        pulse = 0.5 + 0.5 * math.sin(now * 2.2)
        painter.setBrush(QColor(*rgb, 9))
        painter.setPen(QPen(QColor(*rgb, int(17 + 10 * pulse)), 5.0))
        painter.drawRoundedRect(rect, 8.0, 8.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(*rgb, 110), 1.0))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        bracket = min(18.0, max(8.0, min(rect.width(), rect.height()) * 0.24))
        corner_path = QPainterPath()
        for start, elbow, end in (
            ((left, top + bracket), (left, top), (left + bracket, top)),
            ((right - bracket, top), (right, top), (right, top + bracket)),
            ((right, bottom - bracket), (right, bottom), (right - bracket, bottom)),
            ((left + bracket, bottom), (left, bottom), (left, bottom - bracket)),
        ):
            corner_path.moveTo(*start)
            corner_path.lineTo(*elbow)
            corner_path.lineTo(*end)
        painter.setPen(QPen(QColor(*rgb, 200), 2.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(corner_path)

    def _draw_particles(self, painter: QPainter, trail: List[Tuple[QPointF, float]], rgb: Tuple[int, int, int]):
        """Draw subtle glowing sparkles along the fading comet tail as shown in the gesture UI."""
        r, g, b = rgb
        for i, (pt, a) in enumerate(trail):
            if a < 0.12 or i % 9 != 0:
                continue
            ox = math.sin(i * 12.9898 + pt.x()) * 7.0
            oy = math.cos(i * 78.233 + pt.y()) * 7.0
            sz = 0.9 + (math.sin(i * 1.5) + 1.0) * 0.5
            particle_pt = QPointF(pt.x() + ox, pt.y() + oy)
            alpha = int(75 * a * (0.6 + 0.4 * math.sin(i * 2.5)))
            if alpha <= 0:
                continue
            painter.setBrush(QColor(r, g, b, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(particle_pt, sz, sz)

    def _draw_pointer_head(self, painter: QPainter, trail: List[Tuple[QPointF, float]],
                           rgb: Tuple[int, int, int], core_rgb: Tuple[int, int, int]):
        """Draw a crisp white arrowhead at the tip of the live trail."""
        if len(trail) < 3:
            return

        p1, a1 = trail[max(0, len(trail) - 4)]
        p2, a2 = trail[-1]
        
        if a2 <= 0.05:
            return

        angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())

        arrow_len = 22.0
        arrow_angle = math.pi / 6.5

        tip = QPointF(p2.x() + 5 * math.cos(angle), p2.y() + 5 * math.sin(angle))
        left = QPointF(tip.x() - arrow_len * math.cos(angle - arrow_angle),
                       tip.y() - arrow_len * math.sin(angle - arrow_angle))
        right = QPointF(tip.x() - arrow_len * math.cos(angle + arrow_angle),
                        tip.y() - arrow_len * math.sin(angle + arrow_angle))
        notch = QPointF(tip.x() - arrow_len * 0.65 * math.cos(angle),
                        tip.y() - arrow_len * 0.65 * math.sin(angle))
        
        r, g, b = rgb
        cr, cg, cb = core_rgb

        # Glow layer
        painter.setBrush(QColor(r, g, b, int(200 * a2)))
        painter.setPen(QPen(QColor(r, g, b, int(100 * a2)), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolygon([tip, left, notch, right])

        # Core pure white arrowhead
        painter.setBrush(QColor(255, 255, 255, int(255 * a2)))
        painter.setPen(QPen(QColor(cr, cg, cb, int(255 * a2)), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolygon([tip, left, notch, right])

    # ------------------------------------------------------------------
    # Markers + arrow
    # ------------------------------------------------------------------

    def _draw_marker(self, painter: QPainter, stroke: Stroke, rgb: Tuple[int, int, int]):
        if not stroke.points:
            return
        center = stroke.points[0].point
        radius = 13.0
        number = "1" if stroke.role == "source" else "2"

        painter.setBrush(QColor(9, 9, 11, 220))
        painter.setPen(QPen(QColor(*rgb), 2.5))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(QColor(255, 255, 255), 1))
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            QPointF(center.x() - 4, center.y() + 4),
            number,
        )

        # Label under the marker
        label = MARKER_LABELS.get(stroke.role, "")
        if label:
            font2 = QFont()
            font2.setPointSize(9)
            font2.setBold(True)
            painter.setFont(font2)
            lx = center.x()
            ly = center.y() + radius + 14
            painter.setPen(QPen(QColor(255, 255, 255, 235), 1))
            painter.drawText(QPointF(lx - 30, ly), label)

    def _draw_arrow(self, painter: QPainter, start: QPointF, end: QPointF):
        # Glow + core line
        painter.setPen(QPen(QColor(255, 255, 255, 28), 14,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(start, end)
        painter.setPen(QPen(QColor(230, 230, 250, 230), 3.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(start, end)

        # Arrowhead
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        arrow_len = 16.0
        arrow_angle = math.pi / 6
        p1 = QPointF(end.x() - arrow_len * math.cos(angle - arrow_angle),
                     end.y() - arrow_len * math.sin(angle - arrow_angle))
        p2 = QPointF(end.x() - arrow_len * math.cos(angle + arrow_angle),
                     end.y() - arrow_len * math.sin(angle + arrow_angle))
        painter.setBrush(QColor(230, 230, 250, 235))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon([end, p1, p2])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide_overlay()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw translucent dark backdrop
        painter.fillRect(self.rect(), QColor(15, 17, 23, 215))

        # Render subtle dot-grid background pattern matching the gesture screenshot
        grid_step = 28
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1.5))
        for x in range(14, self.rect().width(), grid_step):
            for y in range(14, self.rect().height(), grid_step):
                painter.drawPoint(x, y)

        # Render floating guide pill at top center
        banner_w, banner_h = 460, 34
        bx = int((self.rect().width() - banner_w) / 2)
        by = 20
        painter.setBrush(QColor(15, 23, 42, 230))
        painter.setPen(QPen(QColor(244, 114, 182, 180), 1.5))
        painter.drawRoundedRect(bx, by, banner_w, banner_h, 17, 17)

        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QPen(QColor(241, 245, 249), 1))
        painter.drawText(
            bx, by, banner_w, banner_h,
            Qt.AlignmentFlag.AlignCenter,
            "Draw: 1 Current  ->  2 Destination   |   Press ESC when done"
        )
        
        now = time.time()

        locked = [s for s in self._strokes if s.locked and len(s.points) >= 1]

        # Glow is layered behind the selected-element geometry, matching
        # TipTour's non-obscuring highlighter treatment.
        for stroke in locked:
            afterglow = self._focus_trail(stroke.points, now, stroke.committed_at)
            self._stroke_trail(painter, afterglow, ACTIVE_RGB, ACTIVE_CORE)

        # Subdued semantic strokes and pulsing focus outlines remain visible
        # for source/destination, independently of the temporary blue glow.
        for s in locked:
            rgb = SOURCE_RGB if s.role == "source" else DEST_RGB
            semantic_path = QPainterPath()
            if s.points:
                semantic_path.moveTo(s.points[0].point)
                for point in s.points[1:]:
                    semantic_path.lineTo(point.point)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(*rgb, 95), 2.5,
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(semantic_path)
            self._draw_focus_outline(painter, s, now)
            self._draw_marker(painter, s, rgb)

        # Connecting arrow: source → destination.
        if len(locked) >= 2:
            src = next((s for s in locked if s.role == "source"), None)
            dst = next((s for s in locked if s.role == "destination"), None)
            if src is not None and dst is not None:
                c1 = stroke_center([p.point for p in src.points])
                c2 = stroke_center([p.point for p in dst.points])
                if c1 is not None and c2 is not None:
                    self._draw_arrow(painter, c1, c2)

        # Active stroke: same glow, with a crisp white-blue pointer at the tip.
        if self._current_stroke is not None and len(self._current_stroke.points) >= 1:
            trail = self._build_trail(
                self._current_stroke.points[-self.MAX_VISIBLE_TRAIL_POINTS:],
                now, self.TRAIL_SECONDS
            )
            self._stroke_trail(painter, trail, ACTIVE_RGB, ACTIVE_CORE)
            self._draw_particles(painter, trail, ACTIVE_RGB)
            self._draw_pointer_head(painter, trail, ACTIVE_RGB, ACTIVE_CORE)

        painter.end()
