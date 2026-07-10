# Codex MCP setup

Arrow exposes a local MCP (Model Context Protocol) server so Codex can retrieve
the latest Arrow change request and screenshots without any copy-paste.

## Start the server

The server speaks JSON-RPC 2.0 over stdio:

```bash
python -m arrow.mcp.server
```

It reads captures from the Arrow SQLite database (default: `arrow.db` in the
project root, override with `ARROW_DB_PATH`).

## Register with Codex

Add Arrow to your Codex MCP configuration.

### Project-level

Create `.codex/mcp.json` in your repository:

```json
{
  "mcpServers": {
    "arrow": {
      "command": "python",
      "args": ["-m", "arrow.mcp.server"],
      "env": {
        "ARROW_DB_PATH": "C:\\path\\to\\arrow.db"
      }
    }
  }
}
```

### Global

Add the same `arrow` entry to your global Codex config (`~/.codex/config.toml`
or the equivalent MCP servers file for your Codex version).

## Available tools

Read-only:

- `arrow_get_latest_change_request`
- `arrow_get_change_request`
- `arrow_list_change_requests`
- `arrow_get_capture_metadata`
- `arrow_get_project_context`
- `arrow_get_source_context`
- `arrow_get_destination_context`

Controlled mutation (status only — never OS actions):

- `arrow_mark_started`
- `arrow_mark_completed`
- `arrow_mark_failed`
- `arrow_add_agent_note`

## Available resources

Screenshot assets are exposed as MCP resources:

```
arrow://captures/{capture_id}/raw
arrow://captures/{capture_id}/annotated
arrow://captures/{capture_id}/context-crop
arrow://captures/{capture_id}/source-crop
arrow://captures/{capture_id}/destination-crop
```

## Workflow

1. Create a request in Arrow.
2. In Codex, say: "Implement the latest Arrow request."
3. Codex calls `arrow_get_latest_change_request`, reads the screenshots, edits
   your repository, and reports status via `arrow_mark_started` /
   `arrow_mark_completed`.
