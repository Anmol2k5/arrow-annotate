# Local spatial context implementation plan

> Execution: implement incrementally in this session, with regression tests and full verification.

Goal: port the supplied Lite workflow to Arrow on Windows: local capture and
speech, typed instructions, exact regions/direction/window text, shared local
MCP/REST access and existing Codex/Claude Code handoff. No Arrow account or cloud
API key is required. The user's agent remains responsible for its own account.

Architecture: retain Python/PyQt, SQLite and immutable capture bundles. Use
CPU/int8 multilingual faster-whisper with an explicitly downloaded local model;
never fetch weights or contact speech services while transcribing. Add stateless
JSON Streamable HTTP MCP to the existing loopback Flask server and reuse its
local authorization token (not a cloud API key). Keep stdio for existing clients.
Resolve the actual window at each annotation point, retaining text extraction
status/limits and avoiding foreground-window substitutions.

Tasks:
- [x] Offline voice: tests for local-only model loading, no network fallback,
  cancellation and existing push-to-talk semantics; model installer in Capture
  settings; packaged runtime dependencies; typed overlay input bypasses speech.
- [x] Shared endpoint: authenticated POST /mcp plus capture REST reads; initialization,
  notifications, tools, stored image retrieval, bad origins and malformed requests.
  Show/copy connection configuration inside Agents settings.
- [x] Window context: collect actual owner/window/UIA text at release, physical
  point mapping, bounded traversal with truncation/unavailable markers, persisted
  source/destination context; gate wrong-window browser evidence.
- [x] Verify complete test suite, lint/types, actual HTTP and stdio exchanges,
  packaging dependency imports and native Windows installer/smoke workflow.

Local verification: 511 Python tests passed, one native-Windows clipboard test
skipped on Linux; four browser tests passed. Ruff, mypy and diff checks passed.
Actual loopback HTTP initialization, capture tool/image, REST PNG and an independent
stdio child read the same saved capture. Source smoke loaded the native speech
runtime. The official MCP Python SDK also initialized, listed tools and retrieved
saved text plus PNG through the shared HTTP endpoint.

Windows build [41218287522](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41218287522)
passed source tests, native clipboard verification, executable/installer creation,
portable and installed smoke checks (including native speech dependency imports),
real frozen stdio MCP exchange and uninstall/data-preservation checks. Artifact:
`Arrow-Annotate-Windows-x64-12`, setup version `0.3.0`.

The cloud proxy rejected the real Hugging Face model download (HTTP 403), so model
installation/transcription behavior is covered with boundary fakes, not a claimed
real speech-recognition result. Live Windows UIA and microphone behavior require
interactive validation. The settings UI was rendered and visually inspected offscreen.

Review focus: missing/partial speech model, offline capture, microphone failure,
old ASR worker completion, typed-only capture, protected/password controls,
DPI/negative origins, hostile HTTP origins/hosts, disabled capabilities, model
installer failures and data-directory consistency across MCP transports.

Limits: Windows UIA cannot reveal text an application does not expose; report
unavailable/truncated rather than claiming complete text. One-time model download
uses the internet but never includes recorded audio/screenshots. Image/text sent
to an external AI agent follows that agent's own processing/data policy.
