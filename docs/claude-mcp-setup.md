# Claude Code MCP setup

Arrow ships a local MCP server so Claude Code can retrieve the latest Arrow
change request and screenshots directly.

## Start the server

```bash
python -m arrow.mcp.server
```

The server speaks JSON-RPC 2.0 over stdio and reads from the Arrow SQLite
database (default `arrow.db`, override with `ARROW_DB_PATH`).

## Register with Claude Code

### Project-level (recommended)

Use the CLI:

```bash
claude mcp add arrow -- python -m arrow.mcp.server
```

Or add to `.mcp.json` in your repository root:

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

```bash
claude mcp add --scope user arrow -- python -m arrow.mcp.server
```

## Tools and resources

The same read-only tools, controlled mutation tools and `arrow://` screenshot
resources documented in [`codex-mcp-setup.md`](./codex-mcp-setup.md) are
available to Claude Code.

## Workflow

1. Create a request in Arrow.
2. In Claude Code, say: "Implement the latest Arrow request."
3. Claude calls `arrow_get_latest_change_request`, reads the annotated and raw
   screenshots as MCP resources, edits the selected repository, and reports
   progress with `arrow_mark_started` / `arrow_mark_completed`.
