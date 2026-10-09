# Audit Report — Arrow Annotate

**Audited:** 2026-10-09  
**Repository:** https://github.com/Anmol2k5/arrow-annotate  
**Branch:** `main` (GitHub tree `9c4166ca718895a867a51d9aedfc44e7b086bbef`)  
**Evidence standard:** Source findings link to exact file/line ranges. **No claim of successful installation, test execution, GUI launch, or lint run.**

## 1. Summary

**Decision: NOT production-ready. Demo readiness is unverified on Windows.** This is a Windows-only Python/PyQt6 desktop overlay with Flask HTTP API, local WebSocket bridge, browser extension (Manifest V3), screenshot/UIA/OCR capture, voice recognition, local storage, and Agentation/MCP integrations. Entrypoint: `main.py:1-16` → `arrow/app.py:48-54` → `arrow/server/server.py:806-854`, `arrow/ui/notch.py`, and capture/orchestration modules.

GitHub's recursively listed tree contains modules under `arrow/capture`, `context`, `core`, `intent`, `mcp`, `providers`, `server`, `storage`, and `ui`; a `browser_extension/` and 19 `tests/test_*.py` files. Dependency declarations are in `pyproject.toml:1-26` and `requirements.txt:1-16`. Runtime dependencies match across these two lists; development tools (`ruff`, `mypy`, `pytest`) are only in requirements. No complete import-to-dependency resolution was executed; avoid interpreting this as verification that all imports resolve.

**Principal risks:** unauthenticated read/capture HTTP surface; unimplemented UI status handlers; voice capture cancellation race; 127.0.0.1 ports hardwired despite config examples; possible screenshot-cropping coordinate bug; no demonstrated Windows integration validation. Do not assign a numeric completion percentage on incomplete runtime evidence.

## 2. Build/Run/Test Results

| Check | Result | Exact observed evidence |
| --- | --- | --- |
| Fetch repository metadata/tree | PASS | GitHub connector returned default branch `main` and complete recursive file tree (`truncated: false`). |
| Local clone | **BLOCKED** | `git clone --depth 1 https://github.com/Anmol2k5/arrow-annotate.git audit-repo` → `fatal: unable to access 'https://github.com/Anmol2k5/arrow-annotate.git/': Could not resolve host: github.com` (exit code 128). |
| Dependency installation | **NOT RUN** | No local repository checkout or Windows runner; cannot assert pip install succeeded. |
| GUI startup | **NOT RUN** | `main.py:8-12` explicitly terminates on non-Windows; this environment is not a Windows GUI session. |
| Python tests | **NOT RUN** | Tests exist, e.g. `tests/test_security.py`, `tests/test_orchestrator.py`; test pass/fail unverified. |
| Ruff/mypy | **NOT RUN** | Configured in `pyproject.toml:28-49`, but code/dependencies could not be installed locally. |
| Browser extension in Chrome | **NOT RUN** | Requires a live Chrome instance and local WS bridge. |
| GitHub source inspection | PASS | Exact file contents retrieved via authenticated GitHub connector. |

**Required Windows verification:** `py -3.12 -m venv .venv`; `.venv\Scripts\python -m pip install -r requirements.txt`; `.venv\Scripts\python -m pytest -q`; `.venv\Scripts\python -m ruff check .`; `.venv\Scripts\python -m mypy arrow`; `.venv\Scripts\python main.py`. Test native capture, hotkeys, selection, microphone, browser token handshake, HTTP access control, and Agentation unavailable/available states. Record exit codes and logs.

## 3. Critical Issues (breaks core functionality or privacy boundary)

