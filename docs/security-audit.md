# Security Audit

Status of the local server's security posture after the Phase 14 hardening
(`arrow/server/security.py`).

## 1. Local binding

Flask binds to `127.0.0.1:5001` and the WebSocket bridge to `127.0.0.1:5002`.
The server is only reachable from the local machine.

## 2. Bearer token authentication — FIXED

A random per-install bearer token (32-byte `secrets.token_urlsafe`) is generated
on first use and persisted to `$ARROW_HOME/token` (default `~/.arrow/token`,
`0600` chmod — best-effort; on Windows the chmod is a no-op).

- Mutating endpoints require `Authorization: Bearer <token>`:
  `/execute`, `/execute/batch`, `/highlight/execute`.
- Token comparison uses `hmac.compare_digest`; creation is serialized with a
  lock so concurrent first-ever requests cannot diverge into two tokens.
- Missing/invalid token → `401 Unauthorized`.

External consumers must read the token from the file above and send it in the
`Authorization` header.

## 3. Origin validation — FIXED (mutating endpoints only)

Protected endpoints reject requests whose `Origin` header is present but not
`127.0.0.1`, `localhost`, or `::1` (`403`). A missing Origin (non-browser
client) is allowed; the token is the real gate.

## 4. Shell execution vulnerability — FIXED

`OSController.open_app` previously ran `subprocess.Popen(target, shell=True)`,
which executed arbitrary command strings. It now only opens **existing
filesystem paths** via the OS file association (`os.startfile`); anything else
returns an error. General-purpose command execution is never exposed.

## 5. Capability model — FIXED (with explicit opt-in)

Sensitive capabilities are disabled by default. `CONTROL_NATIVE` is required
for `/execute`, `/execute/batch`, and `/highlight/execute`; it is enforced
before the handler runs (after token + origin checks).

Opt in explicitly before starting the server:

```bash
set ARROW_ENABLED_CAPABILITIES=control_native   # Windows
export ARROW_ENABLED_CAPABILITIES=control_native # POSIX
```

Unknown capability names are ignored (logged).

## 6. Request-size limit — ADDED

`MAX_CONTENT_LENGTH = 8 MiB` caps request bodies.

## 7. WebSocket bridge authentication — FIXED

`ws://127.0.0.1:5002` now requires a bearer-token handshake before any
`inspect` command is accepted:

1. The client connects and must send `{"type": "auth", "token": "…"}` within
   10 seconds.
2. The server validates the token against the same per-install token as the
   HTTP endpoints (`~/.arrow/token`).
3. Success → `{"type": "auth_ok"}` and the connection is registered.
   Failure (missing, malformed, wrong token, or timeout) →
   `{"type": "auth_error"}` followed by a close with code `4001`.
4. Until auth succeeds the connection is not registered, so `/inspect`
   requests return `503` rather than reaching an unauthenticated socket.

**How the extension gets the token:** the extension popup (`popup.html`)
accepts the token by paste or by "Load from file…" (the user picks
`~/.arrow/token`); it is stored in `chrome.storage.local` and sent on every
connection. The badge shows `KEY?` (no token), `AUTH` (wrong token), `ON`
(authorized), or `OFF` (disconnected). Unauthorized connections are not
auto-reconnected — the extension waits for the user to fix the token.

## 8. Remaining open items

- **Read endpoints are unauthenticated by design.** `/status`, `/screenshot`,
  `/screenshots/*`, `/screenshots/save`, `/resolve`, `/inspect`,
  `/highlight/resolve`, `/highlight/capture` require no token. This is
  intentional: the read capabilities are enabled by default, and gating
  `/screenshots/*` would break the Agentation flow, which fetches screenshot
  URLs (`http://127.0.0.1:5001/screenshots/<file>`) without auth. Any local
  process can read screenshots and DOM inspection data.
- **Windows token-file permissions.** `os.chmod(0o600)` does not enforce
  ACLs on Windows; the token may be readable by other local users.
- **Screenshot deletion.** `notch.py` `_clear_all` ignores `os.remove`
  failures (`except: pass`), which can leave sensitive captures on disk.
- **Read-capability enforcement is aspirational.** `READ_SCREENSHOT`,
  `READ_CAPTURE_CONTEXT`, and `READ_REPO_CONTEXT` are defined and
  default-enabled but not enforced by any endpoint yet.
