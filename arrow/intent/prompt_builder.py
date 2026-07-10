"""
Prompt builder (Phase 9).

Renders a :class:`ChangeRequest` into human-readable markdown for the notch
preview and for handing to a coding agent. It presents observed facts and marked
inferences separately so the request stays reviewable.
"""

from __future__ import annotations

from arrow.intent.schemas import Anchor, ChangeRequest


def _anchor_block(title: str, anchor: Anchor | None) -> list[str]:
    if anchor is None:
        return [f"**{title}:** (none)"]
    lines = [f"**{title}:** {anchor.label or '(unlabeled)'}"]
    element = anchor.element or {}
    selector = element.get("selector")
    if selector:
        lines.append(f"- Selector: `{selector}`")
    tag = element.get("tagName") or element.get("control_type")
    if tag:
        lines.append(f"- Element: {tag}")
    mapping = anchor.source_mapping or {}
    if mapping.get("source_file"):
        loc = mapping["source_file"]
        if mapping.get("source_line"):
            loc += f":{mapping['source_line']}"
        lines.append(f"- Likely source: `{loc}`")
    if anchor.resolution_confidence is not None:
        lines.append(f"- Resolution confidence: {anchor.resolution_confidence:.2f}")
    return lines


def build_markdown(req: ChangeRequest) -> str:
    lines: list[str] = []
    lines.append(f"# Arrow change request — {req.normalized_intent.value}")
    lines.append("")
    if req.summary:
        lines.append(f"**Summary:** {req.summary}")
        lines.append("")
    if req.raw_user_request:
        lines.append(f"**User request:** {req.raw_user_request}")
        lines.append("")

    lines.append(f"**Application mode:** {req.application_mode}")
    lines.append(f"**Overall confidence:** {req.confidence:.2f}")
    if req.clarification_required:
        lines.append("")
        lines.append("> Clarification required before implementation.")
    lines.append("")

    lines.extend(_anchor_block("Source", req.source))
    lines.append("")
    lines.extend(_anchor_block("Destination", req.destination))
    lines.append("")
    if req.move_relationship:
        lines.append(f"**Move relationship:** {req.move_relationship.value}")
        lines.append("")

    if req.requested_changes:
        lines.append("## Requested changes")
        for c in req.requested_changes:
            suffix = " _(inferred)_" if c.inferred else ""
            lines.append(f"- **{c.operation}**: {c.description}{suffix}")
            if c.details:
                detail = ", ".join(f"{k}={v}" for k, v in c.details.items())
                lines.append(f"  - {detail}")
        lines.append("")

    if req.responsive_expectations:
        lines.append("## Responsive expectations")
        for e in req.responsive_expectations:
            lines.append(f"- {e}")
        lines.append("")

    if req.constraints:
        lines.append("## Constraints")
        for constraint in req.constraints:
            lines.append(f"- {constraint}")
        lines.append("")

    if req.acceptance_criteria:
        lines.append("## Acceptance criteria")
        for criterion in req.acceptance_criteria:
            lines.append(f"- [ ] {criterion}")
        lines.append("")

    if req.likely_files:
        lines.append("## Likely files")
        for f in req.likely_files:
            loc = f.source_file + (f":{f.source_line}" if f.source_line else "")
            comp = f" ({f.component})" if f.component else ""
            lines.append(f"- `{loc}`{comp} — confidence {f.confidence:.2f}")
        lines.append("")

    if req.inferences:
        lines.append("## Inferences (not confirmed facts)")
        for inf in req.inferences:
            lines.append(f"- `{inf.field}`: {inf.reason}")
        lines.append("")

    if req.ambiguities:
        lines.append("## Ambiguities")
        for amb in req.ambiguities:
            lines.append(f"- [{amb.severity}] `{amb.field}`: {amb.description}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = ["build_markdown"]
