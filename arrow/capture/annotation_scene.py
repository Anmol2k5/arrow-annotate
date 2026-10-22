"""Build semantic capture regions without losing the user's recorded ink."""

import math
from dataclasses import dataclass

from arrow.capture.session import Annotation, generate_uuidv7

_COLORS = {"source": "#ef4444", "destination": "#22c55e"}
_MAX_ANALYSIS_POINTS = 180
_MAX_EXACT_PATH_POINTS = 512
_EPSILON = 1e-9

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]


def _bounds(points: list[dict]) -> dict:
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    return {"x": min(xs) - 8, "y": min(ys) - 8,
            "width": max(xs) - min(xs) + 16, "height": max(ys) - min(ys) + 16}


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _simple_path(points: list[Point], *, closed: bool = False) -> bool:
    """Reject intersections and retracing, with an optional closing segment."""
    if closed and _distance(points[0], points[-1]) < _EPSILON:
        points = points[:-1]
    count = len(points)
    edge_count = count if closed else count - 1
    for i in range(edge_count):
        a, b = points[i], points[(i + 1) % count]
        if i + 1 < edge_count or closed:
            c = points[(i + 2) % count]
            dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
            if abs(_cross(a, b, c)) < _EPSILON and dot < -_EPSILON:
                return False
        for j in range(i + 2, edge_count):
            if closed and i == 0 and j == edge_count - 1:
                continue
            c, d = points[j], points[(j + 1) % count]
            if (max(a[0], b[0]) < min(c[0], d[0]) - _EPSILON
                    or max(c[0], d[0]) < min(a[0], b[0]) - _EPSILON
                    or max(a[1], b[1]) < min(c[1], d[1]) - _EPSILON
                    or max(c[1], d[1]) < min(a[1], b[1]) - _EPSILON):
                continue
            ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
            cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
            if ab_c * ab_d <= _EPSILON ** 2 and cd_a * cd_b <= _EPSILON ** 2:
                return False
    return True


@dataclass(frozen=True)
class _Loop:
    end: int
    bounds: Bounds
    diagonal: float
    closure: float


def _closed_prefixes(points: list[Point]) -> list[_Loop]:
    """Find compact, simple, nearly closed loops starting at the first point."""
    candidates = []
    path_length = 0.0
    min_x = max_x = points[0][0]
    min_y = max_y = points[0][1]
    # Relative coordinates keep area and tolerances independent of monitor origin.
    area = 0.0
    origin = points[0]
    for end in range(1, len(points)):
        point, previous = points[end], points[end - 1]
        min_x, max_x = min(min_x, point[0]), max(max_x, point[0])
        min_y, max_y = min(min_y, point[1]), max(max_y, point[1])
        path_length += _distance(previous, point)
        area += _cross(origin, previous, point) / 2
        width, height = max_x - min_x, max_y - min_y
        diagonal = math.hypot(width, height)
        if end < 4 or min(width, height) <= max(width, height) * 0.15 or diagonal < 1e-5:
            continue
        closure = _distance(origin, point) / diagonal
        if (closure > 0.18 or not 1.8 <= path_length / diagonal <= 4.0
                or abs(area) < width * height * 0.5):
            continue
        if _simple_path(points[:end + 1], closed=True):
            candidates.append(_Loop(end, (min_x, min_y, max_x, max_y), diagonal, closure))
    return candidates


def _analysis_points(points: list[dict]) -> tuple[list[Point], list[int]]:
    """Normalize and bound geometric work; retain indices into the original ink."""
    min_x, max_x = min(p["x"] for p in points), max(p["x"] for p in points)
    min_y, max_y = min(p["y"] for p in points), max(p["y"] for p in points)
    scale = max(max_x - min_x, max_y - min_y)
    if scale <= 0:
        return [], []
    normalized: list[Point] = []
    indices: list[int] = []
    for index, point in enumerate(points):
        value = ((point["x"] - min_x) / scale, (point["y"] - min_y) / scale)
        if not normalized or _distance(value, normalized[-1]) > _EPSILON:
            normalized.append(value)
            indices.append(index)
    if len(normalized) > _MAX_ANALYSIS_POINTS:
        selected = [round(i * (len(normalized) - 1) / (_MAX_ANALYSIS_POINTS - 1))
                    for i in range(_MAX_ANALYSIS_POINTS)]
        normalized = [normalized[i] for i in selected]
        indices = [indices[i] for i in selected]
    return normalized, indices


