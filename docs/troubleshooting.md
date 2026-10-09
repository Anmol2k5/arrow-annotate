# Troubleshooting

## Voice input does nothing

- Check the microphone permission for your OS and that PyAudio installed
  (`pip show PyAudio`). On Linux install `portaudio19-dev` first.
- The status notch shows `Voice unavailable` when the audio stack cannot be
  opened; the typed-instruction path still works.
- If a voice session seems stuck, start a new capture — cancellation is
  generation-based, so a new session always wins over an in-flight one.

## Extension cannot connect

- The desktop app must be running; it hosts the local server.
- Default bind is loopback only. If you changed the port, set the same port
  in the extension popup (or `.env`).
- "auth failed" means the token does not match the app's current token —
  regenerate it in the app and paste it again.
- "server unavailable" after retries usually means the app is not running or
  the port is firewalled; the popup shows the live state honestly instead of
  pretending to be connected.

## Screenshot failure leaves the app in a weird state

This used to wedge the session. Failures now record an error on the capture
session (`FAILED` state) and surface `Screenshot failed` in the notch. Start
a new capture; if it repeats, check display scaling changes mid-capture and
GPU capture permissions.

## Agentation sync fails

The capture is marked `FAILED` with the reason (`agentation sync failed: …`)
and the notch shows the failure. Common causes:

- Agentation not running on the configured URL (default
  `http://127.0.0.1:4747`).
- No usable session and `create_session` rejected — start a project session
  in Agentation first.

## Multi-monitor crop is wrong

Crop math handles negative and non-zero monitor origins (see
`tests/test_crop_geometry.py`). If a region lands wrong, note whether the
monitor is left/above the primary — that's the negative-origin case — and
check `docs/current-architecture.md` for the coordinate-space contract.

## App starts then immediately exits

Check the log output in the terminal. Common causes: port already in use
(change `ARROW_SERVER_PORT`), missing `.env` values (copy from
`.env.example`), or a Qt plugin failure on headless machines (set
`QT_QPA_PLATFORM=offscreen` for non-GUI test runs).

## Tests crash the interpreter (exit code 0xC0000409)

A `QApplication` was garbage-collected while Qt was still using it. Keep a
module-level reference in test helpers (see `docs/testing.md`).
