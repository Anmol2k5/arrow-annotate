"""
Strict schemas for the spatial intent compiler (Phase 9).

The :class:`ChangeRequest` is the reviewable, implementable JSON output produced
from a capture. It deliberately separates observed facts from inferences so a
coding agent (and the user, in the notch) can tell what Arrow *knows* from what
it *guessed*.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Intent(str, Enum):
    MOVE_ELEMENT = "move_element"
    RESIZE_ELEMENT = "resize_element"
    RESTYLE_ELEMENT = "restyle_element"
    REPLACE_CONTENT = "replace_content"
    REMOVE_ELEMENT = "remove_element"
    ADD_ELEMENT = "add_element"
    ALIGN_ELEMENTS = "align_elements"
    CHANGE_SPACING = "change_spacing"
    CHANGE_RESPONSIVE_BEHAVIOR = "change_responsive_behavior"
    FIX_INTERACTION = "fix_interaction"
    FIX_VISUAL_BUG = "fix_visual_bug"
    INSPECT_OR_EXPLAIN = "inspect_or_explain"
    UNKNOWN = "unknown"


class MoveRelationship(str, Enum):
    BEFORE = "before"
    AFTER = "after"
    INSIDE = "inside"
    ABOVE = "above"
    BELOW = "below"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    ALIGN_START = "align_start"
    ALIGN_CENTER = "align_center"
    ALIGN_END = "align_end"
    REPLACE = "replace"
    APPROXIMATE_VISUAL_POSITION = "approximate_visual_position"
    UNKNOWN = "unknown"


class Anchor(BaseModel):
    """A resolved source or destination anchor."""

    role: str  # "source" | "destination"
    label: Optional[str] = None
    coordinate_space: Optional[str] = None
    geometry: dict = Field(default_factory=dict)
    element: dict = Field(default_factory=dict)  # DOM/native element context summary
    source_mapping: dict = Field(default_factory=dict)
    resolution_confidence: Optional[float] = None
    resolution_source: Optional[str] = None


class RequestedChange(BaseModel):
    operation: str
    description: str
    # e.g. dimension="width", direction="increase", magnitude="slight"
    details: dict = Field(default_factory=dict)
    inferred: bool = False


class Inference(BaseModel):
    field: str
    value: Any
    reason: str


class Ambiguity(BaseModel):
    field: str
    description: str
    severity: str = "warning"  # "warning" | "blocking"


class LikelyFile(BaseModel):
    source_file: str
    source_line: Optional[int] = None
    component: Optional[str] = None
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class ChangeRequest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    capture_id: Optional[str] = None
    project: dict = Field(default_factory=dict)
    application_mode: str = "web"  # "web" | "native" | "desktop"

    raw_user_request: str = ""
    normalized_intent: Intent = Intent.UNKNOWN
    summary: str = ""

    source: Optional[Anchor] = None
    destination: Optional[Anchor] = None
    move_relationship: Optional[MoveRelationship] = None

    requested_changes: list[RequestedChange] = Field(default_factory=list)
    responsive_expectations: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)

    likely_files: list[LikelyFile] = Field(default_factory=list)

    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    inferences: list[Inference] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    clarification_required: bool = False

    assets: dict = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


__all__ = [
    "SCHEMA_VERSION",
    "Intent",
    "MoveRelationship",
    "Anchor",
    "RequestedChange",
    "Inference",
    "Ambiguity",
    "LikelyFile",
    "ChangeRequest",
]
