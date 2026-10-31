# Arrow architecture — 2026-10-31

Arrow is a Windows PyQt desktop application, a local capture database, a browser
extension and an MCP stdio server. It is not an embedded copy of Codex or Claude.

## Runtime flow

`main.py` → `launcher.entrypoint` → desktop logging/single-instance lock →
`app.main` → Qt notch, overlay, microphone, capture coordinator, HTTP/WebSocket
services and system tray. CLI `--mcp` instead serves JSON-RPC on stdin/stdout.

The held shortcut starts an annotation session. Releasing it freezes the drawing
and desktop image while speech recognition finishes asynchronously. The
coordinator binds results to capture IDs and discards cancelled/stale results.
The orchestrator collects observed element/repository evidence, renders the
scene and crops, compiles an instruction, writes PNG files and commits SQLite
records. Speech, original drawing points and coordinate metadata are retained.

## File map

- `arrow/launcher.py`, `app.py`: entry points, startup and lifecycle coordination.
- `arrow/core`: hotkey hooks, resource/data paths and logging.
- `arrow/capture`: session state, drawing geometry, virtual-display composition,
  annotated PNGs, crop generation and latest-file convenience mirror.
- `arrow/context`: DOM/native evidence, repository/source mapping, orchestration
  and revisioned capture bundles.
- `arrow/intent`: conservative instruction classification, anchors, ambiguities
  and readable/structured requests. Missing evidence remains unknown.
- `arrow/storage`: SQLite migrations, atomic request/context/assets persistence,
  deletion and application preferences. PNGs are separate filesystem assets.
- `arrow/ui`: slim pill, capture history/details, settings, clipboard, voice and tray.
- `arrow/providers`: CLI discovery/auth checks, background adapters and visible
  client handoff. Authentication remains with the official client.
- `arrow/mcp`: tools, resources and JSON-RPC transport. The bundle tool returns
  both complete text context and a stored annotated image, not a fresh screenshot.
- `arrow/server`, `browser_extension`: authenticated loopback HTTP/WebSocket
  utilities and DOM inspection. These are distinct from MCP stdio transport.
- `packaging`, `scripts`, `.github/workflows`: Windows executable/installer build,
  provenance, native clipboard checks and install/uninstall smoke checks.
- `tests`: regression coverage for these boundaries; native Windows tests require Windows.

## Agent handoff

`build_capture_bundle(id)` reads the exact saved capture and creates a revision
identified by its metadata/image digest. `capture.json`, `prompt.md` and copied
PNGs preserve that revision when another capture is made or the instruction is
edited. Original speech remains separate from the current instruction.

Codex and Claude Code open interactive CLI sessions in a visible Windows console.
Their per-session MCP configuration points to the installed `ArrowMCP.exe` (or the
source Python entry point) and the same data directory/database. Codex receives
an image attachment; Claude receives explicit file access and the bundle path.

VS Code's documented draft URI can prefill its agent composer. This does not
select a Codex/Claude extension. Codex desktop's documented URI opens a workspace;
without a supported prefill parameter, Arrow copies the complete context and
labels the remaining paste step honestly. Launching is never reported as agent
work completion. Unsupported clients are not assumed to accept arbitrary links.

## Verified limitations

The cloud environment could not access `lite.supamaus.com` (proxy HTTP 403), and
no Heyclick folder was supplied. This is an independent Windows implementation;
exact parity with that reference has not been verified.

The native rich UIA resolver is not fully connected to the normal capture path,
and browser DOM ownership across overlapping windows needs further validation.
The latest-file mirror is a convenience, not an immutable context transport; use
capture-ID bundles for handoff. Live Windows app focus, provider login and UI
paste behavior require user-machine validation beyond mocked launch tests.
