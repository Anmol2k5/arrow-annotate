# Implementation Report

Branch: `fix/arrow-annotate-prelaunch` (from `main` @ `2f22a0b`).

Starting point: the repo had a strong audit (`AUDIT_REPORT.md`) but the
fixes it recommended were only partially applied. This report lists what was
implemented, gate by gate. Current status: **18 of 19 gates met** (see
`GATES.md`); G17 (manual GUI run) needs a human on a real desktop.

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
  error on the right capture; screenshot failure degrades to `FAILED` +
  status message instead of wedging or crashing. Optional provider
  (Agentation) failure uses `complete_if_active` so a saved capture is
  never failed (see Phase 5).
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
  `Screenshot failed`, `Capture failed` (pipeline), `Agentation offline —
  capture saved` (amber; provider outage is not a local failure), and
  `Sent to Agentation` (auto-clears after 6s). Voice errors distinguish
  "wasn't understood" / "no microphone" / "service offline".
- Fixed a real hotkey bug: `is_annotating` was never reset after a
  successful selection, so the next hotkey press was swallowed (the toggle
  thought a capture was still active). It now returns to idle as soon as
  the selection is consumed.
- Voice `WaitTimeoutError` (no speech within 4s) is now benign: it stops
  the voice session quietly instead of surfacing as an error that cancelled
  the entire capture.

## Phase 5 — TipTour trail & overlay polish

Studied TipTour's `CursorStreakTrailView` / `buildContinuousSmoothTrailPath`
(`OverlayWindow.swift`) and `DetectionOverlayView.swift`, then adapted the
rendering approach to PyQt6 (`arrow/ui/overlay.py`):

- **Continuous band rendering**: densified Catmull-Rom trail sliced into
  ordered tail→head opacity bands; each band is one polyline with shared
  endpoints, stroked once per glow layer with flat caps — the Qt
  equivalent of TipTour's "one continuous path, trimmed into bands",
  eliminating round-cap bead junctions.
- **Three-layer glow** at the reference proportions: 54 px @ 0.11 halo,
  32 px @ 0.26 bloom, 18 px @ 0.72 core; palette `#4F8EF7` / `#E2F3FF`.
- Removed sparkle particles (they contradicted the "no glowing dots"
  highlighter aesthetic).
- **Overlay veil reduced** from alpha 215 to 32; removed the full-screen
  dot grid (thousands of `drawPoint` calls per frame). The desktop stays
  legible while drawing; the guide pill uses the electric-blue accent.
- Idle overlay skips 60 fps repaints when nothing is animating.
- Compact white-blue pointer head (18 px) with a soft blue halo.
- `SessionManager.complete_if_active`: an Agentation outage completes the
  session (capture already saved) instead of failing it; notch shows an
  amber offline status.
- Notch: offline status color, tooltips on copy/trash controls.

## Phase 6 — Priority Zero fixes (master directive)

- **P0-1 negative coordinates**: removed the `stroke_rect` clamp that
  mangled strokes on multi-monitor layouts with negative origins; tests in
  `tests/test_overlay_math.py`.
- **P0-2 voice privacy**: `ARROW_VOICE_TRANSCRIPTION={google,off}` validated
  in `arrow/core/config.py`; `VoiceInput.__init__(enabled)` gates listening;
  README/`.env.example` disclose that Google transcription is networked.
- **P0-3 asset deletion**: `CaptureRecord.assets` + `CaptureStore.add/delete`
  asset handling so deleting a capture deletes its files; tests in
  `tests/test_database.py`.
- **P0-4 extension permissions**: manifest 1.3.0 with on-demand injection
  (`scripting` + `activeTab`, per-site optional hosts + popup consent),
  honest popup state machine; `scripts/verify-extension.mjs` tightened.
- **P0-5 config propagation**: `env_value()`/`resolve_home()` helpers in
  `arrow/core/config.py` (real env wins over `.env`, `ARROW_HOME` honored);
  Agentation client, settings dir, capability manager, and `latest_dir()`
  all resolve through them; extension `sanitizeWsUrl()` rejects non-loopback
  or portless WS URLs; popup Bridge-URL field saves `{arrowToken,
  arrowWsUrl}` in one write. Tests: `test_config.py`, `test_agentation.py`,
  `test_settings.py`, `test_security.py`, `test_context_file.py`,
  background vm tests (14).
- **P0-6 session reliability/hotkeys**: `overlay.cancelled` signal;
  `hide_overlay`/`cancel_overlay` idempotence guards; Escape cancels without
  emitting a selection (never falls back to full-screen);
  `finish_annotation()` extracted (no-op when idle) and bound to a global
  `Ctrl+Shift+Enter` hotkey — registered outside the overlay's
  `keyPressEvent` so the two paths cannot double-fire; banner widened to
  780px with finish/cancel hints. Tests: `tests/test_overlay_cancel.py`
  (7). Architecture flowchart and README updated.

## Phase 7 — Typing hardening

- Removed the `pyproject.toml` mypy `[[tool.mypy.overrides]]` block that
  suppressed errors in `arrow.ui/server/context/providers`, then fixed all
  **46** surfaced errors across 8 files (Optional narrowing, `Any` imports
  for pywin32/runtime-only values, latent `None` guards in
  `source_mapper`/`highlight_resolver`/`orchestrator`, explicit
  `Optional[...]` annotations in `server.py`/`notch.py`). `pyqtProperty`
  keeps a targeted `# type: ignore[attr-defined]` because PyQt6 ships no
  type stubs for it.
- `mypy arrow` → `Success: no issues found in 49 source files` with no
  blanket suppressions. (G3)

## Test & verification infrastructure

- `tests/` grew to **345 passing tests**; new suites: config, share
  tokens, crop geometry, screenshot upload, threading, voice, agentation,
  notch status, hotkey, trail fade (band continuity, layer ordering),
  overlay cancel/finish semantics, context file mirroring, extension
  background state machine (14 vm tests).
- `GATES.md`: 19 outcome-focused gates with machine-checkable oracles
  (G0–G16 + G18 met with freshly re-verified evidence; G17 manual);
  unlazy gate ledger keeps them honest.
- `scripts/verify-extension.mjs`, `scripts/verify-docs.mjs`,
  `scripts/verify-ci.mjs`.
- `.github/workflows/ci.yml`: Windows runner, install → ruff → mypy →
  pytest → extension verification.

## Not done / open

- G17 (manual GUI smoke run) needs a human on a real desktop session;
  hotkeys, live mic, and the Chrome extension handshake are unit-tested but
  not exercised live by an agent.
- `AUDIT_REPORT.md` items deliberately left unchecked: project-scoped
  Agentation sessions (#42), hotkey-registration status surface (#43),
  server polling status (#44), `bluely://desktop` deep link (#53),
  responsive notch sizing (#56), voice per-error timeouts (#58), static
  bundle cache-busting (#60), REPL capture (#67), prompt-caching metrics
  (#68), token-ACL tests for `READ_REPO_CONTEXT` (#77), and the §8 status
  feedback full state machine / capture Retry action.
- Remaining UI polish items are listed in `plan.md` Phase 4.
