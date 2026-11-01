# Live agent validation

Arrow's live agent check is explicitly opt-in. It invokes the installed Codex or
Claude Code CLI using that client's existing account and may use account quota.
It never starts on application launch or in ordinary credential-free tests. No
API key or login prompt is requested by Arrow. A missing CLI or an unauthenticated
client cannot pass.

The check creates a disposable Arrow home, SQLite database, PNG and empty working
repository. The initial prompt identifies one synthetic capture. It contains
neither expected answer. A random eight-character code is drawn as large black
text on white pixels, with no textual image metadata. A separate random context
code is stored in the capture's current instruction. The CLI must call the real
Arrow MCP bundle implementation for that exact capture, inspect the returned
image and instruction, then return the image code, context code and capture ID.

The per-session MCP configuration points to `--validation-mcp FIXTURE RECEIPT`.
This private endpoint advertises only `arrow_get_capture_bundle` and rejects
other capture IDs, omitted IDs, other tools, resource reads and resource lists.
It uses only the synthetic database. A receipt is written after the response is
flushed, recording the capture ID, session nonce, JSON-RPC request ID and SHA-256
of the actual returned PNG. Expected answers are absent from the receipt.
The check requires a matching receipt, both exact nonce answers, the exact
capture ID and a successful CLI exit. MCP registration, login status, process
startup or an MCP protocol probe alone never demonstrates a model answer.

Codex uses `exec --sandbox read-only --json --ephemeral`, with the synthetic
repository as its working directory. Claude uses print mode, default permissions,
an explicit MCP tool allowlist and no built-in tools. Neither configuration is
written to the user's global MCP settings. A bounded timeout or cancellation
stops the child process tree. On Windows the CLI starts suspended, is assigned
to a kill-on-close Job Object, and is then resumed. Closing the job stops MCP
descendants even if the CLI already exited; an abrupt Arrow exit also closes
the owning job handle. Temporary captures and provider output are deleted at
the end.

The Python entry point is
`run_live_check(provider_name, report_path, timeout=120)` from
`arrow.providers.live_check`; provider names are `Codex` and `Claude Code`.
The function returns zero only after full verification. Set
`provider_overrides=True` for Codex to place its `sqlite_home` and `log_dir` in
the temporary fixture when an existing account lives in a read-only home.
Authentication continues to use the installed client's existing configuration.
The optional `cancel_event` parameter accepts a `threading.Event`; cancellation
is checked at most every quarter second while awaiting the CLI. A cancelled
check reports `failed` / `cancelled` and still performs process and fixture
cleanup.
The JSON report contains the provider, platform (including Windows or Linux),
synthetic-fixture marker, safe status/reason and receipt/answer match booleans.
It contains no credentials, raw stdout/stderr, image/context answer values,
account details or real captures.

`tests/test_live_handoff.py` exercises the actual MCP subprocess and synthetic
SQLite/PNG path, strict routing, receipt matching, answer parsing, missing CLI,
missing receipt, provider failure and timeout behavior. Fake provider replies in
those tests check protocol boundaries only; they are not live model results.
A Linux pass does not prove Windows CLI or desktop behavior. Run each available
provider on each target platform and retain the safe reports separately.

In the current Linux cloud environment (2026-11-01), the installed Codex cannot
initialize its in-process app server because its existing account home is
immutable. The CLI opens its `installation_id` file for both reading and writing;
redirecting SQLite and logs does not redirect that file. The live check reports
`failed` / `provider_state_read_only`, without a receipt or verified answer.
Claude Code is absent and reports `not_run` / `not_installed`. Neither result
proves successful model retrieval. Arrow does not replace `HOME`/`CODEX_HOME`,
copy credentials or modify the account configuration to work around this runtime
restriction. Complete live verification still requires an installed,
authenticated CLI in a normally writable account home on the target platform.

In the notch, open **Settings → Agents → Verify live handoff** beneath the
installed client. The button shows progress and a separate verification result;
it does not change CLI sign-in or MCP registration status. Safe reports are
saved to `ARROW_HOME/logs/live-handoff-codex.json` or
`live-handoff-claude-code.json` (the default home is `%USERPROFILE%\.arrow`).

From an installed console:

```powershell
& "$env:LOCALAPPDATA\Programs\ArrowAnnotate\ArrowMCP.exe" --verify-agent Codex "$env:TEMP\arrow-codex-live.json"
& "$env:LOCALAPPDATA\Programs\ArrowAnnotate\ArrowMCP.exe" --verify-agent "Claude Code" "$env:TEMP\arrow-claude-live.json"
```

Use your actual installation folder if it differs. A successful source test or
MCP receipt without both correct model answers is insufficient for a live pass.
