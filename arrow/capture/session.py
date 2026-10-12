import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

logger = logging.getLogger("arrow.capture.session")


def generate_uuidv7() -> str:
    """Generates a UUIDv7 string representation (compatible with standard UUID)."""
    # 48-bit timestamp in milliseconds
    ts_ms = int(time.time() * 1000)
    
    # Random bytes
    rand_a = os.urandom(2)
    rand_b = os.urandom(8)
    
    # Construct byte array
    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, 'big')
    b[6] = (rand_a[0] & 0x0F) | 0x70  # Version 7
    b[7] = rand_a[1]
    b[8] = (rand_b[0] & 0x3F) | 0x80  # Variant 1 (RFC 4122)
    b[9:16] = rand_b[1:8]
    
    return str(uuid.UUID(bytes=bytes(b)))


class CaptureState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    SELECTING_SOURCE = "SELECTING_SOURCE"
    SELECTING_DESTINATION = "SELECTING_DESTINATION"
    ANNOTATING = "ANNOTATING"
    COLLECTING_CONTEXT = "COLLECTING_CONTEXT"
    PROCESSING = "PROCESSING"
    PREVIEW = "PREVIEW"
    READY = "READY"
    SENDING = "SENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CaptureMode(str, Enum):
    """How the user expresses what they mean.

    ``POINT`` — one click is a complete capture (TipTour-style pointing).
    ``ANNOTATE`` — freehand source/destination strokes, the original flow.

    Both modes share one CaptureSession and one pipeline; the mode only
    decides which overlay gesture produces the selection.
    """

    POINT = "point"
    ANNOTATE = "annotate"


class Annotation(BaseModel):
    id: str
    type: str  # "pointer", "rectangle", "highlight", "arrow", "freehand", "text"
    role: str  # "source", "destination", "supporting", "informational"
    label: str = ""
    coordinateSpace: str = "virtual_screen"
    geometry: Dict[str, Any] = Field(default_factory=dict)
    style: Dict[str, Any] = Field(default_factory=dict)
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    order: int = 1


class CaptureSession(BaseModel):
    capture_id: str = Field(default_factory=generate_uuidv7)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: CaptureState = CaptureState.IDLE
    mode: str = "desktop"
    capture_mode: CaptureMode = CaptureMode.ANNOTATE
    project_id: Optional[str] = None
    annotations: List[Annotation] = Field(default_factory=list)
    source_anchor: Optional[Dict[str, Any]] = None
    destination_anchor: Optional[Dict[str, Any]] = None
    raw_instruction: str = ""
    voice_transcript: str = ""
    assets: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = None
    error: Optional[str] = None

    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


