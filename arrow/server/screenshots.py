"""Screenshot file handling: validation, collision-safe atomic writes, crop math.

These helpers are deliberately free of Qt/mss dependencies so the risky logic
(base64 validation, image sniffing, path safety, monitor-relative crop
arithmetic) is unit-testable without a real screen.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import io
import os
import re
import time
import uuid
from typing import Any, Mapping, Optional, Sequence, Tuple

# Hard limits. The HTTP layer already caps request bodies (8 MiB); these bound
# what happens *after* decoding so a small request cannot expand into a giant
# image allocation.
MAX_DECODED_BYTES = 6 * 1024 * 1024
MAX_IMAGE_DIMENSION = 20_000
MAX_IMAGE_PIXELS = 80_000_000

ALLOWED_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp", "GIF": ".gif", "WEBP": ".webp"}
_FORMAT_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"BM", "BMP"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
)
_SAFE_PREFIX = re.compile(r"^[a-z0-9_]+$")


class UploadError(Exception):
    """Validation failure for an uploaded image.

    ``status`` is the HTTP status code the caller should return.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def unique_filename(prefix: str, suffix: str = ".png", now: Optional[float] = None) -> str:
    """Collision-resistant filename: ``<prefix>_<YYYYmmdd_HHMMSS>_<uuid8>``.

    The uuid component makes same-second and concurrent saves unique; the
    timestamp keeps names human-sortable and preserves the existing naming
    convention so old references stay recognizable.
    """
    if not _SAFE_PREFIX.match(prefix):
        raise UploadError(f"Invalid filename prefix: {prefix!r}")
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
        raise UploadError(f"Invalid filename suffix: {suffix!r}")
    ts = datetime.datetime.fromtimestamp(now if now is not None else time.time())
    return f"{prefix}_{ts.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"


def decode_image_b64(payload: Any) -> bytes:
    """Strictly decode a base64 image payload with a size ceiling."""
    if not isinstance(payload, str) or not payload.strip():
        raise UploadError("image (base64) required")
    raw = payload.strip()
    # Allow a data URL wrapper.
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma == -1:
            raise UploadError("Malformed data URL")
        raw = raw[comma + 1:]
    # Base64 expands 3 bytes to 4 chars; bound the encoded size first so a
    # huge payload is rejected before any allocation.
    if len(raw) > (MAX_DECODED_BYTES * 4) // 3 + 8:
        raise UploadError("Image exceeds the maximum allowed size", status=413)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise UploadError("image is not valid base64") from None
    if not data:
        raise UploadError("Decoded image is empty")
    if len(data) > MAX_DECODED_BYTES:
        raise UploadError("Image exceeds the maximum allowed size", status=413)
    return data


def sniff_format(data: bytes) -> Optional[str]:
    """Return a known image format name from magic bytes, or None."""
    for magic, name in _FORMAT_MAGIC:
        if data.startswith(magic):
            return name
    # WEBP: RIFF....WEBP
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def validate_image(data: bytes) -> Tuple[str, int, int]:
    """Verify ``data`` is a real, size-bounded image.

    Returns ``(format_name, width, height)``. Raises :class:`UploadError`
    when the payload is not a supported image or violates dimension limits.
    """
    fmt = sniff_format(data)
    if fmt is None:
        raise UploadError("Payload is not a supported image (png/jpeg/bmp/gif/webp)", status=415)
    if fmt not in ALLOWED_FORMATS:
        raise UploadError(f"Unsupported image format: {fmt}", status=415)
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover - dependency always present
        raise UploadError("Image library unavailable", status=500) from e
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            img.verify()
    except UploadError:
        raise
    except Exception as e:
        raise UploadError("Image could not be decoded") from e
    if width <= 0 or height <= 0:
        raise UploadError("Image has invalid dimensions")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise UploadError("Image dimensions exceed the allowed limit", status=413)
    if width * height > MAX_IMAGE_PIXELS:
        raise UploadError("Image pixel count exceeds the allowed limit", status=413)
    return fmt, width, height


def safe_join(directory: str, filename: str) -> str:
    """Join ``filename`` under ``directory`` refusing traversal.

    Raises :class:`UploadError` (404) when the result would escape the
    directory. Used before any filesystem access on user-supplied names.
    """
    from arrow.server.security import is_safe_filename

    if not is_safe_filename(filename):
        raise UploadError("Invalid screenshot filename", status=404)
    base = os.path.abspath(directory)
    target = os.path.abspath(os.path.join(base, filename))
    if os.path.commonpath([base, target]) != base or target == base:
        raise UploadError("Invalid screenshot filename", status=404)
    return target


