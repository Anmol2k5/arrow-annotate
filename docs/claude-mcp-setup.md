# Claude Code MCP setup

Arrow ships a local MCP server so an **existing** Claude Code session can read
your task, see the screenshots you took, and verify its own work.

> Verified on Windows against **Claude Code 2.1.205** (`claude --version`).
> The `claude mcp list` health check reported `✔ Connected`, and a real stdio
> JSON-RPC round-trip returned both a task manifest and a valid PNG image
> block. Codex is **not installed** on the verification machine, so its setup
> below is unverified — see [`codex-mcp-setup.md`](./codex-mcp-setup.md).

## Register

```powershell
claude mcp add arrow -- .\.venv\Scripts\python.exe -m arrow.mcp.server
claude mcp list        # expect: arrow: ... - Connected
```

If you use the venv explicitly (recommended on Windows, where `python` may
resolve to a different interpreter), pass the interpreter path as shown above.

Confirm what was registered:

```powershell
claude mcp get arrow
```

To remove it:

```powershell
claude mcp remove arrow --scope local
```

### Project-level `.mcp.json`

```json
{
  "mcpServers": {
    "arrow": {
      "command": "python",
      "args": ["-m", "arrow.mcp.server"],
      "env": {
        "ARROW_HOME": "C:\\Users\\you\\.arrow"
      }
    }
  }
}
```

Set `ARROW_HOME` rather than `ARROW_DB_PATH` so the server reads the same
database and screenshots as the running app.

## What the agent can do

### Tasks (the multi-screenshot workflow)

| Tool | Purpose |
|---|---|
| `arrow_get_latest_task` | The most recent task: your grouped screenshots + instruction |
| `arrow_list_tasks` | Task list (id, title, instruction, status, capture count) |
| `arrow_get_task_context` | One task as a full JSON manifest |
| `arrow_get_task_markdown` | One task as agent-readable Markdown |
| `arrow_list_task_captures` | Captures in your defined order, with target provenance |
| `arrow_get_capture_image` | A screenshot as **real MCP image content** |
| `arrow_get_fresh_screen_context` | A **new** screenshot to verify a change |

### Captures (unchanged, still supported)

`arrow_get_latest_change_request`, `arrow_get_capture_metadata`,
`arrow_get_source_context`, `arrow_get_destination_context`,
`arrow_get_ax_tree`, `arrow_look`, `arrow_get_context_md`, the
`arrow_mark_*` status tools, and `arrow://` screenshot resources.

## Workflow

1. In Arrow, click **+ Task**, then Point at two or three elements. Click
   **Copy task** if you want the Markdown on your clipboard too.
2. In an **existing** Claude Code session, say:
   *"Read my latest Arrow task and implement the requested change."*
3. Claude calls `arrow_get_latest_task`, reads the manifest, then calls
   `arrow_get_capture_image` per capture to actually **see** each screenshot.
4. After editing, it calls `arrow_get_fresh_screen_context` to verify, and
   `arrow_mark_completed` when done.

## Honesty rules

- A task stays `draft` until something actually moves it. Availability over
  MCP is **not** evidence an agent engaged.
- `arrow_get_fresh_screen_context` timestamps its capture and says plainly it
  is new — an agent must not present it as one of your stored screenshots.
- When Arrow could not identify the element you pointed at, the manifest says
  `resolution_method: "fallback"` and `confidence_kind: "none"`. That crop is
  around your click, not a detected element.

## Troubleshooting

- **`Server disconnected`** — run `python -m arrow.mcp.server` by hand; it
  should wait silently on stdin. Errors go to stderr.
- **No tasks found** — the MCP process and the running app must share
  `ARROW_HOME`.
- **`Image file ... is missing on disk`** — the capture was deleted, or
  `ARROW_HOME` points somewhere else. Use `arrow_get_capture_metadata` for
  the recorded path.
- **PowerShell swallows `--`** — if `claude mcp add` reports `unknown option`,
  invoke `claude.exe` directly rather than the `claude.ps1` wrapper.