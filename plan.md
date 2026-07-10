# Arrow Annotate — Phase-by-Phase Refactor and Implementation Plan

Repository:

https://github.com/Anmol2k5/arrow-annotate

## Product objective

Arrow should become a local-first spatial-context tool for coding agents.

A user should be able to:

1. Open a webpage or desktop application.

2. Activate Arrow using a keyboard shortcut.

3. Point at or highlight an interface element.

4. Draw a pointer, rectangle, highlight, freehand mark or arrow.

5. For movement requests, select both:

   - the current element,
   - the desired destination.

6. Type or speak an instruction such as:

   “Move this button here, make it slightly wider, and preserve the mobile
   layout.”

7. See an annotated screenshot and interpreted request inside the notch.

8. Send the full context directly to Codex, Claude Code or another supported
   coding agent.

9. Let the coding agent retrieve:

   - annotated screenshot,
   - raw screenshot,
   - DOM or native application context,
   - repository context,
   - source and destination coordinates,
   - acceptance criteria,
   - user instruction.

10. Avoid manually copying screenshots or prompts.

---

# Important development rules

Follow these rules throughout the project:

1. Do not implement all phases in one large rewrite.
2. Complete one phase at a time.
3. Run tests after every phase.
4. Do not proceed to the next phase while critical tests in the current phase
   are failing.
5. Preserve working functionality unless it is intentionally replaced.
6. Create a Git checkpoint after every completed phase.
7. Do not redesign the notch before fixing the capture pipeline.
8. Do not add direct AI execution before the spatial context packet is reliable.
9. Do not use mock integrations in production-facing UI.
10. Do not claim a feature is complete unless its end-to-end test passes.
11. Avoid putting new logic into large files such as `main.py`, `notch.py` or
    `server.py`.
12. New functionality must be modular, typed and testable.
13. Every asynchronous operation must be associated with a unique capture
    session.
14. Never fabricate DOM selectors, component names, repository files or
    source-code line numbers.
15. Treat screenshots as supporting evidence, not the only source of context.

---

# Phase 0 — Repository audit and baseline

## Goal

Understand the existing project completely before modifying its architecture.

## Tasks

Inspect every file in the repository and document:

- application startup flow,
- hotkey handling,
- Qt event loop usage,
- screenshot creation,
- annotation rendering,
- voice input,
- capture storage,
- browser-extension communication,
- UI Automation resolution,
- OCR fallback,
- Agentation integration,
- Flask endpoints,
- notch UI,
- threading and asynchronous behavior,
- dependency management,
- hardcoded values,
- demo data,
- unused code,
- duplicate code,
- security risks.

Create:

```text
docs/current-architecture.md
docs/refactor-plan.md
docs/security-audit.md
```

Document the current flow from:

```text
User hotkey
→ overlay
→ drawing
→ screenshot
→ capture record
→ notch
→ Agentation
```

Identify every place where context is lost.

Specifically verify these suspected issues:

- annotation marks are not reliably baked into saved screenshots,
- only the primary monitor is captured,
- annotation points disappear after a timer,
- new strokes replace previous strokes,
- source and destination are not represented separately,
- browser context is not called from the primary capture flow,
- capture records contain empty context fields,
- browser response formats do not match resolver expectations,
- voice results can arrive after a capture is cancelled,
- Agentation selects an unrelated first session,
- local action endpoints are unauthenticated,
- shell execution is possible,
- screenshot and metadata deletion are inconsistent,
- timestamp IDs can collide,
- notch integrations and agent tasks are hardcoded demos.

## Deliverables

- Written architecture map.
- List of components that can be kept.
- List of components requiring refactoring.
- List of components requiring complete replacement.
- Dependency and security audit.
- Baseline test report.
- Baseline Git checkpoint.

## Completion criteria

Do not modify major functionality in this phase.

The phase is complete when the existing project and its failure points are
clearly documented.

---

# Phase 1 — Project foundation and modular structure

## Goal

Create a clean foundation before rebuilding core functionality.

## Tasks

Add or improve:

```text
README.md
LICENSE
pyproject.toml
.env.example
docs/
tests/
.github/workflows/
```

Move toward this logical structure:

