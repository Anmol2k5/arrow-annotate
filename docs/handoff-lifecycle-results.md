# Agent handoff and Windows lifecycle results

Candidate version: **0.4.2**. Code commit: `63fdc68`.
Verified on 1 November 2026.

[Native Windows run 21](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41274408192)
passed the required source, native, packaging and runtime checks:

- Actual Windows Job Object ownership and shutdown after the CLI parent exits;
  the MCP-like child must already be signaled and its open file removable when
  production cleanup returns.
- Frozen portable and installed production startup, native HWND visibility,
  HTTP/WebSocket service startup, tray activation restore, close-last-window
  survival, Show Arrow restore, Quit and service/tray cleanup. Two fresh runs
  per bundle prove lock/port release and relaunch with the same data directory.
- Actual public `0.4.1` installer downloaded and SHA-256 verified, then upgraded
  in the same installation directory to `0.4.2`. Frozen old-format synthetic data
  survives the upgrade and new desktop launches: shortcut, speech language,
  clipboard/UI preferences, selected repository, capture, original speech,
  corrected instruction, annotations, window context and exact PNG bytes.
  Both installed MCP versions retrieve the expected image and context.
- Source, portable and installed offline synthetic speech checks and uninstall
  preservation. Existing native clipboard and UIA/capture checks also pass.

These tray interactions invoke real Qt signals/actions programmatically. They
do not establish physical Windows notification-area clicks, microphone/Hinglish
accuracy, multiple physical monitors or mixed OS display scaling.

Linux source verification: **704 passed, 3 native Windows checks skipped**;
4 browser tests, Ruff, mypy and dependency consistency passed.

Actual authenticated model verification remains **unverified**:

| Client | Linux live result | MCP receipt | Correct model answer |
| --- | --- | --- | --- |
| Codex | CLI startup blocked by read-only account `installation_id` | No | No |
| Claude Code | CLI not installed | No | No |

No account home, authentication file or global MCP configuration was changed to
work around those constraints. Public Windows CI has no provider credentials
and does not run account-backed agent tasks.

On a normal signed-in Windows account, install the candidate and open
**Settings → Agents → Verify live handoff** for each installed CLI. A pass
requires the actual selected synthetic PNG hash in an MCP receipt plus exact
answers for its image-only and instruction-only random codes and capture ID.
The account, MCP protocol and verified model-answer statuses stay separate.
See [live checks](live-agent-validation.md) and
[upgrade details](upgrade-validation.md). Reports contain synthetic check results
without raw provider output, account information or real captures.