class SessionManager:
    """Manages the lifecycle of a single active CaptureSession and validates transitions."""

    # Set of final states from which you cannot transition except back to IDLE
    FINAL_STATES = {CaptureState.COMPLETED, CaptureState.FAILED, CaptureState.CANCELLED}

    # Map of allowed state transitions
    ALLOWED_TRANSITIONS: Dict[CaptureState, Set[CaptureState]] = {
        CaptureState.IDLE: {CaptureState.STARTING},
        CaptureState.STARTING: {CaptureState.SELECTING_SOURCE, CaptureState.ANNOTATING, CaptureState.CANCELLED},
        CaptureState.SELECTING_SOURCE: {CaptureState.SELECTING_DESTINATION, CaptureState.ANNOTATING, CaptureState.CANCELLED},
        CaptureState.SELECTING_DESTINATION: {CaptureState.ANNOTATING, CaptureState.CANCELLED},
        CaptureState.ANNOTATING: {CaptureState.COLLECTING_CONTEXT, CaptureState.CANCELLED},
        CaptureState.COLLECTING_CONTEXT: {CaptureState.PROCESSING, CaptureState.FAILED, CaptureState.CANCELLED},
        CaptureState.PROCESSING: {CaptureState.PREVIEW, CaptureState.FAILED, CaptureState.CANCELLED},
        CaptureState.PREVIEW: {CaptureState.READY, CaptureState.CANCELLED},
        CaptureState.READY: {CaptureState.SENDING, CaptureState.CANCELLED},
        CaptureState.SENDING: {CaptureState.RUNNING, CaptureState.FAILED, CaptureState.CANCELLED},
        CaptureState.RUNNING: {CaptureState.COMPLETED, CaptureState.FAILED, CaptureState.CANCELLED},
        CaptureState.COMPLETED: {CaptureState.IDLE},
        CaptureState.FAILED: {CaptureState.IDLE},
        CaptureState.CANCELLED: {CaptureState.IDLE},
    }

    def __init__(self) -> None:
        self._active_session: Optional[CaptureSession] = None
        # Sessions are mutated from the Qt main thread and from capture /
        # provider worker threads; every read-modify-write goes through this.
        self._lock = threading.RLock()

    @property
    def active_session(self) -> Optional[CaptureSession]:
        with self._lock:
            return self._active_session

    def is_active(self, capture_id: Optional[str]) -> bool:
        """True when capture_id still names the active session."""
        if not capture_id:
            return False
        with self._lock:
            return (
                self._active_session is not None
                and self._active_session.capture_id == capture_id
            )

    def start_session(self, project_id: Optional[str] = None) -> CaptureSession:
        """Initializes and returns a new active capture session."""
        with self._lock:
            if (
                self._active_session
                and self._active_session.state not in self.FINAL_STATES
                and self._active_session.state != CaptureState.IDLE
            ):
                logger.warning(
                    "Starting a new session while an active one (%s) is in progress. Cancelling old session.",
                    self._active_session.capture_id
                )
                self._transition_locked(CaptureState.CANCELLED)

            session = CaptureSession(project_id=project_id, state=CaptureState.IDLE)
            self._active_session = session
            self._transition_locked(CaptureState.STARTING)
            return session

    def transition_to(self, target_state: CaptureState) -> None:
        """Validates and applies a state transition to the active session."""
        with self._lock:
            self._transition_locked(target_state)

    def _transition_locked(self, target_state: CaptureState) -> None:
        if not self._active_session:
            raise ValueError("No active session exists to transition.")

        current = self._active_session.state

        # If target state is the same as current state, ignore (no-op)
        if current == target_state:
            return

        allowed = self.ALLOWED_TRANSITIONS.get(current, set())

        # Explicitly allow transitioning to FAILED or CANCELLED from non-final states
        is_abort = target_state in {CaptureState.FAILED, CaptureState.CANCELLED}
        is_current_active = current not in self.FINAL_STATES and current != CaptureState.IDLE

        if target_state not in allowed and not (is_abort and is_current_active):
            err_msg = f"Invalid state transition: {current.value} -> {target_state.value}"
            logger.error(err_msg)
            raise ValueError(err_msg)

        logger.info(
            "Session %s transitioning: %s -> %s",
            self._active_session.capture_id,
            current.value,
            target_state.value
        )
        self._active_session.state = target_state
        self._active_session.update_timestamp()

    def fail_if_active(self, capture_id: Optional[str], reason: str) -> bool:
        """Mark the session FAILED if capture_id is still current.

        Used by error boundaries (e.g. screenshot failures) so an exception can
        never leave the session wedged in an intermediate state. Returns True
        when the failure was applied.
        """
        with self._lock:
            if not self.is_active(capture_id):
                return False
            assert self._active_session is not None
            self._active_session.error = reason
            try:
                self._transition_locked(CaptureState.FAILED)
            except ValueError:
                # Already terminal — keep the recorded reason.
                logger.debug("fail_if_active: session already terminal")
            return True

    def complete_if_active(self, capture_id: Optional[str]) -> bool:
        """Mark the session COMPLETED if capture_id is still current.

        Used when the local capture pipeline succeeded but an optional
        downstream step (e.g. Agentation sync) failed: the capture itself is
        fine, so the session must not be failed.
        """
        with self._lock:
            if not self.is_active(capture_id):
                return False
            try:
                self._transition_locked(CaptureState.COMPLETED)
            except ValueError:
                logger.debug("complete_if_active: session already terminal")
                return False
            return True

    def clear_session(self) -> None:
        """Clears the active session references."""
        with self._lock:
            self._active_session = None
