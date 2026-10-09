# Implementation Report

Branch: `fix/arrow-annotate-prelaunch` (from `main` @ `2f22a0b`).

Starting point: the repo had a strong audit (`AUDIT_REPORT.md`) but the
fixes it recommended were only partially applied. This report lists what was
implemented, gate by gate. Current status: **15 of 18 gates met** (see
`GATES.md`).

## Phase 0 — Baseline

- Fresh venv, verified pytest/ruff/mypy baseline.
- Fixed pre-existing breakage: stray `/` in `arrow/core/logging.py`,
  `Image.Resampling.LANCZOS` in `arrow/capture/screenshot_service.py`.
- Wrote `docs/current-architecture.md` from the code as-built.

## Phase 1 — Security

- **Config single source of truth** (`arrow/core/config.py`): defaults →
  `.env` → env; non-loopback hosts rejected unless
  `ARROW_ALLOW_NON_LOOPBACK=1`. (G12)
- **Scoped share tokens** (`arrow/server/security.py`): HMAC
  `<payload>.<mac>`, 15-minute TTL, single-file scope; screenshot fetch
  endpoints require a valid token instead of the master bearer. (G14)
- **Upload validation** (`arrow/server/screenshots.py`): size limits, path
  safety, collision-resistant filenames. (G6)
- **Browser extension hardening**: permissions cut from `<all_urls>` to
  `activeTab` + `storage` with loopback-only host permissions; honest popup
  state machine (not_configured → connecting → authenticating → connected /
  auth_failed / server_unavailable); capped exponential backoff with jitter;
  `bluelyToken` → `arrowToken` migration. (G4/G5)

## Phase 2 — Stability

- **Qt thread safety** (`arrow/core/threads.py`): `UiBridge.post` /
  `post_for(capture_id, …)` marshals worker callbacks to the main thread and
  discards stale callbacks for superseded captures. `arrow/app.py` never
  touches widgets from worker threads anymore. (G10)
- **Session wedging fixed**: `fail_if_active(capture_id, reason)` records an
  error on the right capture; screenshot failure and Agentation failure both
  degrade to `FAILED` + status message instead of wedging or crashing.
- **Voice input rewrite** (`arrow/ui/voice_input.py`): generation-based
  cancellation. A stopped/stale session can no longer clobber the next
  session's state (the old `finally: self._listening = False` race). Mic
  reassignment reuses the live mic thread instead of opening a second mic on
  Windows. Proven by tests that fail against the old implementation. (G9)
- **Notch status** (`arrow/ui/notch.py`): `set_status`/`update_status` drive
  a real visible status label. (G11)
- **Clean shutdown**: `aboutToQuit` unhooks hotkeys, stops timers/voice, and
  stops the server.

## Phase 3 — Agentation

- Session selection hardened (`pick_session_id`): skips malformed entries
  instead of trusting `sessions[0]["id"]`.
- Handoff extracted to `send_capture_annotation` (`arrow/providers/agentation.py`)
  with a clear contract: reuse first usable session, create when none,
  raise `AgentationError` on failure — callers degrade gracefully. (G13)
- Tests cover offline (real connection-refused), payload completeness, empty
  and malformed session lists, create-without-id rejection, and the full
  store → handoff path.

## Phase 4 — UI/UX

- Status messages now cover the whole capture lifecycle through the notch:
  `Screenshot failed`, `Capture failed` (pipeline), `Agentation sync
  failed`, and `Sent to Agentation` (auto-clears after 6s).
- Fixed a real hotkey bug: `is_annotating` was never reset after a
  successful selection, so the next hotkey press was swallowed (the toggle
  thought a capture was still active). It now returns to idle as soon as
  the selection is consumed.
- Voice `WaitTimeoutError` (no speech within 4s) is now benign: it stops
  the voice session quietly instead of surfacing as an error that cancelled
  the entire capture.

## Test & verification infrastructure

- `tests/` grew from the partial suite to **307 passing tests**; new suites:
  config, share tokens, crop geometry, screenshot upload, threading, voice,
  agentation, notch status, hotkey.
- `GATES.md`: 18 outcome-focused gates with machine-checkable oracles;
  unlazy gate ledger keeps them honest.
- `scripts/verify-extension.mjs`, `scripts/verify-docs.mjs`,
  `scripts/verify-ci.mjs`.
- `.github/workflows/ci.yml`: Windows runner, install → ruff → mypy →
  pytest → extension verification.

## Not done / open

- G15/G16 now met (docs + CI landed with this report set); G17 (manual GUI
  smoke run) needs a human on a real desktop session.
- Remaining UI polish items are listed in `plan.md` Phase 4.
