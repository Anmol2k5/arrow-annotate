"""
Spatial intent compiler (Phase 9).

Converts a user's instruction plus spatial annotations and resolved context into
a strict, reviewable :class:`ChangeRequest`.

Design principles (from the plan):
  * Structured metadata has priority over visual guessing.
  * The screenshot informs layout relationships; pixels are never turned into
    hardcoded CSS positioning.
  * Prefer normal layout flow; preserve responsive behavior unless the user
    explicitly asks otherwise.
  * Every inference is marked. Missing facts are never invented.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from arrow.intent.schemas import (
    Ambiguity,
    Anchor,
    ChangeRequest,
    Inference,
    Intent,
    LikelyFile,
    MoveRelationship,
    RequestedChange,
)

log = logging.getLogger("arrow.intent.compiler")


class CompilerInput(BaseModel):
    capture_id: Optional[str] = None
    application_mode: str = "web"
    project: dict = Field(default_factory=dict)

    raw_instruction: str = ""
    voice_transcript: str = ""
    typed_corrections: str = ""

    annotations: list[dict] = Field(default_factory=list)
    source_context: dict = Field(default_factory=dict)
    destination_context: dict = Field(default_factory=dict)
    source_mapping: dict = Field(default_factory=dict)
    destination_mapping: dict = Field(default_factory=dict)

    assets: dict = Field(default_factory=dict)

    def instruction_text(self) -> str:
        # Typed corrections take priority over voice; raw instruction is the base.
        parts = [self.raw_instruction, self.voice_transcript, self.typed_corrections]
        combined = " ".join(p.strip() for p in parts if p and p.strip())
        return combined.strip()


# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_RESIZE_WORDS = {
    "wider": ("width", "increase"), "narrower": ("width", "decrease"),
    "taller": ("height", "increase"), "shorter": ("height", "decrease"),
    "bigger": ("size", "increase"), "larger": ("size", "increase"),
    "smaller": ("size", "decrease"), "resize": ("size", "unknown"),
}
_MAGNITUDE_WORDS = {
    "slightly": "slight", "slight": "slight", "a bit": "slight", "a little": "slight",
    "much": "large", "way": "large", "significantly": "large", "a lot": "large",
}
_RESTYLE_WORDS = ("color", "colour", "background", "font", "border", "rounded",
                  "shadow", "style", "bold", "italic", "padding-color", "theme")
_SPACING_WORDS = ("spacing", "margin", "padding", "gap", "closer", "further apart",
                  "more space", "less space")
_ALIGN_WORDS = ("align", "center", "centre", "left-align", "right-align", "justify")
_REMOVE_WORDS = ("remove", "delete", "hide", "get rid of")
_ADD_WORDS = ("add", "insert", "create a", "put a new")
_REPLACE_WORDS = ("replace", "change the text", "rename", "swap")
_FIX_INTERACTION_WORDS = ("not clickable", "doesn't work", "does not work", "broken",
                          "click", "hover", "focus", "not responding")
_FIX_VISUAL_WORDS = ("overflow", "overlap", "cut off", "misaligned", "glitch",
                     "looks wrong", "visual bug", "clipping")
_RESPONSIVE_WORDS = ("mobile", "responsive", "breakpoint", "tablet", "desktop layout",
                     "small screen")
_INSPECT_WORDS = ("what is", "explain", "why", "how does", "inspect", "tell me about")
_MOVE_WORDS = ("move", "drag", "relocate", "reposition", "put it")

_REL_KEYWORDS = {
    "before": MoveRelationship.BEFORE,
    "after": MoveRelationship.AFTER,
    "inside": MoveRelationship.INSIDE,
    "into": MoveRelationship.INSIDE,
    "above": MoveRelationship.ABOVE,
    "below": MoveRelationship.BELOW,
    "under": MoveRelationship.BELOW,
    "left of": MoveRelationship.LEFT_OF,
    "to the left": MoveRelationship.LEFT_OF,
    "right of": MoveRelationship.RIGHT_OF,
    "to the right": MoveRelationship.RIGHT_OF,
    "replace": MoveRelationship.REPLACE,
}


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class IntentCompiler:
    def compile(self, data: CompilerInput) -> ChangeRequest:
        text = data.instruction_text()
        lower = text.lower()

        req = ChangeRequest(
            capture_id=data.capture_id,
            project=data.project,
            application_mode=data.application_mode,
            raw_user_request=text,
            assets=data.assets,
        )

        source_ann, dest_ann, other_anns = _split_annotations(data.annotations)
        has_source = bool(source_ann) or bool(data.source_context) or bool(data.source_mapping)
        has_destination = bool(dest_ann) or bool(data.destination_context)

        # --- anchors -----------------------------------------------------
        if has_source:
            req.source = _build_anchor("source", source_ann, data.source_context, data.source_mapping)
        if has_destination:
            req.destination = _build_anchor(
                "destination", dest_ann, data.destination_context, data.destination_mapping
            )

        # --- intent ------------------------------------------------------
        intent, intent_evidence, intent_inferred = _classify_intent(lower, has_destination)
        req.normalized_intent = intent
        req.evidence.extend(intent_evidence)
        if intent_inferred:
            req.inferences.append(Inference(
                field="normalized_intent", value=intent.value,
                reason="Intent inferred from instruction keywords and annotation roles.",
            ))

        # --- requested changes ------------------------------------------
        req.requested_changes = _extract_changes(lower, intent, req)

        # --- move relationship ------------------------------------------
        if intent == Intent.MOVE_ELEMENT and has_destination:
            rel, rel_inferred, rel_reason = _move_relationship(
                lower, source_ann, dest_ann, data.source_context, data.destination_context
            )
            req.move_relationship = rel
            if rel_inferred:
                req.inferences.append(Inference(
                    field="move_relationship", value=rel.value, reason=rel_reason,
                ))

        # --- responsive expectations ------------------------------------
        req.responsive_expectations = _responsive_expectations(lower, req)

        # --- constraints -------------------------------------------------
        req.constraints = _constraints(lower)

        # --- acceptance criteria ----------------------------------------
        req.acceptance_criteria = _acceptance_criteria(intent, req)

        # --- likely files -----------------------------------------------
        req.likely_files = _likely_files(data.source_mapping, data.destination_mapping)

        # --- summary -----------------------------------------------------
        req.summary = _summary(intent, req, text)

        # --- ambiguities + confidence -----------------------------------
        _finalize(req, data, text, intent, has_source, has_destination)

        return req


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def _split_annotations(annotations: list[dict]):
    source_ann = None
    dest_ann = None
    others: list[dict] = []
    for a in annotations:
        role = a.get("role")
        if role == "source" and source_ann is None:
            source_ann = a
        elif role == "destination" and dest_ann is None:
            dest_ann = a
        else:
            others.append(a)
    return source_ann, dest_ann, others


def _build_anchor(role: str, annotation: Optional[dict], context: dict, mapping: dict) -> Anchor:
    label = None
    geometry: dict = {}
    coord_space = None
    if annotation:
        label = annotation.get("label") or None
        geometry = annotation.get("geometry", {}) or {}
        coord_space = annotation.get("coordinateSpace")
    if not label:
        label = context.get("text") or context.get("name") or None
    return Anchor(
        role=role,
        label=label,
        coordinate_space=coord_space,
        geometry=geometry,
        element=context or {},
        source_mapping=mapping or {},
        resolution_confidence=(mapping.get("confidence") if mapping else None)
        or (context.get("confidence") if context else None),
        resolution_source=(mapping.get("method") if mapping else None)
        or (context.get("source") if context else None),
    )


def _center(annotation: Optional[dict], context: dict) -> Optional[tuple[float, float]]:
    geom = (annotation or {}).get("geometry", {}) if annotation else {}
    if "x" in geom and "y" in geom:
        w = geom.get("width", 0)
        h = geom.get("height", 0)
        return geom["x"] + w / 2, geom["y"] + h / 2
    box = context.get("boundingBox") or context.get("bounding_rect") or {}
    if "x" in box and "y" in box:
        return box["x"] + box.get("width", 0) / 2, box["y"] + box.get("height", 0) / 2
    if "left" in box:
        return (box["left"] + box.get("right", box["left"])) / 2, (box["top"] + box.get("bottom", box["top"])) / 2
    return None


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def _has_any(text: str, words) -> bool:
    return any(w in text for w in words)


def _has_word(text: str, words) -> bool:
    """Whole-word match so e.g. 'move' does not match inside 'remove'."""
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return True
    return False


def _classify_intent(text: str, has_destination: bool) -> tuple[Intent, list[str], bool]:
    evidence: list[str] = []
    if not text:
        if has_destination:
            return Intent.MOVE_ELEMENT, ["No text; source+destination annotations imply a move."], True
        return Intent.UNKNOWN, ["No instruction text provided."], False

    if _has_any(text, _INSPECT_WORDS) and not _has_word(text, _MOVE_WORDS):
        return Intent.INSPECT_OR_EXPLAIN, ['Instruction asks to inspect/explain.'], False
    if _has_word(text, _REMOVE_WORDS):
        return Intent.REMOVE_ELEMENT, ["Instruction requests removal."], False
    if _has_word(text, _MOVE_WORDS) or has_destination:
        evidence.append("Instruction/annotations indicate movement.")
        return Intent.MOVE_ELEMENT, evidence, not _has_word(text, _MOVE_WORDS)
    if _has_any(text, _ADD_WORDS):
        return Intent.ADD_ELEMENT, ["Instruction requests adding an element."], False
    if _has_any(text, _REPLACE_WORDS):
        return Intent.REPLACE_CONTENT, ["Instruction requests content replacement."], False
    if _has_any(text, _ALIGN_WORDS):
        return Intent.ALIGN_ELEMENTS, ["Instruction requests alignment."], False
    if _has_any(text, _SPACING_WORDS):
        return Intent.CHANGE_SPACING, ["Instruction requests spacing change."], False
    if _has_any(text, list(_RESIZE_WORDS.keys())):
        return Intent.RESIZE_ELEMENT, ["Instruction requests resizing."], False
    if _has_any(text, _RESPONSIVE_WORDS) and _has_any(text, ("change", "fix", "make")):
        return Intent.CHANGE_RESPONSIVE_BEHAVIOR, ["Instruction targets responsive behavior."], False
    if _has_any(text, _RESTYLE_WORDS):
        return Intent.RESTYLE_ELEMENT, ["Instruction requests a style change."], False
    if _has_any(text, _FIX_INTERACTION_WORDS):
        return Intent.FIX_INTERACTION, ["Instruction reports an interaction problem."], False
    if _has_any(text, _FIX_VISUAL_WORDS):
        return Intent.FIX_VISUAL_BUG, ["Instruction reports a visual bug."], False
    return Intent.UNKNOWN, ["Could not classify intent from instruction."], False


# ---------------------------------------------------------------------------
# Requested changes
# ---------------------------------------------------------------------------

def _magnitude(text: str) -> Optional[str]:
    for word, mag in _MAGNITUDE_WORDS.items():
        if word in text:
            return mag
    return None


def _extract_changes(text: str, intent: Intent, req: ChangeRequest) -> list[RequestedChange]:
    changes: list[RequestedChange] = []

    if intent == Intent.MOVE_ELEMENT:
        changes.append(RequestedChange(
            operation="move",
            description="Move the source element to the destination location.",
        ))

    # Resize can accompany a move (e.g. "move this here and make it wider").
    for word, (dimension, direction) in _RESIZE_WORDS.items():
        if word in text:
            details: dict[str, Any] = {"dimension": dimension, "direction": direction}
            mag = _magnitude(text)
            if mag:
                details["magnitude"] = mag
            changes.append(RequestedChange(
                operation="resize",
                description=f"Adjust {dimension} ({direction}).",
                details=details,
                inferred=mag is None,
            ))
            break

    if intent == Intent.RESTYLE_ELEMENT or _has_any(text, _RESTYLE_WORDS):
        matched = [w for w in _RESTYLE_WORDS if w in text]
        if matched and intent != Intent.MOVE_ELEMENT or intent == Intent.RESTYLE_ELEMENT:
            changes.append(RequestedChange(
                operation="restyle",
                description="Apply the requested style change.",
                details={"properties": matched},
            ))

    if intent == Intent.CHANGE_SPACING:
        changes.append(RequestedChange(operation="change_spacing",
                                       description="Adjust spacing as described."))
    if intent == Intent.ALIGN_ELEMENTS:
        changes.append(RequestedChange(operation="align",
                                       description="Align the elements as described."))
    if intent == Intent.REMOVE_ELEMENT:
        changes.append(RequestedChange(operation="remove",
                                       description="Remove the source element."))
    if intent == Intent.ADD_ELEMENT:
        changes.append(RequestedChange(operation="add",
                                       description="Add the requested new element."))
    if intent == Intent.REPLACE_CONTENT:
        changes.append(RequestedChange(operation="replace_content",
                                       description="Replace the element's content/text."))
    if intent == Intent.FIX_INTERACTION:
        changes.append(RequestedChange(operation="fix_interaction",
                                       description="Fix the reported interaction problem."))
    if intent == Intent.FIX_VISUAL_BUG:
        changes.append(RequestedChange(operation="fix_visual_bug",
                                       description="Fix the reported visual bug."))
    if intent == Intent.INSPECT_OR_EXPLAIN:
        changes.append(RequestedChange(operation="inspect",
                                       description="Explain the element; no code change required."))
    return changes


# ---------------------------------------------------------------------------
# Move relationship
# ---------------------------------------------------------------------------

def _move_relationship(
    text: str,
    source_ann: Optional[dict],
    dest_ann: Optional[dict],
    source_ctx: dict,
    dest_ctx: dict,
) -> tuple[MoveRelationship, bool, str]:
    # Explicit keywords take priority (structured over visual).
    for keyword, rel in _REL_KEYWORDS.items():
        if keyword in text:
            return rel, False, f'Explicit spatial keyword "{keyword}" in instruction.'

    # Fall back to geometry comparison (a marked visual inference).
    src = _center(source_ann, source_ctx)
    dst = _center(dest_ann, dest_ctx)
    if src and dst:
        dx = dst[0] - src[0]
        dy = dst[1] - src[1]
        if abs(dx) >= abs(dy):
            rel = MoveRelationship.RIGHT_OF if dx >= 0 else MoveRelationship.LEFT_OF
        else:
            rel = MoveRelationship.BELOW if dy >= 0 else MoveRelationship.ABOVE
        return rel, True, "Relationship inferred from annotation geometry (visual position)."

    return MoveRelationship.APPROXIMATE_VISUAL_POSITION, True, (
        "No explicit relationship or geometry; using approximate visual position."
    )


# ---------------------------------------------------------------------------
# Responsive / constraints / acceptance
# ---------------------------------------------------------------------------

def _responsive_expectations(text: str, req: ChangeRequest) -> list[str]:
    expectations: list[str] = []
    if re.search(r"preserve.{0,20}(mobile|responsive|layout)", text):
        expectations.append("Preserve the existing mobile/responsive layout.")
    elif "mobile" in text or "responsive" in text:
        expectations.append("Account for mobile/responsive behavior.")
    if not expectations:
        expectations.append("Preserve existing responsive behavior unless explicitly changed.")
        req.inferences.append(Inference(
            field="responsive_expectations",
            value="preserve",
            reason="Default: responsive behavior is preserved when the user does not say otherwise.",
        ))
    return expectations


def _constraints(text: str) -> list[str]:
    constraints = [
        "Prefer normal layout flow; avoid unnecessary absolute positioning.",
        "Do not convert screenshot pixel positions into hardcoded CSS coordinates.",
        "Use existing design tokens and utility conventions where possible.",
    ]
    if "don't change" in text or "do not change" in text or "keep" in text:
        constraints.append("Respect the user's explicit 'keep/do not change' request.")
    return constraints


def _acceptance_criteria(intent: Intent, req: ChangeRequest) -> list[str]:
    criteria: list[str] = []
    src_label = req.source.label if req.source else "the element"
    dst_label = req.destination.label if req.destination else "the destination"

    if intent == Intent.MOVE_ELEMENT:
        criteria.append(f"{src_label} appears at {dst_label} after the change.")
        criteria.append("No unrelated elements are visually displaced.")
    if any(c.operation == "resize" for c in req.requested_changes):
        criteria.append(f"{src_label} has the requested new size.")
    if intent == Intent.RESTYLE_ELEMENT:
        criteria.append(f"{src_label} reflects the requested style change.")
    if intent == Intent.REMOVE_ELEMENT:
        criteria.append(f"{src_label} is no longer rendered.")
    if intent == Intent.ADD_ELEMENT:
        criteria.append("The new element renders at the requested location.")
    if intent == Intent.REPLACE_CONTENT:
        criteria.append(f"{src_label} shows the replacement content.")
    if intent in (Intent.FIX_INTERACTION, Intent.FIX_VISUAL_BUG):
        criteria.append("The reported problem is no longer reproducible.")

    for expectation in req.responsive_expectations:
        criteria.append(expectation)
    criteria.append("Existing tests continue to pass.")
    return criteria


# ---------------------------------------------------------------------------
# Likely files
# ---------------------------------------------------------------------------

def _likely_files(source_mapping: dict, destination_mapping: dict) -> list[LikelyFile]:
    files: list[LikelyFile] = []
    seen: set[tuple[str, Optional[int]]] = set()

    def add(mapping: dict):
        if not mapping:
            return
        if mapping.get("resolved") and mapping.get("source_file"):
            key = (mapping["source_file"], mapping.get("source_line"))
            if key not in seen:
                seen.add(key)
                files.append(LikelyFile(
                    source_file=mapping["source_file"],
                    source_line=mapping.get("source_line"),
                    component=mapping.get("component"),
                    confidence=mapping.get("confidence", 0.0),
                    evidence=mapping.get("evidence", []),
                ))
        for cand in mapping.get("candidates", []) or []:
            key = (cand.get("source_file"), cand.get("source_line"))
            if cand.get("source_file") and key not in seen:
                seen.add(key)
                files.append(LikelyFile(
                    source_file=cand["source_file"],
                    source_line=cand.get("source_line"),
                    component=cand.get("component"),
                    confidence=cand.get("confidence", 0.0),
                    evidence=cand.get("evidence", []),
                ))

    add(source_mapping)
    add(destination_mapping)
    files.sort(key=lambda f: f.confidence, reverse=True)
    return files


# ---------------------------------------------------------------------------
# Summary + finalization
# ---------------------------------------------------------------------------

def _summary(intent: Intent, req: ChangeRequest, text: str) -> str:
    if intent == Intent.UNKNOWN:
        return text or "No actionable instruction was provided."
    src = req.source.label if req.source else "the selected element"
    if intent == Intent.MOVE_ELEMENT:
        dst = req.destination.label if req.destination else "the destination"
        base = f"Move {src} to {dst}"
        if any(c.operation == "resize" for c in req.requested_changes):
            base += " and resize it"
        return base + "."
    readable = intent.value.replace("_", " ")
    return f"{readable.capitalize()} for {src}."


def _finalize(
    req: ChangeRequest,
    data: CompilerInput,
    text: str,
    intent: Intent,
    has_source: bool,
    has_destination: bool,
) -> None:
    confidences: list[float] = []

    if not text:
        req.ambiguities.append(Ambiguity(
            field="raw_user_request",
            description="No instruction text; intent relies solely on annotations.",
            severity="warning",
        ))

    if intent == Intent.UNKNOWN:
        req.ambiguities.append(Ambiguity(
            field="normalized_intent",
            description="Intent could not be determined from the instruction.",
            severity="blocking",
        ))

    if not has_source:
        req.ambiguities.append(Ambiguity(
            field="source",
            description="No source element/annotation was resolved.",
            severity="blocking",
        ))

    if intent == Intent.MOVE_ELEMENT and not has_destination:
        req.ambiguities.append(Ambiguity(
            field="destination",
            description="Move intent detected but no destination was provided.",
            severity="blocking",
        ))

    # Confidence from resolved anchors and mapping.
    if req.source and req.source.resolution_confidence is not None:
        confidences.append(float(req.source.resolution_confidence))
    if req.destination and req.destination.resolution_confidence is not None:
        confidences.append(float(req.destination.resolution_confidence))
    if req.likely_files:
        confidences.append(req.likely_files[0].confidence)

    intent_conf = 0.3 if intent == Intent.UNKNOWN else 0.75
    confidences.append(intent_conf)

    req.confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    if not req.likely_files:
        req.ambiguities.append(Ambiguity(
            field="likely_files",
            description="No repository file could be confidently mapped to the element.",
            severity="warning",
        ))
        req.inferences.append(Inference(
            field="likely_files", value=[],
            reason="Source mapping did not produce a confident file; agent must locate the component.",
        ))

    req.clarification_required = any(a.severity == "blocking" for a in req.ambiguities)


# ---------------------------------------------------------------------------
# Recompile (edit-context support)
# ---------------------------------------------------------------------------

def recompile_change_request(
    old: dict,
    new_instruction: str,
    compiler: Optional[IntentCompiler] = None,
) -> Optional[ChangeRequest]:
    """Recompile a persisted change request with an edited instruction.

    The previous anchors, element context, mappings, project and assets are
    reconstructed from the old change request, so only the instruction (and
    therefore the intent, requested changes, criteria and confidence) changes.
    Returns ``None`` when there is nothing to recompile.
    """
    if not old:
        return None

    annotations: list[dict] = []
    for role in ("source", "destination"):
        anchor = old.get(role)
        if anchor:
            annotations.append({
                "role": role,
                "label": anchor.get("label") or "",
                "geometry": anchor.get("geometry") or {},
                "coordinateSpace": anchor.get("coordinate_space"),
            })

    data = CompilerInput(
        capture_id=old.get("capture_id"),
        application_mode=old.get("application_mode", "web"),
        project=old.get("project") or {},
        raw_instruction=new_instruction,
        annotations=annotations,
        source_context=(old.get("source") or {}).get("element") or {},
        destination_context=(old.get("destination") or {}).get("element") or {},
        source_mapping=(old.get("source") or {}).get("source_mapping") or {},
        destination_mapping=(old.get("destination") or {}).get("source_mapping") or {},
        assets=old.get("assets") or {},
    )
    return (compiler or IntentCompiler()).compile(data)


__all__ = ["IntentCompiler", "CompilerInput", "recompile_change_request"]
