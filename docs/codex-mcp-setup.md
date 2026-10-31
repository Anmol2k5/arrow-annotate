# Codex and Arrow MCP

Arrow's **Codex** handoff opens the interactive CLI with per-session `-c`
MCP overrides pointing at the same Arrow database. It does not use `codex exec`.
The actual screenshot is attached and full context is available through
`arrow_get_capture_bundle(capture_id)`.

For persistent Codex CLI/desktop configuration, use the supported command:

```powershell
codex mcp add --env "ARROW_HOME=$env:USERPROFILE\.arrow" arrow -- "C:\path\to\ArrowMCP.exe" --mcp
codex mcp list
```

Use the actual installation path. Codex configuration uses TOML `mcp_servers`
entries in `config.toml`; `.codex/mcp.json` is not Codex's configuration format.
For source development, replace the executable with the virtual environment's
Python and pass the absolute `main.py` path before `--mcp`.

MCP registration and account sign-in are separate. Codex desktop's documented
workspace launcher does not document prompt/image query parameters. Arrow opens
the workspace and copies context for pasting instead of claiming automatic prefill.
