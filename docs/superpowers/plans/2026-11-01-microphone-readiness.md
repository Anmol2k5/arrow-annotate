# Microphone Readiness Implementation Plan

> **For agentic workers:** Use test-driven implementation and fresh final review;
> keep independent backend and UI edits in disjoint files.

**Goal:** Make actual Windows microphone/Hinglish testing available inside the notch.
**Architecture:** Existing production VoiceInput owns recording and local decoding.
A small MicrophonePanel reuses it with isolated transient results; settings store
stable input descriptions. No additional recognition service or dependency.
**Tech stack:** Python, PyQt6, PyAudio, SpeechRecognition, local Faster Whisper.
**Spec:** ../specs/2026-11-01-microphone-readiness-design.md

## Global constraints
- Preserve hold/release capture, offline inference and current settings.
- Only explicit Test opens a microphone; Refresh only enumerates inputs.
- Never save test audio or send test transcripts to an agent/clipboard.
- Do not label inventory or mocked audio as real hardware/Hinglish verification.

## Review focus
- USB device indices change; resolve saved name/host API uniquely each time.
- Duplicate device names, unplugged input and permission errors are actionable.
- Cancel/close/real capture suppress stale test results and microphone overlap.
- Real stream failures differ from silence and missing runtime.
- Test transcription is plain text, transient and independent of capture state.

## Task 1: Device selection and production voice feedback
Files: arrow/speech/microphone.py; arrow/storage/settings.py;
arrow/ui/voice_input.py; tests/test_microphone.py; tests/test_voice_lifecycle.py.
Interfaces: list_input_devices() -> list[dict] with index/name/host_api/ambiguous;
resolve_input_device(selection: dict|None) -> int|None;
get_microphone_selection()/set_microphone_selection(selection: dict|None).
VoiceInput(language='auto', *, microphone_selection=<saved default>) accepts an
explicit None for System default. audio_level(float 0..1, capture_id) and opening
phase are generation guarded; finished/result/recording semantics stay intact.
- [x] Write and observe failing input filtering, index reorder, duplicates,
  saved-settings, error categorization, levels, silence and stale-event tests.
- [x] Implement the backend using PyAudio input inventory and bounded device lock.
- [x] Run backend tests and existing lifecycle tests; address failures at source.

## Task 2: Inline microphone panel
Files: arrow/ui/microphone_panel.py; arrow/ui/settings_panel.py; arrow/app.py;
arrow/capture/coordinator.py; tests/test_microphone_panel.py.
Interfaces: MicrophonePanel(language: Callable[[],str], parent=None),
can_start_test: Callable[[],bool], cancel_test(). Integrate as microphone_panel
in SettingsPanel. App supplies coordinator busy guard and cancels test before a
normal capture. Opening phase updates production notch status.
- [x] Write and observe failing real Qt tests for inventory, saved selection,
  test phases/levels/transcript, Stop/Cancel/timeout/stale events/navigation/quit.
- [x] Implement ten-second bounded explicit test with production VoiceInput.
- [x] Verify typed/normal captures remain independent and no test persists data.

## Task 3: Verify, review and distribute
- [x] Run full Python suite, Ruff, mypy, browser tests and dependency check.
- [x] Fresh review and meaningful regressions for important findings.
- [x] Document real Windows microphone/Hinglish checks and limitations.
- [ ] Push versioned changes; require native Windows installer/lifecycle/upgrade
  and speech checks before publishing a testable installer.

## Implementation record

Implementation choices: retain normal hold recordings without a duration limit;
bound only the explicit test in both recorder and UI. Preserve descriptors and
fail on ambiguous input names. Cancel testing before any coordinator start and
when navigating away, independent of whether Qt delivered a child hide event.

Review fixes: actual SpeechRecognition suppresses stream-open exceptions; the
recorder opens and closes its native stream explicitly. Final input resolution
uses the SAME live PortAudio instance as stream opening, preventing USB hotplug
from switching to another microphone between inventory and open. Native host
errors include Windows microphone privacy guidance without asserting a cause.
Regression tests first reproduced wrong-input opening and missing guidance, then
passed with the fixes. Real physical input and mixed-language accuracy remain
unverified until the user runs the explicit Windows test.

Source verification: 746 Python tests passed, 3 native Windows tests skipped on
Linux. Four browser tests, Ruff, mypy and dependency consistency passed.
[Native Windows run 23](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41323375364)
passed source tests, native clipboard/UIA, frozen/installed synthetic English
speech, desktop tray relaunch, actual released-installer upgrade and preservation.
Device inventory/stream unit tests use mocked PortAudio, not a physical mic.
