# Test Results

Date: 2026-10-13
Branch: `fix/arrow-annotate-prelaunch`

## Python suite

```
598 passed, 1 warning in 45.86s
```

- The single warning is a pre-existing `mss.mss` deprecation in
  `arrow/server/server.py` and does not affect results.
- Start of this phase (`a82b97d`): 389 passed.
- Added in the previous phase: 100 tests. Added in this phase: **109**
  (task shelf 33, agent actions 41, agent pointer integration 35).

### Suites added

| File | Tests | Covers |
|---|---|---|
| `test_task_shelf.py` | 33 | Ordering, edit, removal, honest labels, fits-in-notch |
| `test_agent_actions.py` | 41 | Allow/Deny, expiry, revalidation, injection, races |
| `test_agent_pointer_integration.py` | 35 | HTTP auth/capability, approval handshake, Qt bridge |
| `test_point_lifecycle.py` | 19 | Overlay teardown ordering, thread safety, state reconciliation |
| `test_tasks.py` | 30 | TaskBundle persistence, ordering, edit, export, migration |
| `test_point_task_integration.py` | 7 | Real point captures landing in one task, restart survival |
| `test_mcp_tasks.py` | 21 | Task-aware MCP, real image content, honest status |
| `test_agent_pointer.py` | 22 | Spring convergence, bounded timestep, stability |

### Bugs found by these tests and fixed

- `request()` cached `awaiting_approval` as a terminal outcome, so `status()`
  could never report an expiry.
- `decide()` pruned before lookup, making an expired approval
  indistinguishable from one that never existed.
- `decide()` rebuilt the request *from* the approval, so the `target_moved`
  check was unreachable dead code. An `observe()` hook now re-resolves the live
  target and refuses when it cannot be identified.
- The MCP preview tool could not read a capture's resolved bounds: the target
  lives in the capture's context, not the change-request row.
- `/agent/preview` read `label` while the MCP schema documented `reason`.
- Two layout defects found only by looking at a real screen (see below).

### Verified red-capable

Each fix was confirmed to fail before the change:

- **Point capture race** — moving the worker dispatch ahead of the overlay
  teardown turned 4 tests red, including
  `test_raw_capture_begins_only_after_overlay_teardown`.
- **Callback race** — stashing only `arrow/core/threads.py` turned the
  delivery-time test red.
- **ARROW_HOME** — all 3 propagation tests failed before the resolvers existed.

## Integration verification

### Real, verified

- **App launch** — `main.py` runs, binds `127.0.0.1:5001` + WS `5002`, polls
  `/status`, no tracebacks. Migration 3 applied to the real database.
- **ARROW_HOME migration** — the repo-local `arrow.db` was moved to
  `~/.arrow/arrow.db` (90,112 bytes) with data intact.
- **MCP over real stdio** — a separate `python -m arrow.mcp.server` process
  returned a task manifest and an image content block decoding to a valid PNG
  (signature `\x89PNG` verified).
- **Real Claude Code client** — Claude Code **2.1.205** was installed and
  `claude mcp add arrow` + `claude mcp list` reported
  `arrow: ... - ✔ Connected`. Config went to `~/.claude.json`; the repo stayed
  clean.

### Mocked / unit-tested only

- Capture pipeline, UIA/OCR resolution, screenshot acquisition — all use
  fakes. No automated test touches a real screen.
- Codex integration — **Codex is not installed on this machine.** Its MCP
  setup doc is therefore unverified.

### Real Windows desktop (1920x1080, 125% scaling)

An interactive session was available, so the app was launched and the screen
read back programmatically. Verified:

| Check | Evidence |
|---|---|
| Notch renders | Idle capsule visible top-centre, occluding VS Code behind it |
| Notch stays above other apps | z-index 2 of 23 top-level visible windows |
| Hover expansion | Window rect `(909,10,100,40)` → `(484,10,950,759)`, i.e. 760x560 logical x 1.25 |
| Hover collapse | Returns to the idle rect |
| Task shelf renders | Selector, title, instruction, footer all visible |
| 125% DPI handling | Window sizes are exactly logical x 1.25 |
| Packaged exe | `dist/ArrowAnnotate/ArrowAnnotate.exe` launched and stayed running |

