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

## 7. Remaining open items

- **WebSocket bridge (5002) is unauthenticated.** Any local process can
  connect and send `inspect` commands to the active browser tab. Fixing it
  needs a design decision first: how does the browser extension obtain the
  token (it cannot read `~/.arrow/token`)? Until that is answered, do not
  bolt auth onto the bridge in a way that breaks the extension.
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