- [ ] **High — `arrow/server/server.py:251-314,617-745`; `docs/security-audit.md:67-72` — screenshot and read-context endpoints do not authenticate the caller.** A local caller can fetch screenshots and potentially invoke on-demand screen/DOM inspection when defaults permit. The docs explicitly acknowledge this. **Fix:** bearer auth and explicit client capabilities for all private screen/content endpoints; handle Agentation access using scoped short-lived signed URLs rather than public local URLs. Test requests without token return 401, and hostile origins never receive contents. This is a production blocker for a product handling screen contents.
- [ ] **High — `arrow/ui/voice_input.py:24-35,38-79` — stop is not a true cancellation mechanism.** `stop_listening()` flips a boolean but the worker remains inside microphone acquisition / Google recognition until a timeout or return. Starting another session while the prior thread is still running allows the old worker's `finally` to set `_listening=False` after a newer capture has started. **Fix:** generation token/cancellation event protected by lock; only the current generation may clear state or emit `listening_changed(False)`. Add back-to-back start/stop race tests.
- [ ] **High — `arrow/app.py:101-151` — screenshot acquisition and annotation callbacks are not wrapped in a complete error boundary.** `ScreenshotService().capture_raw(overlay)` occurs before the worker's `try` block. An exception here can interrupt the UI callback and leave the session stuck. **Fix:** surround capture + mapping with try/except/finally; signal failure to notch; always release overlay and session states, with structured error reporting.
- [ ] **Potential high — `arrow/server/server.py:716-724` — crop uses absolute desktop `x,y` on an MSS image whose coordinate origin may be the acquired monitor/region.** `pil_full.crop((x,y,x+w,y+h))` is only valid when `full` starts at desktop (0,0). **Fix:** normalize crop by actual `monitor['left']`/`monitor['top']` or acquire region directly; test negative-origin multi-monitor and nonzero-origin displays. **Verification required:** inspect `find_mss_monitor` return for this call before classifying as a confirmed bug.

## 4. Broken / Non-Working Features

- [ ] **Confirmed unfinished — `arrow/ui/notch.py:1267-1272`:** `set_status` and `update_status` are `pass`. Connect these to visible status model/label or remove unused public handlers and callers. Verify whether they are referenced before assigning user-visible impact.
- [ ] **High — `arrow/app.py:175-203`:** failure transitions log errors but do not visibly render an error in the notch; add a visible failed state, retry and recovery.
- [ ] **Medium — `arrow/app.py:205-244`:** Agentation handoff assumes first available session and always sends there; potentially mixes projects/sessions. Choose by repository/current capture, or create a dedicated session and persist the ID.
- [ ] **Medium — `arrow/app.py:248-257`:** global hotkey failure only logs a warning. Add visible hotkey-registration status and alternate trigger.
- [ ] **Medium — `arrow/app.py:260-272`:** server polling swallows every exception and never updates visible connection state. Report online/offline in UI and a retry/backoff state.
- [ ] **Medium — `browser_extension/background.js:19-104`:** WS reconnection uses a fixed 3000 ms loop; no capped exponential backoff, jitter, or explicit stop during browser shutdown. Add backoff and on-screen connection explanation.

## 5. Hardcoded Values & Mock Data

- [ ] `arrow/app.py:48-55` — app name `Bluely Agent` and Flask bind `127.0.0.1:5001`. Rename to Arrow Annotate and source bind/port from validated configuration.
- [ ] `arrow/server/server.py:502-503,806` — default WS port `5002` and HTTP port `5001`. Centralize config and document override; currently `.env.example:1-5` advertises `FLASK_PORT`/`WS_PORT` but bootstrap doesn't load/use them.
- [ ] `browser_extension/background.js:22` — `ws://127.0.0.1:5002` hardcoded. Store validated localhost port in extension settings or detect via native messaging/pairing.
- [ ] `arrow/providers/agentation.py:8-18` — Agentation base `http://127.0.0.1:4747`. Make a configurable integration endpoint with health check and explanatory disconnected state; 127.0.0.1 is appropriate as a secure default, but the fixed port is fragile.
- [ ] `arrow/app.py:215-230` — `bluely://desktop`, `desktop_screen`, `desktop` and first session assignment are integration-specific defaults; rename and scope by project/session.
- [ ] `arrow/server/server.py:239` — API version `1.0.0` differs from package version `0.1.0` in `pyproject.toml:3`. Derive from package metadata.
- [ ] `arrow/server/server.py:298-299,714-715` — timestamp filenames only have second precision. Concurrent captures can overwrite files. Use UUID or microseconds + random suffix, atomic exclusive create, tests for parallel calls.
- [ ] `arrow/ui/notch.py:367,384,390` — fixed 320×400 parent and 320×160 image region. Adapt width based on available screen geometry and DPI; use aspect-ratio-preserving scale.
- [ ] `arrow/ui/notch.py:1250` — 1500 ms auto-collapse; could hide result before user understands state. Make optional/user-adjustable, default 2500–3000 ms.
- [ ] `arrow/ui/voice_input.py:50` — 4-second start timeout and 8-second phrase limit; configurable, with active state and cancellation.
- [ ] `browser_extension/manifest.json:3-12` — stale Bluely branding plus broad `<all_urls>` match.
- [ ] `arrow/server/security.py:17-18` — 8 MiB request cap and localhost allow-list are security defaults, not secrets; retain but document config rationale.

