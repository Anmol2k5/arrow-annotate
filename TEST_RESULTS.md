# Test Results

Date: 2026-10-10
Branch: `fix/arrow-annotate-prelaunch`

## Python suite

```
317 passed, 1 warning in 21.56s
```

- The single warning is a pre-existing `mss.mss` deprecation in
  `arrow/server/server.py` and does not affect results.
- Baseline before this pass (after fast-forward to `70b5d8c`): 314 passed.
- New/updated tests in this pass: `test_trail_fade` (layer ordering,
  continuous band painting along a curve), `test_agentation` (offline
  completes session; `complete_if_active` ignores superseded sessions).

## Static checks

```
ruff check .        → All checks passed!
mypy arrow          → Success: no issues found in 49 source files
```

## Browser extension

```
node scripts/verify-extension.mjs → extension verification passed
```

Includes manifest/permission assertions (no `<all_urls>`, loopback-only
hosts, `activeTab`+`storage` only) and 9 vm-sandboxed background
state-machine tests.

## Gate ledger

```
GATES.md: 17 met / 1 unmet
  met:   G0–G16
  unmet: G17 manual GUI smoke run → requires a human on a real desktop
```

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
