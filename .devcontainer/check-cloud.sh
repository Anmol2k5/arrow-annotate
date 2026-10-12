#!/usr/bin/env bash
# Static checks plus a limited, cross-platform pytest subset.
# Full Python + GUI acceptance remains in Windows Actions / native Windows.
set -euo pipefail

export QT_QPA_PLATFORM=offscreen
export ARROW_VOICE_TRANSCRIPTION=off

echo "[Arrow] Python compile checks"
python -m compileall -q arrow tests

echo "[Arrow] Ruff"
python -m ruff check .

echo "[Arrow] Mypy (project configuration may suppress some package errors)"
python -m mypy arrow

echo "[Arrow] Browser extension checks"
node scripts/verify-extension.mjs

echo "[Arrow] Documentation / CI checks"
node scripts/verify-docs.mjs
node scripts/verify-ci.mjs

echo "[Arrow] Limited platform-neutral Python tests"
python -m pytest -q tests/test_config.py tests/test_intent_compiler.py

echo "[Arrow] Cloud checks complete. The Windows GUI was NOT validated here."
