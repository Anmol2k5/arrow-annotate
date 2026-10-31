# Local screen context

Arrow's Windows equivalent of the supplied Lite workflow combines a saved
annotated screenshot, source/destination geometry, gesture direction, instruction
and accessible window text. The instruction can be typed or transcribed locally.
Window-text status distinguishes complete, partial and unavailable evidence.
Captured text may include sensitive information visible in the selected window;
review it before handing it to an agent. Password controls are skipped.

## One-time voice setup

Use **Settings → Capture → On-device voice → Download voice model**. Arrow fetches
public `Systran/faster-whisper-base` files anonymously into
`ARROW_HOME/models/whisper-base` (default `%USERPROFILE%\.arrow\models\whisper-base`).
No microphone audio accompanies the download. Recognition loads only local files,
uses CPU/int8, and has no cloud fallback. Hindi and English are selectable.
Missing model, download failure or microphone failure still permits typed captures.
Source installs need `pip install -e ".[speech]"`; Windows installers include the
runtime. First recognition may take longer while the local model loads.

## Connect an agent

**Open in agent** creates a capture-specific interactive Codex/Claude CLI session
with stdio MCP configured automatically. Account sign-in belongs to that client.
For another compatible HTTP MCP client, keep Arrow running and open **Settings →
Agents → Local MCP and REST → Copy MCP connection JSON**. This copies the actual
local URL plus a per-install access token. Treat that token as a local credential;
it is not an API key and requires no Arrow account.

With the default data directory/port, persistent CLI registration in PowerShell is:

```powershell
$arrowToken = (Get-Content "$env:USERPROFILE\.arrow\token" -Raw).Trim()
$env:ARROW_LOCAL_TOKEN = $arrowToken
codex mcp add arrow --url http://127.0.0.1:5001/mcp --bearer-token-env-var ARROW_LOCAL_TOKEN
claude mcp add --transport http arrow http://127.0.0.1:5001/mcp --header "Authorization: Bearer $arrowToken"
```

Launch Codex from a shell where `ARROW_LOCAL_TOKEN` is set. Use the URL shown in
settings if your port differs, and `ARROW_HOME/token` if you changed the data
directory. Restart the client after adding a server. Registration does not sign
you into the agent or automatically insert a message into an already-open chat.
Ask the agent to call `arrow_get_capture_bundle` for the desired capture ID; without
an ID it retrieves the latest. MCP returns text plus actual annotated PNG content.

HTTP transport accepts a single JSON-RPC message per `POST /mcp`, returns JSON,
and accepts initialized notifications with HTTP 202. It is stateless, without SSE
or server-initiated messages; `GET /mcp` returns 405. Stdio remains supported and
can read saved captures without the GUI running.

## REST reads

Requests require `Authorization: Bearer <local token>` and the capture-context
capability. The service binds to loopback and rejects non-local origins/hosts.
Responses have `Cache-Control: no-store`.

| Endpoint | Result |
| --- | --- |
| `GET /api/captures?limit=20` | Saved capture list (limit 1–100) |
| `GET /api/captures/<id>` | Same immutable bundle metadata as MCP |
| `GET /api/captures/<id>/image` | Saved annotated PNG bytes |

The optional live `arrow_look` MCP tool also requires the screenshot capability.
No default automatic forwarding to Agentation occurs. When you explicitly open
or connect an AI client, its own account and processing policy applies.
