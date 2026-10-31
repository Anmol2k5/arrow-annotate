# Review and Windows Readiness Implementation Plan

> **For agentic workers:** Use executing-plans for the coordinator and independent
> parallel workers for speech, provider setup, and release infrastructure.

**Goal:** Deliver reviewable context, straightforward setup and testable Windows distribution.
**Architecture:** Extend Python/PyQt and the existing immutable SQLite capture bundles.
**Tech Stack:** Python 3.12, PyQt6, faster-whisper, documented CLI MCP, GitHub Actions/Inno Setup.
**Spec:** docs/superpowers/specs/2026-10-31-review-and-readiness-design.md

## Global constraints
- Settings/review stay in the notch; no shell interpolation, automatic agent tasks or cloud speech.
- Hardware/account checks remain not-run unless actually exercised.
- Trusted signing requires a user-provided identity; optional setup cannot claim signed output.

## Review focus
- Edited/excluded window text must reach every export and persisted revision.
- Cancelled downloads must leave an existing model usable and permit retry.
- MCP registration must preserve unrelated configuration and distinguish failed probes.
- Release checks/signatures must refer to exact artifacts before public publication.
- No diagnostic report silently records microphone audio, screenshots or credentials.

### 1. Capture review and clean prompts (coordinator)
- [x] Add regression tests for prompt simplicity and reviewed instruction/window text persistence.
- [x] Implement a focused review widget/service and wire selected cards to review before handoff.
- [x] Keep exact saved image and structured diagnostics available; verify edited bundles/clipboard.

### 2. Voice setup (parallel worker)
- [x] Test/implement cancellation, progress and safe model replacement, automatic Hindi/English mode.
- [x] Add speech state signals; coordinator wires progress/cancel controls and status.

### 3. Agent setup (parallel worker)
- [x] Test/implement documented registration and independent real stdio MCP initialize/tools-list probe.
- [x] Distinguish registration, protocol verification and account authentication; coordinator wires UI.

### 4. Distribution (parallel worker)
- [x] Test/implement explicit release update checks, optional trusted signing, verified tag publication.
- [x] Document signing credentials and unsigned behavior without inventing certificates.

### 5. Windows testing (coordinator)
- [x] Add guided local diagnostics with real device/display information and explicit optional checks.
- [x] Cover hardware-free boundaries in unit tests and document interactive acceptance steps.
- [x] Push verified changes and inspect native Windows build.
- [x] Publish the verified version tag and confirm public release downloads.

Local verification: 621 Python tests passed, one native clipboard test skipped on Linux; four browser tests passed. Ruff and mypy passed. Independent review found export duplication, stale latest-file mirror and missing-image completion; each is fixed and regression-tested. Review/settings UI rendered and visually inspected.

Actual microphone/Hinglish, multi-monitor/DPI, desktop startup and authenticated agent task results remain unverified: this host is Linux. The new diagnostic command reports unsupported here, with no false hardware passes. A real model-download attempt failed at the cloud proxy; local recognition is not claimed tested. Signing identity is not available, so release artifacts are unsigned and signing support is prepared.

Native Windows workflow [41227044772](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41227044772) passed source tests, native PNG clipboard test, frozen-app/MCP smoke checks and install/uninstall/data preservation. Initial Windows test assumptions were corrected (explicit UTF-8 reads and case-insensitive environment aliases). A live synthetic Codex session was attempted on Linux but failed during startup because the CLI state directory is read-only; no successful agent session is claimed. Claude Code is absent in this cloud.

Release verification: [v0.4.0](https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.0) is public. Tag workflow [41227617422](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41227617422) passed native build/install checks, final SHA256 verification and publication. The public release page returned HTTP 200 and lists Setup, portable ZIP, hashes and provenance. The release is explicitly unsigned. This publication does not change the pending interactive hardware/account validation status above.