```text
arrow/
├── app/
│   ├── application.py
│   └── lifecycle.py
├── capture/
│   ├── session.py
│   ├── screenshot_service.py
│   ├── coordinate_mapper.py
│   ├── annotation_scene.py
│   ├── renderer.py
│   └── crop_service.py
├── context/
│   ├── orchestrator.py
│   ├── browser_adapter.py
│   ├── windows_uia_adapter.py
│   ├── ocr_adapter.py
│   └── source_mapper.py
├── intent/
│   ├── compiler.py
│   ├── schemas.py
│   └── prompt_builder.py
├── storage/
│   ├── database.py
│   ├── models.py
│   ├── migrations.py
│   └── assets.py
├── providers/
│   ├── base.py
│   ├── codex.py
│   ├── claude.py
│   └── agentation.py
├── mcp/
│   ├── server.py
│   ├── tools.py
│   └── resources.py
├── ui/
│   ├── notch/
│   ├── overlay/
│   └── components/
└── browser_extension/
```

The exact package names may differ, but responsibilities must be separated.

Add:

- formatting,
- linting,
- type checking,
- unit test execution,
- CI workflow.

Use a strict schema library such as Pydantic for core data.

Add structured logging.

Do not silently catch all exceptions.

## Dependencies

Audit and explicitly declare all runtime dependencies.

Ensure dependencies imported by the project are present, including the HTTP
client used by the Agentation client.

Remove unused dependencies.

## Completion criteria

- Application still starts.
- Existing basic capture behavior still works.
- CI runs.
- Formatting, linting and basic tests pass.
- Major responsibilities are no longer being added directly to `main.py`.
- No new product functionality is required yet.

---

# Phase 2 — Capture session state machine

## Goal

Eliminate stale events, race conditions and disconnected capture state.

## Create a `CaptureSession`

Every capture must have:

```text
capture_id
created_at
updated_at
state
mode
project_id
annotations
source_anchor
destination_anchor
raw_instruction
voice_transcript
assets
context
provider
error
```

Use UUIDv7 or ULID for capture IDs.

## Required states

