# Test Results

Date: 2026-10-10
Branch: `fix/arrow-annotate-prelaunch`

## Python suite

```
345 passed, 1 warning in 24.95s
```

- The single warning is a pre-existing `mss.mss` deprecation in
  `arrow/server/server.py` and does not affect results.
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
