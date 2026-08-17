# Capture → Compiled Change Request → Agent Handoff

## Problem Statement

A developer sees a UI problem — a button in the wrong place, spacing off,
something broken — and wants to tell a coding agent "move this there" without
writing a paragraph and pasting screenshots. Right now the app captures a
screenshot and sends it to Agentation with almost no context: the compiled
change request exists as modules but was never wired into the capture flow, the
notch only shows raw screenshots, drawing is a single bounding box with a jagged
trail, and there is no notion of a selected repository, so an agent has nowhere
safe to work. Context is lost at every step between "point at the screen" and
"agent edits the repo".

## Solution

From the user's perspective: activate Arrow, draw once around the current
element (marker **1**) and once at the destination (marker **2**), say or type
"move this here and make it slightly wider", release — and the notch shows the
annotated screenshot plus a compiled, human-readable change request (intent,
source → destination, confidence, likely file, acceptance criteria). The user
either copies that request or sends it straight to Codex or Claude Code, which
runs inside the selected repository. The whole capture is a single pipeline: the
same code path resolves the element (browser DOM → Windows UI Automation →
visual fallback), gathers repository context, renders annotations off-screen,
compiles the request, and persists everything — so the notch preview and the
agent prompt are the same structured truth.

## User Stories

1. As a developer, I want to draw a smooth neon trail around the element I care about, so that my selection is precise and easy to see even on a fast stroke.
2. As a developer, I want the drawing trail to fade smoothly instead of stepping, so that the selection feels polished and does not distract me.
3. As a developer, I want my first stroke to become the source and my second stroke to become the destination, so that "move this here" maps to exactly two points on screen.
4. As a developer, I want marker `1` and marker `2` rendered on the locked strokes, so that I can see which selection is source and which is destination.
5. As a developer, I want a connecting arrow drawn from source to destination, so that the intended movement is visible at a glance.
6. As a developer, I want my locked strokes to persist on screen until the capture completes or is cancelled, so that the comet-tail fade never destroys my selection data.
7. As a developer, I want to re-draw one stroke without deleting the other, so that fixing a sloppy source selection does not wipe my destination.
8. As a developer, I want the capture pipeline to resolve the element at my source and destination (browser DOM first, then native UI Automation, then a visual fallback), so that the agent gets real element context instead of raw pixels.
9. As a developer, I want the compiled change request to include intent, source, destination, move relationship, requested changes, confidence, and acceptance criteria, so that the agent can act without guessing.
10. As a developer, I want repository context (root, branch, commit, framework, dev-server URL, active route) attached to the capture, so that the agent knows where and against what to work.
11. As a developer, I want the annotated screenshot and crops (source, destination, context) generated off-screen, so that the raw screenshot stays clean and the annotations are always visible in the final image.
12. As a developer, I want the notch preview card to show the compiled intent, confidence, summary, source → destination, and likely file, so that I can verify what the agent will be asked before sending.
13. As a developer, I want to copy the change request as a paste-ready prompt that includes the screenshot path, so that I can paste it into any IDE or chat without losing context.
14. As a developer, I want a "Copy all" action that copies full change requests rather than raw annotation text, so that bulk handoff stays structured.
15. As a developer, I want to send the change request directly to Codex or Claude Code from the notch, so that I never copy-paste between apps.
16. As a developer, I want provider send buttons to be disabled when the CLI is not installed, so that I am not offered a dead action.
17. As a developer, I want provider runs to be confined to the selected repository, so that an agent never works outside the project I chose.
18. As a developer, I want to select the working repository once and have it persist across restarts, so that I do not re-pick a folder every session.
19. As a developer, I want old captures without an attached repository to fall back to the currently selected repository when sending, so that past captures remain actionable.
20. As a developer, I want a failed pipeline or provider run to surface an explicit failure state, so that I never see a silent dead-end.
21. As a developer, I want the capture record to include the full change request so that previews and history survive an app restart.
22. As a developer, I want to cancel or abandon a capture without corrupting the next one, so that stale voice results never attach to a new session.

## Implementation Decisions

- **Single pipeline, one orchestrator.** All capture flows go through one `ContextOrchestrator` entry point: freeze annotation scene → resolve anchors → collect repository context → render annotated screenshot → generate crops → compile change request → persist. No separate capture logic in the app shell, server routes, or preview UI.
- **Anchor resolution cascade.** Per anchor: browser extension DOM inspection via the WebSocket bridge (richest, exact element, confidence 0.9) → native resolution (UI Automation / window-title / URL, real confidence) → visual-only fallback (explicitly `resolved=false`, confidence 0.25). Low-confidence results are surfaced, never silently treated as exact.
- **Browser element → source mapping.** React debug metadata (`_debugSource`) maps an element to `source_file` / `source_line` / component for the change request's `likely_files`. Nothing is fabricated when metadata is absent.
- **Change request schema.** Reuses the existing strict `ChangeRequest` model (schema v1): intent, anchors, move relationship, requested changes, responsive expectations, constraints, acceptance criteria, likely files, confidence, inferences, ambiguities, clarification flag. Annotation labels have priority over DOM names in the anchor label; the DOM accessible name is carried in the anchor element.
- **Move-tool overlay contract.** The overlay now emits two rects instead of one. Prototype-decided result shape (trimmed):
  ```
  { "x", "y", "width", "height",          // overall = source (backward compatible)
    "source":      { "x", "y", "width", "height" },
    "destination": { "x", "y", "width", "height" } | null }
  ```
  First stroke becomes source, subsequent strokes become destination (re-drawing replaces the same role). Locked strokes are the persistent annotation scene; the comet-tail fade applies only to the live stroke.
