# Test Results

Date: 2026-10-08
Branch: `fix/arrow-annotate-prelaunch`

## Python suite

```
308 passed, 1 warning in 19.81s
```

- The single warning is pre-existing (pytest config deprecation) and does
  not affect results.
- New/major suites in this effort: `test_config`, `test_share_tokens`,
  `test_screenshot_upload`, `test_crop_geometry`, `test_threading`,
  `test_voice_input`, `test_agentation`, `test_notch_status`,
  `test_hotkey`.

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