def save_image_bytes(data: bytes, directory: str, prefix: str, suffix: str = ".png") -> Tuple[str, str]:
    """Atomically write image bytes under ``directory`` with a unique name.

    The data is written to a temporary file in the same directory and moved
    into place with ``os.replace`` so concurrent readers never observe a
    partially written file. Returns ``(filename, absolute_path)``.
    """
    fmt, _, _ = validate_image(data)
    filename = unique_filename(prefix, suffix)
    path = safe_join(directory, filename)
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise UploadError("Failed to save image", status=500) from None
    return filename, path


def save_decoded_upload(payload: Any, directory: str, prefix: str) -> Tuple[str, str, str]:
    """Decode + validate + save a base64 upload.

    Returns ``(filename, absolute_path, format)``.
    """
    data = decode_image_b64(payload)
    fmt, _, _ = validate_image(data)
    suffix = ALLOWED_FORMATS.get(fmt, ".png")
    filename, path = save_image_bytes(data, directory, prefix, suffix=suffix)
    return filename, path, fmt


# ---------------------------------------------------------------------------
# Monitor-relative crop arithmetic
# ---------------------------------------------------------------------------

Rect = Mapping[str, Any]
Monitor = Mapping[str, Any]


def monitor_for_rect(rect: Rect, monitors: Sequence[Monitor]) -> Monitor:
    """Pick the monitor that actually contains ``rect``.

    Uses the rectangle center (falling back to its origin) and returns the
    monitor whose bounds contain that point. ``monitors`` must be MSS-style
    dicts with ``left/top/width/height`` (do **not** include MSS's synthetic
    all-in-one monitor 0, which would swallow every point).
    """
    if not monitors:
        raise ValueError("No monitors provided")
    x = int(rect.get("x", 0))
    y = int(rect.get("y", 0))
    w = int(rect.get("width", 0))
    h = int(rect.get("height", 0))
    cx = x + w // 2
    cy = y + h // 2
    for m in monitors:
        left, top = int(m["left"]), int(m["top"])
        if left <= cx < left + int(m["width"]) and top <= cy < top + int(m["height"]):
            return m
    # Center outside every monitor (partially off-screen rect): choose the
    # monitor with the largest overlap area.
    best = None
    best_area = -1
    for m in monitors:
        left, top = int(m["left"]), int(m["top"])
        iw = max(0, min(x + w, left + int(m["width"])) - max(x, left))
        ih = max(0, min(y + h, top + int(m["height"])) - max(y, top))
        area = iw * ih
        if area > best_area:
            best_area = area
            best = m
    if best is None or best_area <= 0:
        raise ValueError("Rectangle does not intersect any monitor")
    return best


def crop_box_in_monitor(rect: Rect, monitor: Monitor) -> Tuple[int, int, int, int]:
    """Convert a virtual-desktop rect into a crop box in monitor image pixels.

    The returned ``(left, top, right, bottom)`` is relative to the *captured
    image's* origin, which is the monitor's ``left/top`` — never the desktop
    origin. This is the fix for the audit's nonzero-origin cropping bug.
    """
    x = int(rect.get("x", 0))
    y = int(rect.get("y", 0))
    w = int(rect.get("width", 0))
    h = int(rect.get("height", 0))
    if w <= 0 or h <= 0:
        raise ValueError("Rectangle must have positive width/height")
    origin_x = int(monitor["left"])
    origin_y = int(monitor["top"])
    monitor_w = int(monitor["width"])
    monitor_h = int(monitor["height"])

    left = x - origin_x
    top = y - origin_y
    right = left + w
    bottom = top + h

    # Clamp to the captured image bounds; never produce an empty box.
    left = max(0, min(left, monitor_w))
    top = max(0, min(top, monitor_h))
    right = max(left, min(right, monitor_w))
    bottom = max(top, min(bottom, monitor_h))
    if right <= left or bottom <= top:
        raise ValueError("Rectangle does not overlap the captured monitor")
    return left, top, right, bottom


def crop_box_for_monitors(rect: Rect, monitors: Sequence[Monitor]) -> Tuple[Monitor, Tuple[int, int, int, int]]:
    """Convenience: pick the monitor and compute its normalized crop box."""
    monitor = monitor_for_rect(rect, monitors)
    return monitor, crop_box_in_monitor(rect, monitor)


__all__ = [
    "ALLOWED_FORMATS",
    "MAX_DECODED_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "UploadError",
    "crop_box_for_monitors",
    "crop_box_in_monitor",
    "decode_image_b64",
    "monitor_for_rect",
    "safe_join",
    "save_decoded_upload",
    "save_image_bytes",
    "sniff_format",
    "unique_filename",
    "validate_image",
]
