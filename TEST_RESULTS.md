# Test Results

Date: 2026-10-13
Branch: `fix/arrow-annotate-prelaunch`

## Python suite

```
389 passed, 1 warning in 28.57s
```

- The single warning is a pre-existing `mss.mss` deprecation in
  `arrow/server/server.py` and does not affect results.
- Baseline at the start of this pass (`2859dbc`): 345 passed.
- After merging `origin/fix/arrow-annotate-prelaunch` (`066db08`): 349 passed
  (the 4 restored `test_notch_animation.py` tests).
- This pass adds 40 tests:
  - `test_config_propagation.py` (6) — `ARROW_HOME` reaches the database and
    both asset roots; legacy checkout data migrates exactly once and never
    overwrites live data.
  - `test_threading.py` (+1) — a UI callback queued while capture A was current
    is re-checked at delivery, after B supersedes it.
  - `test_point_mode.py` (19) — point-target resolution and geometry,
    including negative monitor origins and honest fallback labelling.
  - `test_point_overlay.py` (9) — Point Mode gesture, no shared stroke state,
    and cancel-instead-of-full-screen on an empty finish.
  - `test_notch_modes.py` (5) — notch → app capture-mode wiring.

### Verified red-capable

Each new fix was confirmed to fail before the change and pass after. The
delivery-time race test was checked by stashing only `arrow/core/threads.py`
and re-running it:

```
=== with fix (expect PASS) ===        1 passed
=== verify it actually goes RED without the fix ===   1 failed
```

## Browser extension (Node)

```
node --test browser_extension/tests/background.test.mjs
tests 14 | pass 14 | fail 0
```

## Static checks

- `ruff check .` → All checks passed
- `mypy arrow` → Success: no issues found in 50 source files
- `node scripts/verify-extension.mjs` → extension verification passed
- `node scripts/verify-docs.mjs` → docs verification passed
- `node scripts/verify-ci.mjs` → ci verification passed

## Windows launch smoke test

```
Start-Process .venv\Scripts\python.exe main.py     # ran 12s, then stopped
```

Observed on stderr, no tracebacks:

```
[INFO] server listening on 127.0.0.1:5002
[INFO] [WSBridge] listening on ws://127.0.0.1:5002
[INFO] [AgentServer] listening on http://127.0.0.1:5001
[INFO] 127.0.0.1 - - "GET /status HTTP/1.1" 200 -   (repeats every 5s)
```

The `ARROW_HOME` migration was confirmed on real data: the repo-local
`arrow.db` was gone afterwards and `~/.arrow/arrow.db` existed at 90,112 bytes.

## NOT verified — interactive GUI

No interactive desktop session was available to the agent, so **none** of the
following were exercised. They are unverified, not passing:

- Clicking an element in Chrome / a native app and seeing it in the notch.
- Actual UIA/OCR resolution quality against a live desktop.
- Multi-monitor physical setup with a left/above monitor (geometry is covered
  by unit tests only).
- Voice capture, notch animation smoothness, DPI 125/150/200% rendering.

## Earlier results

- Baseline before this pass (after fast-forward to `70b5d8c`): 314 passed.
- Suites added since then include: overlay math (P0-1 negative coords),
  database asset handling (P0-3), extension/config/agentation unit tests
  (P0-5), and `test_overlay_cancel.py` (P0-6 Escape/finish semantics,
  7 tests), plus `test_context_file.py` (4 tests).

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
