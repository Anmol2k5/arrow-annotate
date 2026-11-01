# Breakage audit — 2 November 2026

Baseline: work branch `78f3932`, released version 0.4.3.

Fresh baseline checks: 746 Python tests passed, 3 Windows-only tests skipped on
Linux; 4 browser tests passed. Ruff, mypy, dependency consistency and whitespace
checks passed. Reviewed microphone/device lifecycle, capture startup/cancellation,
review persistence and image/context handoff paths.

## Reproduced and fixed

An existing handoff image could be modified or corrupted after bundle creation.
`build_capture_bundle` chose its directory from original saved capture bytes,
but trusted cached image files merely because they existed. Subsequent MCP
retrieval could therefore return different or invalid pixels for that capture.

The builder now verifies cached bytes against the persisted source and atomically
restores mismatches before returning the bundle. It preserves capture metadata,
revision identity, original assets and previous legitimate revisions.

Four regressions exercise the real MCP dispatch and SQLite-backed bundle path:
normal annotated and optimized agent image caches, each replaced by a valid wrong
image or truncated data. All four failed before the fix and passed afterward;
they verify restored bytes, actual MCP image content, capture ID, unchanged bundle
identity and untouched original screenshot.

After the fix: 750 Python tests passed, 3 Windows-only tests skipped on Linux;
Ruff, mypy and whitespace checks passed. The four browser tests and dependency
consistency check also passed during this audit. Independent review reported no
actionable findings and reran all nine capture-bundle tests successfully.

[Branch run 25](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41357076598)
and [release run 26](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41357076721)
both passed native Windows source, clipboard/UIA, frozen/installed speech,
desktop startup/tray/relaunch, upgrade preservation and uninstall checks.
The release workflow verified final checksums and published
[v0.4.4](https://github.com/Anmol2k5/arrow-annotate/releases/tag/v0.4.4).
Public Setup, portable archive, checksum and provenance links were verified.
The installer remains unsigned; no signing identity has been configured.

Physical microphone/Hinglish accuracy, real mixed-DPI monitors and authenticated
Codex/Claude answers cannot be established by the Linux or credential-free CI
checks. Existing opt-in Windows checks remain available for those observations.