**Two real defects were found only this way**, because Qt silently clips an
oversized layout instead of raising: the task shelf's footer was cut off at
the notch's bottom edge, and the task row overflowed the right edge,
truncating `+ Task`. Both fixed, both now covered by regression tests.

Note on method: two earlier "failures" were my own DPI mistakes, not app bugs.
A DPI-unaware capture script reports virtualised coordinates, so the notch
appeared to be missing. Setting `SetProcessDpiAwarenessContext(-4)` before
sampling showed it rendering correctly the whole time.

### Still NOT verified

- Point Mode's click→capture round trip against a real app.
- A task shelf populated with captures, on screen.
- The agent pointer watched moving; the Allow/Deny panel displayed.
- The global hotkey — synthetic key events did not trigger it in this
  environment. Cause unknown; needs a human press.
- Live UIA/OCR resolution quality.
- Multi-monitor (only one display present); DPI 100/150/200%.
- Voice recognition; notch animation *feel*.

## Static checks

```
ruff check .      -> All checks passed
mypy arrow        -> Success: no issues found in 54 source files
pip check         -> No broken requirements found
verify-extension  -> extension verification passed
verify-docs       -> docs verification passed
verify-ci         -> ci verification passed
node --test browser_extension/tests/background.test.mjs -> 14 pass / 0 fail
```

## Earlier results

- Baseline before the previous pass (`70b5d8c`): 314 passed.
- Phase 0/1 pass (`a82b97d`): 389 passed.

## Static checks

```
ruff check .        → All checks passed!
mypy arrow          → Success: no issues found in 49 source files
```

- mypy runs with **no suppressions**: the `[[tool.mypy.overrides]]`
  `ignore_errors` block for `arrow.ui/server/context/providers` was removed
  from `pyproject.toml` and all 46 previously hidden errors were fixed.
- mypy prints `annotation-unchecked` notes (informational; exit 0). Running
  with `--check-untyped-defs` would surface ~20 further strictness findings,
  mostly in `notch.py`; this is outside the current gate scope.

## Browser extension

```
node scripts/verify-extension.mjs → extension verification passed
```

Includes manifest/permission assertions (no `<all_urls>`, loopback-only
hosts, `activeTab`+`storage` only) and 14 vm-sandboxed background
state-machine tests (`node --test` → 14 pass / 0 fail), including the
`sanitizeWsUrl` loopback/port validation tests added for P0-5.

## Gate ledger

```
GATES.md: 19 gates
  met:   G0–G16 + G18 (all re-verified 2026-10-10 with fresh evidence)
  unmet: G17 manual GUI smoke run → requires a human on a real desktop
```

- G18 (new): Escape cancels an active capture without emitting a
  selection; a duplicate finish trigger emits `selection_complete` exactly
  once.

## Manual Windows validation (required, not automated)

Not executed in this environment (headless CI-style run). Requires a human
on an interactive Windows desktop:

- Scenario A/B: trail smoothness, fade after release (visual).
- Scenario C: focus outline alignment over real UI elements.
- Scenario D: screenshot readback has no overlay veil (overlay is hidden
  before capture; verified by code path, not pixels).
- Scenario E: notch expand/collapse feel.
- Scenario F: live microphone voice path (fakes cover logic only).
- Scenario G: Agentation stopped → amber "offline — capture saved" status.
- Hotkeys: Ctrl+Shift+Space start, Ctrl+Shift+Enter finish, Escape cancel
  (implemented + unit-tested; not exercised live).

## Regression proof (voice race)

The three generation-cancellation tests in `tests/test_voice_input.py`
(stale finally clobber, stop invalidates in-flight, mic reassignment)
were run against the pre-fix implementation: **6 of 9 voice tests failed**,
including the clobber race. Against the new implementation: **all pass**.

## Reproduce

```bash
python -m pytest -q
python -m ruff check .
python -m mypy arrow
node scripts/verify-extension.mjs
node scripts/verify-docs.mjs
node scripts/verify-ci.mjs
```