```text
IDLE
STARTING
SELECTING_SOURCE
SELECTING_DESTINATION
ANNOTATING
COLLECTING_CONTEXT
PROCESSING
PREVIEW
READY
SENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

## Required behavior

Every asynchronous event must include the `capture_id`.

This includes:

- microphone result,
- browser-extension response,
- UI Automation result,
- OCR result,
- screenshot completion,
- context compiler result,
- provider output.

Ignore any response whose capture ID is no longer active.

Only one active capture session should exist by default.

Provide explicit transitions and validation.

For example:

```text
IDLE → STARTING
STARTING → ANNOTATING
ANNOTATING → COLLECTING_CONTEXT
COLLECTING_CONTEXT → PROCESSING
PROCESSING → PREVIEW
PREVIEW → READY
READY → SENDING
SENDING → RUNNING
RUNNING → COMPLETED
```

Invalid transitions should produce logged errors.

## Voice input fixes

- Reset transcript correctly at the start of each session.
- Do not rely on an incorrectly scoped local variable.
- Voice input must be optional.
- Typed input must always be available.
- Stopping a capture must cancel or invalidate voice results.
- Recognition completion must not automatically send the request.
- Let the user edit the transcript before sending.

## Tests

Add tests for:

- valid state transitions,
- invalid state transitions,
- stale voice results,
- stale browser responses,
- cancellation,
- duplicate capture creation,
- provider responses from old sessions.

## Completion criteria

A cancelled session cannot update a newer session.

No asynchronous result can attach itself to the wrong capture.

---

# Phase 3 — Persistent annotation system

## Goal

Replace temporary freehand points with structured spatial annotations.

## Annotation types

Implement:

```text
PointerAnnotation
RectangleAnnotation
HighlightAnnotation
ArrowAnnotation
FreehandAnnotation
TextAnnotation
```

Every annotation should include:

```json
{
    "id": "uuid",
    "type": "rectangle",
    "role": "source",
    "label": "Current button",
    "coordinateSpace": "virtual_screen",
    "geometry": {},
    "style": {},
    "createdAt": "",
    "order": 1
}
```

## Annotation roles

Support:

```text
source
destination
supporting
informational
```

## Required functionality

- Multiple annotations per capture.
- New strokes must not delete earlier strokes.
- Undo.
- Redo.
- Clear.
- Delete selected annotation.
- Cancel capture.
- Change annotation label.
- Change annotation role.
- Pointer tool.
- Rectangle tool.
- Highlight tool.
- Arrow tool.
- Freehand tool.
- Move tool.

Visual fade animations must not delete annotation data.

The user’s persistent annotation scene should survive until the capture is saved
or cancelled.

## Move tool

Create a dedicated move interaction.

### Flow

1. User selects the move tool.
2. First selection becomes the source anchor.
3. Second selection becomes the destination anchor.
4. Draw marker `1` around the source.
5. Draw marker `2` at the destination.
6. Draw an arrow from source to destination.
7. Display labels:

   - `Current element`
   - `Move here`

Store source and destination separately.

Do not represent a move request using a single bounding box.

## Tests

- Multiple strokes persist.
- Source and destination remain separate.
- Undo and redo work.
- Clear removes all annotations.
- Visual animation does not modify persistent state.
- Annotation serialization and restoration work.

## Completion criteria

A user can draw multiple annotations and see all of them in the final annotation
scene.

---

# Phase 4 — Reliable screenshot generation

## Goal

Produce accurate raw and annotated screenshots independently of the live
overlay.

## Assets for every capture

Generate:

```text
raw.png
annotated.png
context-crop.png
source-crop.png
destination-crop.png
```

The destination crop is optional when no destination exists.

## Raw screenshot

The raw screenshot must not include Arrow’s overlay.

Do not depend on the operating system capturing the transparent annotation
window.

Hide or exclude the overlay before capturing.

## Annotated screenshot

Render annotations off-screen onto a copy of the raw screenshot.

The final annotated image must contain:

- pointers,
- rectangles,
- highlights,
- freehand strokes,
- text labels,
- source marker,
- destination marker,
- arrows.

## Coordinate systems

Define and document:

```text
Qt logical coordinates
virtual desktop coordinates
monitor-local coordinates
physical screenshot pixels
browser CSS pixels
browser screenshot pixels
```

Create a `CoordinateMapper`.

Support:

- negative screen coordinates,
- monitors positioned left of the primary monitor,
- monitors positioned above the primary monitor,
- secondary monitors,
- mixed DPI,
- 100% scaling,
- 125% scaling,
- 150% scaling,
- different monitor resolutions.

Do not clamp valid negative desktop coordinates to zero.

## Crop behavior

Generate:

- tight source crop,
- tight destination crop,
- padded context crop containing relevant annotations.

Ensure crop bounds remain inside the captured image.

## Tests

Test coordinate conversion using synthetic monitor configurations.

Include:

- primary monitor only,
- secondary monitor on the right,
- secondary monitor on the left,
- secondary monitor above,
- mixed-DPI configuration.

Test off-screen annotation rendering without launching the full UI.

## Completion criteria

The annotated screenshot always visibly contains the user’s persistent
annotations.

The raw screenshot always remains available separately.

---

# Phase 5 — Unified context orchestration

## Goal

Connect capture, annotations, browser context, native context and OCR through
one pipeline.

## Required pipeline

```text
Capture session
→ Freeze annotation scene
→ Capture raw screenshot
→ Resolve source anchor
→ Resolve destination anchor
→ Collect environment context
→ Render annotated screenshot
→ Generate crops
→ Compile structured request
→ Save capture
→ Show preview
```

Create one `ContextOrchestrator`.

Do not maintain separate disconnected capture pipelines in:

- `main.py`,
- Flask routes,
- screenshots UI,
- browser resolver,
- Agentation integration.

## Resolver priority

For webpages:

```text
Browser extension
→ accessibility/DOM information
→ visual fallback
```

For native Windows applications:

```text
Windows UI Automation
→ OCR fallback
→ visual-only fallback
```

Every resolver result must include:

```text
status
confidence
source
evidence
capture_id
```

## Confidence handling

Example:

```json
{
    "status": "resolved",
    "confidence": 0.92,
    "source": "browser_dom",
    "evidence": [
        "Pointer falls inside button bounds",
        "Accessible name matches visible label"
    ]
}
```

Low-confidence results must not be silently treated as exact.

## Completion criteria

The main capture flow populates actual context fields instead of leaving them
empty.

---

# Phase 6 — Browser extension spatial context

## Goal

Provide precise webpage context without fragile desktop-to-browser coordinate
guessing.

## Browser-native annotation

When the active target is a supported browser:

1. Tell the extension to enter annotation mode.
2. Inject a transparent annotation layer into the webpage.
3. Collect pointer input directly in browser viewport coordinates.
4. Resolve the element using:

   - `event.composedPath()`,
   - `document.elementsFromPoint()`.
5. Capture the visible tab.
6. Return structured context to the desktop application.

Avoid converting operating-system screen coordinates into browser coordinates
whenever browser-native capture is available.

## Versioned protocol

Create a strict protocol such as:

```json
{
    "protocolVersion": 1,
    "requestId": "uuid",
    "captureId": "uuid",
    "status": "ok",
    "tab": {},
    "viewport": {},
    "element": {},
    "page": {}
}
```

Both the Python application and extension must validate it.

Fix the current mismatch where the resolver expects a success status that the
extension does not send.

## Required browser context

Return:

```text
tab ID
page URL
page title
route
browser zoom
devicePixelRatio
viewport size
visualViewport values
scroll position
element bounds
element tag
visible text
accessible name
role
CSS selector
stable element fingerprint
parent summary
sibling summaries
relevant computed styles
selected text
shadow DOM path
iframe information
framework component information
```

## Selector generation

Use:

```text
data-arrow-id
data-testid
stable id
aria-label
role and accessible name
stable parent-child relationship
```

Use `CSS.escape()`.

Do not create selectors from unescaped utility classes.

Do not rely entirely on `nth-of-type`.

## Shadow DOM

Use `event.composedPath()`.

Store the shadow-root traversal path.

## Iframes

Detect when the element is inside an iframe.

Return:

- frame URL,
- frame bounds,
- whether the extension has permission,
- whether exact resolution succeeded.

Do not silently pretend iframe resolution succeeded when it did not.

## React and framework context

Collect framework information when available, but treat private React Fiber
properties as optional hints.

Do not rely on them as the only source.

## Tests

Add extension tests for:

- normal button,
- nested elements,
- dynamically generated classes,
- shadow DOM,
- iframe,
- browser zoom,
- scrolling,
- element removal during capture,
- multiple matching selectors.

## Completion criteria

The browser adapter reliably identifies both source and destination on a
webpage.

---

# Phase 7 — Source-code mapping

## Goal

Map visual webpage elements to likely repository files and components.

## Mapping priority

Attempt mapping in this order:

1. `data-arrow-id`
2. development instrumentation
3. source-map information
4. framework component metadata
5. route information
6. repository search
7. visible text
8. selector and structural heuristics

## Optional development helper

Provide an optional package or plugin that helps developers add:

```jsx
data-arrow-id="pricing-primary-cta"
```

Do not require users to manually instrument every element.

## Source mapping result

Return:

```json
{
    "component": "PricingCTA",
    "sourceFile": "src/components/pricing/PricingCTA.tsx",
    "sourceLine": 47,
    "confidence": 0.86,
    "evidence": [
        "Component development metadata",
        "Text match",
        "Route match"
    ]
}
```

If a mapping is uncertain, return candidates:

```json
{
    "candidates": [
        {
            "sourceFile": "...",
            "confidence": 0.62
        }
    ]
}
```

Never fabricate a file or line.

## Repository context

Collect:

```text
repository root
current branch
current commit
dirty state
framework
package manager
development server URL
active route
```

## Completion criteria

The coding agent can understand which project and likely component the
annotation refers to.

---

# Phase 8 — Native Windows application context

## Goal

Provide useful context when the target is not a webpage.

## Windows UI Automation

For the selected source and destination, collect:

```text
process name
window title
control type
name
automation ID
class name
bounding rectangle
parent hierarchy
enabled state
focus state
accessibility properties
```

Resolve the element at the exact source or destination point.

## OCR fallback

Use OCR only when UI Automation fails.

OCR results must include:

```text
text
bounding rectangle
confidence
monitor
coordinate space
```

Do not apply OCR coordinates from one monitor to another.

Return multiple candidates when the result is ambiguous.

Do not automatically click or type into low-confidence targets.

## Completion criteria

Arrow can provide structured context for native Windows interfaces even when DOM
information is unavailable.

---

# Phase 9 — Spatial intent compiler

## Goal

Convert the user’s instruction and spatial annotations into a precise software
change request.

## Input

The compiler receives:

- raw screenshot,
- annotated screenshot,
- source crop,
- destination crop,
- annotations,
- source context,
- destination context,
- browser or native application data,
- repository data,
- user transcript,
- typed corrections.

## Supported intents

```text
move_element
resize_element
restyle_element
replace_content
remove_element
add_element
align_elements
change_spacing
change_responsive_behavior
fix_interaction
fix_visual_bug
inspect_or_explain
unknown
```

## Move relationships

```text
before
after
inside
above
below
left_of
right_of
align_start
align_center
align_end
replace
approximate_visual_position
unknown
```

## Structured output

Create a strict schema containing:

```text
schema version
capture ID
project
application mode
raw user request
normalized intent
summary
source
destination
requested changes
responsive expectations
constraints
acceptance criteria
likely files
confidence
evidence
inferences
ambiguities
clarification requirement
assets
```

## Important behavior

- Structured metadata has priority over visual guessing.
- The screenshot helps understand layout and visual relationships.
- Do not convert screenshot pixels directly into hardcoded CSS positioning.
- Prefer normal layout flow.
- Avoid unnecessary absolute positioning.
- Preserve responsive behavior unless the user explicitly requests otherwise.
- Use existing design tokens where possible.
- Mark every inference.
- Do not invent missing facts.

## Preview before sending

Show the interpreted request in the notch.

Let the user edit:

- instruction,
- source,
- destination,
- operation,
- constraints,
- acceptance criteria.

## Completion criteria

The output is a valid, implementable and reviewable JSON change request.

---

# Phase 10 — Storage redesign

## Goal

Replace fragile JSON-per-capture storage with a dependable local database and
asset store.

## Use

- SQLite for structured records.
- Asset directory for images and larger files.
- Schema migrations.
- Foreign keys.
- Atomic transactions.

## Tables

Suggested entities:

```text
projects
capture_sessions
annotations
anchors
context_results
assets
provider_runs
status_history
settings
```

## Required behavior

- Atomic capture creation.
- Atomic deletion.
- Deleting a capture removes all associated assets.
- Failed asset deletion is logged and retried.
- No second-level timestamp IDs.
- Database schema is versioned.
- Corrupted records are reported.
- Errors are not silently ignored.
- Retention settings exist.
- Users can delete all capture data.
- Screenshots are local by default.

## Completion criteria

Restarting the application preserves valid captures without stale metadata or
orphaned files.

---

# Phase 11 — Notch UI rebuild

## Goal

Turn the notch into a real capture and agent-control interface.

Do not completely change the established visual direction unless necessary.

## Remove

- fake connected integrations,
- fake agent tasks,
- placeholder statuses,
- hardcoded activity.

## Display real status

```text
Browser extension
Arrow MCP server
Codex installation
Claude Code installation
Selected repository
Current branch
Development server
Active capture
Selected provider
```

## Capture preview card

Display:

- annotated screenshot,
- raw instruction,
- interpreted intent,
- source element,
- destination,
- confidence,
- detected repository,
- likely file,
- constraints,
- acceptance criteria,
- selected provider.

## Actions

Provide:

```text
Edit context
Undo annotation
Redo annotation
Retake screenshot
Send
Copy fallback
Cancel
Delete
Open project
```

## Provider selector

```text
Codex
Claude Code
Agentation
Copy only
```

## Run status

Show:

```text
Ready
Sending context
Agent reading request
Editing files
Running tests
Waiting for permission
Completed
Failed
Cancelled
```

## Completion criteria

Every status visible in the notch is backed by real application state.

---

# Phase 12 — MCP integration

## Goal

Allow Codex and Claude Code to retrieve Arrow context without copying.

Implement Arrow as a local MCP server.

## Read-only tools

```text
arrow_get_latest_change_request
arrow_get_change_request
arrow_list_change_requests
arrow_get_capture_metadata
arrow_get_project_context
arrow_get_source_context
arrow_get_destination_context
```

## Resources

Expose screenshot assets as MCP resources:

```text
arrow://captures/{capture_id}/raw
arrow://captures/{capture_id}/annotated
arrow://captures/{capture_id}/context-crop
arrow://captures/{capture_id}/source-crop
arrow://captures/{capture_id}/destination-crop
```

## Controlled mutation tools

```text
arrow_mark_started
arrow_mark_completed
arrow_mark_failed
arrow_add_agent_note
```

Mutation tools should not directly execute arbitrary operating-system actions.

## Intended workflow

1. User creates a request in Arrow.

2. User opens Codex or Claude Code.

3. User says:

   “Implement the latest Arrow request.”

4. The coding agent calls the MCP server.

5. It receives the structured request and screenshots.

6. It edits the selected repository.

7. It reports status back through MCP.

8. Arrow displays completion.

## Documentation

Add:

```text
docs/codex-mcp-setup.md
docs/claude-mcp-setup.md
```

Provide project-level and global setup instructions.

## Completion criteria

Both Codex and Claude Code can retrieve the latest Arrow request without manual
copy-paste.

---

# Phase 13 — Direct Codex and Claude adapters

## Goal

Add optional one-click execution from the notch.

MCP remains the standard integration. Direct execution is an additional
convenience.

## Provider interface

Create a shared interface:

```text
detect()
validate()
start_run()
stream_events()
cancel_run()
get_status()
```

## Codex adapter

- Detect the installed Codex CLI.
- Run only inside the selected repository.
- Pass the structured request.
- Provide the annotated screenshot and supporting assets.
- Use structured or streamed output when supported.
- Stream progress to the notch.
- Allow cancellation.
- Do not store subscription authentication tokens.
- Do not execute outside the selected repository without confirmation.

## Claude adapter

- Prefer the Claude Agent SDK for a programmatic integration.
- Provide a Claude Code CLI fallback.
- Run only inside the selected repository.
- Pass the structured request and screenshot assets.
- Stream status and results.
- Respect permission modes.
- Allow cancellation.
- Do not extract or store user authentication tokens.

## Provider safety

Require confirmation before:

- deleting files,
- running destructive commands,
- modifying files outside the repository,
- installing system-wide packages,
- committing changes,
- pushing changes,
- accessing unrelated directories.

## Completion criteria

A user can select a provider, press Send, and observe a real coding-agent run.

---

# Phase 14 — Security hardening

## Goal

Remove unsafe local automation and protect local context.

## Remove or redesign

Review all endpoints capable of:

- launching applications,
- clicking,
- typing,
- sending hotkeys,
- reading arbitrary files,
- executing shell commands,
- serving arbitrary local paths.

Remove `shell=True`.

Do not expose general-purpose command execution.

## Authentication

Use:

- localhost-only binding,
- random per-install token,
- bearer authentication,
- origin validation where applicable,
- request-size limits,
- strict input validation,
- rate limits for sensitive actions.

## Capability model

Separate:

```text
read screenshot
read capture context
read repository context
run provider
control native application
execute command
modify files
```

Sensitive capabilities must be disabled by default.

## User confirmation

Require explicit confirmation before:

- operating-system interaction,
- command execution,
- application launching,
- destructive file changes,
- external network actions,
- sending messages,
- committing or pushing code.

## Privacy

- Screenshots remain local by default.
- No screenshot telemetry.
- Add retention controls.
- Add deletion controls.
- Add optional region redaction.
- Avoid collecting unrelated text from the screen.
- Log which provider received which assets.

## Completion criteria

No unauthenticated endpoint can execute operating-system actions.

No user-provided string is passed into a shell.

---

# Phase 15 — Testing and reliability

## Goal

Create an automated test suite covering the critical product promise.

## Unit tests

Add tests for:

1. capture session transitions,
2. stale asynchronous events,
3. multi-stroke annotation persistence,
4. source and destination selection,
5. undo and redo,
6. off-screen annotation rendering,
7. context crops,
8. negative monitor coordinates,
9. mixed-DPI conversion,
10. browser protocol validation,
11. DOM selector generation,
12. shadow DOM,
13. iframe handling,
14. UI Automation context,
15. OCR fallback,
16. change-request validation,
17. database migrations,
18. asset deletion,
19. provider cancellation,
20. authentication,
21. shell-injection attempts,
22. malformed screenshot payloads,
23. missing browser extension,
24. missing coding provider,
25. duplicate IDs.

## Integration tests

Create integration tests for:

- desktop capture,
- browser capture,
- source and destination resolution,
- storage and restoration,
- MCP request retrieval,
- provider run state.

## End-to-end webpage test

Use a small React or Next.js test application.

Test:

1. Open the test webpage.

2. Activate Arrow.

3. Select a button.

4. Select a destination.

5. Enter:

   “Move this button here and make it slightly wider.”

6. Verify raw screenshot.

7. Verify annotated screenshot.

8. Verify source DOM information.

9. Verify destination information.

10. Verify change-request JSON.

11. Retrieve it through MCP.

12. Confirm the coding agent receives the correct repository context.

## Display configuration tests

Test:

```text
100% scaling
125% scaling
150% scaling
browser on primary monitor
browser on secondary monitor
secondary monitor left of primary
secondary monitor above primary
```

## Completion criteria

Core CI tests pass consistently.

No critical workflow relies only on manual testing.

---

# Phase 16 — Packaging and onboarding

## Goal

Make Arrow installable and understandable by another user.

## Windows application

Create a repeatable build and installer process.

Include:

- application binary,
- required runtime dependencies,
- browser-extension installation instructions,
- hotkey setup,
- provider detection,
- repository selection,
- MCP configuration assistant.

## First-run onboarding

Guide the user through:

1. Select repository.
2. Install or connect browser extension.
3. Test screenshot permission.
4. Test annotation.
5. Detect Codex.
6. Detect Claude Code.
7. Configure MCP.
8. Create a sample Arrow request.
9. Send or retrieve the sample request.

## Troubleshooting

Document:

- overlay not appearing,
- browser extension disconnected,
- wrong monitor capture,
- DPI mismatch,
- microphone unavailable,
- Codex not detected,
- Claude Code not detected,
- MCP server unavailable,
- permission failures,
- stale or incorrect source mapping.

## Completion criteria

A new user can install the application and complete a sample workflow without
editing source code.

---

# Final end-to-end definition of done

The project is only considered complete when the following workflow passes:

1. Start Arrow.

2. Select a local React or Next.js repository.

3. Open the application webpage in Chrome.

4. Confirm that the browser extension is connected.

5. Activate Arrow.

6. Select a visible button as the source.

7. Select a new location as the destination.

8. Draw an additional highlight around a nearby container.

9. Type or say:

   “Move this button here, make it slightly wider, and preserve the mobile
   layout.”

10. Confirm the notch displays:

    - annotated screenshot,
    - source marker,
    - destination marker,
    - connecting arrow,
    - instruction,
    - source DOM context,
    - destination context,
    - repository,
    - likely component,
    - confidence,
    - acceptance criteria.

11. Confirm that `raw.png` does not contain Arrow annotations.

12. Confirm that `annotated.png` does contain all annotations.

13. Confirm that the change request is stored in SQLite.

14. Confirm that Codex or Claude Code can retrieve it through MCP.

15. Confirm that the agent edits the selected repository.

16. Confirm that Arrow displays the agent run status.

17. Confirm that the workflow can be cancelled.

18. Confirm that no unauthenticated operating-system mutation endpoint is
    available.

19. Confirm that the workflow works at 100%, 125% and 150% scaling.

20. Confirm that the workflow works when Chrome is on a secondary monitor.

---

# How to execute this plan

Work on only one phase at a time.

At the beginning of each phase, report:

```text
Phase
Goal
Files expected to change
Risks
Tests to add
```

At the end of each phase, report:

```text
Completed work
Files changed
Tests added
Tests passed
Known limitations
Manual verification steps
Next phase
```

Do not proceed when critical tests fail.

Do not replace real functionality with mocks.

Do not spend time polishing animations before the spatial context pipeline,
browser protocol, storage and MCP handoff are dependable.

Begin with Phase 0.