- **Persistence.** `CaptureRecord` gains a `change_request` field, stored as JSON in the existing contexts table and read back — previews and provider sends read the same stored truth. Capture ids are UUIDv7 (no timestamp collisions).
- **Notch preview card.** Screenshot thumbnail renders a compact intent panel (intent chip, confidence, summary, source → destination, likely file) plus actions: copy the request, send to Codex, send to Claude. The paste-ready prompt is produced by one pure `format_change_request` function (header + instruction + anchors + confidence + likely file + requested changes + acceptance criteria + constraints + screenshot path).
- **Provider handoff.** `build_run_request` turns a change request into a `RunRequest` — the capture's repository wins, the currently selected repository is the fallback, and `None` is returned when no repository exists (never guess). `run_provider_sync` runs to completion and never raises: the final event (`done`/`error`) is returned. Providers are the existing CLI adapters (`codex exec --cd <repo>`, `claude -p --permission-mode default`), confined to the repo, `shell=True` never used, sensitive actions denied by default.
- **Repository selection.** A folder picker in the notch persists the selection to a JSON settings file (`~/.arrow/config.json`, `ARROW_HOME` override) and live-updates the orchestrator. The selected repo is shown in the notch toolbar.
- **Thread safety.** Worker threads only emit queued signals (e.g. `provider_finished`) so message boxes and widget mutations always happen on the Qt main thread. Raw screenshot capture stays on the main thread (the overlay must be hidden by the Qt main thread); everything after is background.
- **Failure semantics.** The pipeline returns a typed error instead of raising into a dead thread; the session transitions to `FAILED` and the user sees it.

## Testing Decisions

- **What makes a good test here:** exercise external behavior at the pipeline boundary, not implementation details. A good test feeds a session + rect + instruction (plus injected fakes for screenshot service, browser bridge, resolver, and store) into the orchestrator and asserts on the *outcome*: files written, change-request fields, persisted record, anchor resolution source and confidence. Determinism matters — tests must not depend on the machine's foreground window or a live browser.
- **Primary seam — `ContextOrchestrator.run()`:** the whole capture flow in one call. Tests: full browser-DOM pipeline (assets on disk, change request compiled, record persisted with `change_request` round-trip, repo context dev-server URL from page), source + destination (move relationship inferred from geometry, destination crop written), offline fallback (visual-only, low confidence surfaced honestly), pre-frozen annotations used verbatim, selected project dir feeding repository context, store optional, error surfacing.
- **Secondary seam — provider handoff:** `build_run_request` (capture repo wins, fallback repo, invalid fallback → `None`) and `run_provider_sync` (returns last event, never raises on `start_run` failure) with a fake provider.
- **Presentation seam:** `format_change_request` renders the paste-ready prompt; empty input → empty string.
- **Overlay math seam:** `stroke_rect` (padding + negative-coordinate clamping), `stroke_center`, role sequence (`_next_role`), `_build_trail` smoothing + alpha decay — all pure, no GUI.
- **Settings seam:** project-dir round-trip, invalid path not persisted, config dir created (via `ARROW_HOME` override).
- **Prior art:** the codebase already tests at exactly these seams — `tests/test_orchestrator.py`, `tests/test_provider_runner.py`, `tests/test_notch_status.py`, `tests/test_overlay_math.py`, `tests/test_settings.py`. The Qt widgets themselves contain no logic and are not unit-tested.

## Out of Scope

- Phase 15 end-to-end webpage test (React/Next.js test app driving the full capture flow through a real browser).
- Phase 16 packaging/installer, first-run onboarding, troubleshooting docs.
- Notch status header wiring (`StatusProvider` → notch widget).
- Edit-context recompile (editing instruction/source/destination in the notch before recompiling the change request).
- Undo/redo/clear/delete annotation tools and the text tool.
- MCP retrieval verified against a real Codex/Claude session; voice stale-result integration tests; OCR/UIA verification against real native apps.
- Screenshot retention controls and region redaction (Phase 14 privacy items).

## Further Notes

- The move relationship is inferred from annotation geometry when the instruction has no explicit spatial keyword, and is always marked as an inference.
- Record ids are now UUIDv7; the legacy timestamp id is gone from the capture path.
- The "Send to Agentation" path from the earlier flow is preserved unchanged alongside the new direct provider sends.
- Repository context fills git facts only when the selected path is a real git repository; otherwise those fields stay `None` (observed facts only, nothing fabricated).