def _original_path_is_simple(points: list[dict], *, closed: bool = False) -> bool:
    """Validate original ink; sampling alone cannot establish lack of crossings.

    Short paths get exact segment checks. Longer paths need a linear-time
    certificate: a strictly monotone open path, or a convex closed contour
    making exactly one turn. Other complex paths conservatively remain ink.
    """
    if len(points) < 2:
        return False
    min_x, max_x = min(p["x"] for p in points), max(p["x"] for p in points)
    min_y, max_y = min(p["y"] for p in points), max(p["y"] for p in points)
    scale = max(max_x - min_x, max_y - min_y)
    if scale <= 0:
        return False
    path: list[Point] = []
    for point in points:
        value = ((point["x"] - min_x) / scale, (point["y"] - min_y) / scale)
        if not path or value != path[-1]:
            path.append(value)
    if len(path) <= _MAX_EXACT_PATH_POINTS:
        return _simple_path(path, closed=closed)
    if not closed:
        return any(all(a[axis] < b[axis] for a, b in zip(path, path[1:]))
                   or all(a[axis] > b[axis] for a, b in zip(path, path[1:])) for axis in (0, 1))
    if _distance(path[0], path[-1]) < _EPSILON:
        path.pop()
    turn, direction = 0.0, 0
    for i, a in enumerate(path):
        b, c = path[(i + 1) % len(path)], path[(i + 2) % len(path)]
        cross = _cross(a, b, c)
        dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if abs(cross) <= _EPSILON ** 2:
            if dot < 0:
                return False
            continue
        sign = 1 if cross > 0 else -1
        if direction and sign != direction:
            return False
        direction = sign
        turn += math.atan2(cross, dot)
    return abs(abs(turn) - 2 * math.pi) < 1e-6


def _original_boundary(points: list[dict], indices: list[int], boundary: int, anchor: dict) -> int:
    """Refine a sampled closure to the nearest actual point in its local span."""
    left, right = indices[max(0, boundary - 1)], indices[min(len(indices) - 1, boundary + 1)]
    return min(range(left, right + 1),
               key=lambda i: math.hypot(points[i]["x"] - anchor["x"], points[i]["y"] - anchor["y"]))


def _infer_regions(points: list[dict]) -> tuple[list[dict], list[dict] | None]:
    """Infer targets only for two separated loops joined by a direct connector."""
    sampled, indices = _analysis_points(points)
    if len(sampled) < 10:
        return points, None
    prefixes = _closed_prefixes(sampled)
    if not prefixes:
        return points, None
    suffixes = _closed_prefixes(list(reversed(sampled)))
    pairs = []
    for source in prefixes:
        for destination in suffixes:
            dest_start = len(sampled) - 1 - destination.end
            if dest_start <= source.end:
                continue
            sx1, sy1, sx2, sy2 = source.bounds
            dx1, dy1, dx2, dy2 = destination.bounds
            gap = math.hypot(max(sx1 - dx2, dx1 - sx2, 0), max(sy1 - dy2, dy1 - sy2, 0))
            largest = max(source.diagonal, destination.diagonal)
            connector = sampled[source.end:dest_start + 1]
            distance = _distance(connector[0], connector[-1])
            length = sum(_distance(a, b) for a, b in zip(connector, connector[1:]))
            if gap < largest * 0.25 or distance < largest or length <= 0 or distance / length < 0.85:
                continue
            if not _simple_path(connector):
                continue
            pairs.append((source.closure + destination.closure, source.end, dest_start))
    if pairs:
        _, source_end, destination_start = min(pairs)
        source_index = _original_boundary(points, indices, source_end, points[0])
        destination_index = _original_boundary(points, indices, destination_start, points[-1])
        source_points, destination_points = points[:source_index + 1], points[destination_index:]
        if (source_index < destination_index
                and _original_path_is_simple(source_points, closed=True)
                and _original_path_is_simple(destination_points, closed=True)
                and _original_path_is_simple(points[source_index:destination_index + 1])):
            return source_points, destination_points

    # A completed first loop still identifies the source before the user has
    # completed a destination. A plain line has no qualifying prefix at all.
    for loop in sorted(prefixes, key=lambda candidate: (candidate.closure, candidate.end)):
        tail = sampled[loop.end:]
        if len(tail) < 2:
            continue
        displacement = _distance(tail[0], tail[-1])
        length = sum(_distance(a, b) for a, b in zip(tail, tail[1:]))
        if displacement > loop.diagonal and length > 0 and displacement / length >= 0.85:
            source_index = _original_boundary(points, indices, loop.end, points[0])
            if _original_path_is_simple(points[:source_index + 1], closed=True):
                return points[:source_index + 1], None
    return points, None


