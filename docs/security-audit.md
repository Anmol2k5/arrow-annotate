# Security Audit

## 1. Unauthenticated Local Endpoints
The local Flask server (`server.py`) binds to `127.0.0.1:5001` but has no authentication mechanisms (e.g., Bearer tokens or CORS restrictions for specific origins).
Any process or script running on the local machine can trigger the endpoints.

## 2. Shell Execution Vulnerability
The `OSController.open_app(target)` method in `server.py` uses:
`subprocess.Popen(target, shell=True)`
If a malicious payload is sent to `/execute` with `{"type": "openapp", "target": "notepad & format C:"}`, it will be executed by the shell.
**Recommendation:** Remove `shell=True` and avoid general-purpose command execution.

## 3. Arbitrary OS Control
The `/execute` endpoint allows triggering `ctypes` mouse clicks, keyboard typing (`SendInput`), and hotkeys.
This allows full control over the user's desktop without any explicit confirmation dialog.
**Recommendation:** Require user confirmation before destructive actions or limit capabilities based on explicit scopes.

## 4. Unprotected Screenshots
The `/screenshots/<filename>` endpoint serves local files unconditionally via `send_from_directory`.
While bound to localhost, it still allows any local process to exfiltrate captured screenshots.
Additionally, screenshot deletion (`_clear_all` in `notch.py`) simply uses `os.remove` and ignores failures (`except: pass`), leading to inconsistent deletion and leftover sensitive data.

## 5. Browser WebSocket Bridge
The WebSocket bridge binds to `127.0.0.1:5002`. Any local application can connect to this WebSocket and send `inspect` commands to the active browser tab, potentially extracting sensitive DOM information.

## Summary of Fixes Required
- Implement strict localhost-only binding with a random per-install bearer token.
- Remove `shell=True` entirely.
- Add user confirmation for OS mutations.
- Implement strict payload validation.
- Implement atomic and verified deletion of sensitive assets.