The entries above are verified instances from inspected files, **not a guaranteed exhaustive grep output**. A complete local regex sweep across every tracked file remains outstanding.

## 6. TODO/FIXME Inventory

- [ ] `arrow/ui/notch.py:1267-1272` — two executable `pass` stubs (not TODO comments).
- [ ] `arrow/providers/agentation.py:11-12` — `pass` inside exception class is **normal Python**, not an unfinished implementation.
- [ ] `arrow/server/server.py:547,582,586` — bare `pass` inside exception/recovery paths; inspect context and log appropriately where recovery failure matters.
- [ ] No verified claim about repository-wide TODO/FIXME/HACK/XXX count: full grep not executable locally in this session.

## 7. Security & Config Issues

- [ ] **High — `arrow/server/server.py:251-314,617-745`** — screen contents and browser context available without authenticated read access. Require tokens and scoped capabilities; add negative tests.
- [ ] **High — `arrow/server/server.py:286-315`** — unauthenticated POST can write base64-decoded bytes under publicly served screenshot directory. Authenticate, limit decoded image bytes/dimensions, validate image format, and use collision-safe names. `MAX_CONTENT_LENGTH` protects only request size.
- [ ] **Medium — `browser_extension/manifest.json:7-15`** — all-site host permissions and content-script injection substantially enlarge browser permission scope. Restrict injection via allow-list or on-demand `activeTab`/scripting with explicit explanation.
- [ ] **Medium — `arrow/server/server.py:236-249`** — /status exposes hostname, IP, platform, and Python version to unauthenticated callers. Replace with minimal ready state or protect detailed diagnostics.
- [ ] **Medium — `arrow/server/security.py:76-97`** — Windows token-file ACL tightening failures leave token-file permissions uncertain. Add explicit fail-closed/diagnostic behavior and Windows ACL tests, especially on first install.
- [ ] **Medium — `.gitignore:1-21`** — excludes only the exact `.env` name, not `.env.local`, `.env.production`, `*.key`, or custom secret files. Add `.env.*` with `!.env.example` and secret-file patterns. This is a preventive weakness, **not evidence of committed secrets**.
- [ ] **Medium — `arrow/ui/voice_input.py:55`** — voice transcription calls `recognize_google`, which is network dependent; local-first branding should disclose off-device audio processing and offer opt-in/local transcription. Verify privacy policy and consent UI.
- [ ] **Medium — `arrow/app.py:48-53`; `.env.example:1-5`** — advertised env port settings not actually read by bootstrap. Centralize configuration and document `ARROW_HOME`, `ARROW_ENABLED_CAPABILITIES`, token handling, and ports.
- [ ] **Secret scan status:** No confirmed committed plaintext API key from the files individually inspected. A complete tracked-file/commit-history secret scanner was **not run**, so this is not a clean security certification.

## 8. UI/UX Issues & Fixes

