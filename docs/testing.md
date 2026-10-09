# Testing

## Running the suites

```bash
python -m pytest -q                        # everything (307 tests)
python -m pytest -q tests/test_threading.py   # one file
node scripts/verify-extension.mjs          # extension manifest + state machine
```

CI runs the same commands on `windows-latest` with
`QT_QPA_PLATFORM=offscreen`.

## Layout

| File | Covers |
| --- | --- |
| `tests/test_config.py` | env/.env precedence, loopback rejection |
| `tests/test_share_tokens.py` | HMAC share tokens: scope, TTL, forgery |
| `tests/test_screenshot_upload.py` | upload validation, auth |
| `tests/test_crop_geometry.py` | multi-monitor crop math (negative origins) |
| `tests/test_session*.py` | capture state machine, invalid transitions |
| `tests/test_voice_input.py` | generation-based voice cancellation |
| `tests/test_threading.py` | `UiBridge` delivery, stale discard, wedge recovery |
| `tests/test_agentation.py` | client, session selection, offline degradation |
| `tests/test_notch_status.py` | notch status model wiring |
| `tests/test_hotkey.py` | hotkey bridge debounce + cross-thread emit |
| `tests/test_orchestrator.py` | pipeline end-to-end with fakes |
| `tests/test_providers.py` | Codex/Claude provider behaviour |
| `tests/test_security.py` | server auth, scoped endpoints |

## Patterns worth knowing

### Qt in tests

- Create the `QApplication` once and keep a module-level reference
  (`_APP = QApplication.instance() or QApplication([])`). If nothing holds a
  reference, Python's GC destroys the QApplication mid-test and the Qt
  runtime hard-crashes the interpreter.
- Cross-thread signals are asserted by emitting from a worker thread, then
  draining the main loop: `app.processEvents()` in a `_wait_until(pred)`
  loop until the predicate holds or a timeout expires.

### Fake speech recognition

`tests/test_voice_input.py` installs a fake `speech_recognition` module in
`sys.modules` before any code path triggers the (lazy) real import inside
`VoiceInput`. Each mic/recognizer call gets a `threading.Event` gate so
tests can deterministically interleave a stale session with a new one — this
is how the finally-block clobber race is proven fixed (the same tests fail
against the old implementation).

### Fake Agentation

`tests/test_agentation.py` replaces `client._session` with a scriptable
`FakeSession` (no sockets) for payload assertions, and uses a freshly-closed
ephemeral port for real "connection refused" offline tests.

## Evidence

The authoritative current results live in `TEST_RESULTS.md`; the gate ledger
lives in `GATES.md`.