def _border_point(rectangle: dict, toward: Point) -> Point:
    cx = rectangle["x"] + rectangle["width"] / 2
    cy = rectangle["y"] + rectangle["height"] / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    factor = 1 / max(abs(dx) / (rectangle["width"] / 2), abs(dy) / (rectangle["height"] / 2))
    return cx + dx * factor, cy + dy * factor


def build_annotation_scene(strokes: list[dict]) -> list[Annotation]:
    """Return ordered regions, complete supporting ink, and a visible connector.

    Points use global logical desktop coordinates. Explicit source/destination
    roles take precedence; inference applies only to one source-only stroke.
    """
    strokes = [stroke for stroke in strokes if stroke.get("points")]
    if not strokes:
        return []
    regions = {role: [point for stroke in strokes if stroke["role"] == role for point in stroke["points"]]
               for role in _COLORS}
    if len(strokes) == 1 and strokes[0]["role"] == "source":
        source_points, destination_points = _infer_regions(strokes[0]["points"])
        regions["source"] = source_points
        regions["destination"] = destination_points or []
    scene: list[Annotation] = []

    def add(annotation_type, role, geometry, label="", style=None):
        scene.append(Annotation(id=generate_uuidv7(), type=annotation_type, role=role,
                                label=label, geometry=geometry, style=style or {}, order=len(scene) + 1))

    rectangles = {}
    for role, label in (("source", "1 Source"), ("destination", "2 Destination")):
        if regions[role]:
            rectangles[role] = _bounds(regions[role])
            add("rectangle", role, rectangles[role], label, {"color": _COLORS[role]})
    for stroke in strokes:
        role = stroke["role"]
        add("freehand", "supporting", {"points": [dict(point) for point in stroke["points"]]},
            style={"color": _COLORS.get(role, "#a78bfa"), "semantic_role": role})
    if "source" in rectangles and "destination" in rectangles:
        source_rect, destination_rect = rectangles["source"], rectangles["destination"]
        source_center = (source_rect["x"] + source_rect["width"] / 2,
                         source_rect["y"] + source_rect["height"] / 2)
        destination_center = (destination_rect["x"] + destination_rect["width"] / 2,
                              destination_rect["y"] + destination_rect["height"] / 2)
        if _distance(source_center, destination_center) > _EPSILON:
            x1, y1 = _border_point(source_rect, destination_center)
            x2, y2 = _border_point(destination_rect, source_center)
            # Intersecting selections can put the facing borders in reverse
            # order. Preserve both explicit regions without a misleading arrow.
            forward = ((x2 - x1) * (destination_center[0] - source_center[0])
                       + (y2 - y1) * (destination_center[1] - source_center[1]))
            if forward > _EPSILON:
                add("arrow", "informational", {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    style={"color": "#a78bfa"})
    return scene