- [ ] **Fixed layout — `arrow/ui/notch.py:367,384-390`:** replace hardcoded 320 px content sizing with responsive range 320–480 logical px, 16 px internal padding, 12 px vertical component spacing, and aspect-fit previews. Test 100%, 150%, 200% Windows scaling and 1366×768/4K.
- [ ] **Status feedback — `arrow/ui/notch.py:1267-1272`, `arrow/app.py:260-272`:** implement status surface with idle/capturing/resolving/sending/completed/failed/offline states; 150–200 ms transitions, but respect reduced motion.
- [ ] **Capture errors — `arrow/app.py:175-244`:** after errors, show a clear message and Retry/Copy details action; never leave only a log entry.
- [ ] **Voice control — `arrow/ui/voice_input.py:24-79`:** add visible microphone permission, listening timeout, upload/recognition spinner and retry. Stop must cancel correctly (not merely reset boolean).
- [ ] **Preview visibility — `arrow/ui/notch.py:1250-1265`:** avoid collapsing a fresh result automatically after only 1500 ms while user is moving pointer; consider 3000 ms and preserve manual expanded state.
- [ ] **Browser setup — `browser_extension/popup.js:1-47`:** token load/save shows a success message before WS authentication is confirmed; display separate Saved, Connecting, Connected, Wrong token states via service-worker messaging.
- [ ] **Brand consistency — `browser_extension/manifest.json:3-17` and `arrow/app.py:48`:** replace Bluely names with Arrow Annotate consistently.

**Limitation:** No desktop screenshot or live browser extension was rendered; visual spacing, hover behavior and actual contrast remain unverified. Numbers above are concrete suggested acceptance targets, not measurements of the current rendered UI.

## 9. Prioritized Fix Plan

| Priority | Task / evidence | Effort |
| --- | --- | --- |
| Critical | Require auth for screenshot, inspection and writable capture endpoints — `arrow/server/server.py:251-314,617-745` | moderate/rework |
| High | Fix voice thread cancellation/stale-generation race — `arrow/ui/voice_input.py:24-79` | moderate |
| High | Handle screenshot failure before thread submission — `arrow/app.py:101-151` | quick/moderate |
| High | Verify/correct nonzero-origin screenshot cropping — `arrow/server/server.py:716-724` | moderate |
| High | Run Windows install, pytest, Ruff, mypy, GUI + Chrome integration; capture actual outputs — `main.py:8-16`, `pyproject.toml:28-49` | moderate |
| High | Implement UI status methods and error states — `arrow/ui/notch.py:1267-1272` | moderate |
| Medium | Respect configurable ports; synchronize extension — `arrow/app.py:51`, `browser_extension/background.js:22`, `.env.example:1-5` | quick/moderate |
| Medium | Limit extension permissions — `browser_extension/manifest.json:7-15` | moderate |
| Medium | Scope Agentation sessions and add offline flows — `arrow/app.py:205-244` | moderate |
| Medium | Use collision-proof filenames — `arrow/server/server.py:298-299,714-715` | quick |
| Medium | Responsive notch sizing, DPI tests — `arrow/ui/notch.py:367-390` | moderate |
| Low | Rename stale Bluely branding, version consistency — `arrow/app.py:48`, `browser_extension/manifest.json:3-17`, `pyproject.toml:3`, `arrow/server/server.py:239` | quick |

## 10. Nice-to-haves

- Add a Windows GitHub Actions matrix running pytest, Ruff, mypy and a headless smoke test (`main.py:8-16`; `pyproject.toml:28-49`).
- Add integration tests for token misuse, first-run setup, browser service-worker restart, port conflicts, and no Agentation service (`browser_extension/background.js:1-104`, `arrow/providers/agentation.py:8-123`).
- Provide local/offline speech-to-text option and explicit privacy messaging (`arrow/ui/voice_input.py:55`).
- Add a troubleshooting diagnostics screen with service status, hotkey status and dependency readiness (`arrow/app.py:248-272`).
- Add error telemetry that is disabled by default, redact screenshot contents and voice transcripts, and surface opt-in in settings.

---

### Audit qualification

This document provides useful **source-confirmed findings** and concrete remediation steps but is **not** a completed execution-level prelaunch certification. Repository cloning, package installation, Windows GUI exercise, Chrome extension exercise, pytest, Ruff and mypy did not run; these are explicitly classified as blocked/unverified instead of fabricated passes or failures. No numerical readiness percentage is justified until these checks can run.