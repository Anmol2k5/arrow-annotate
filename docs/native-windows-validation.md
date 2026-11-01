# Native Windows UIA and capture validation

`tests/test_native_windows_capture.py::test_native_windows_frozen_context_and_physical_capture`
requires a logged-in, unlocked Windows desktop and explicit
`QT_QPA_PLATFORM=windows`. It skips on Linux and in the ordinary offscreen source
suite. Once selected on native Windows, missing UIA, an inaccessible desktop, a
blocked worker, or unavailable target text fails the test; these conditions do
not silently skip it.

Run each scale in a fresh process, after the ordinary source suite. In PowerShell:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_ACCESSIBILITY = '1'
$env:QT_SCALE_FACTOR = '1'
python -m pytest -q tests/test_native_windows_capture.py --junitxml=native-desktop-scale-1.xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:QT_SCALE_FACTOR = '1.5'
python -m pytest -q tests/test_native_windows_capture.py --junitxml=native-desktop-scale-1.5.xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

The combined test creates its own visible Qt window with a normal layout, a
`Blue button`, a harmless context label, and a synthetic password field. It
computes the source selection from `button.mapToGlobal()` and freezes ownership
while the target is exposed. Typed, pointer-sized Win32 calls independently
confirm the HWND, window rectangle, and physical source point. A different
window then covers the source point. Actual Windows UI Automation runs in a
worker while the Qt GUI thread continues processing events, with a 20-second
worker deadline. The frozen target must retain its button and context text,
exclude the password node and covering window, and omit point-element evidence
from the other HWND.

After hiding the cover, the test captures the actual desktop with
`ScreenshotService.capture_raw(None)`. It checks blue button pixels and renders
the source box into a PIL image. The changed-pixel bounds must agree with the
button's native `GetWindowRect`, transformed into the composed desktop image
using independently queried native monitor bounds. The expected button rectangle
is not obtained from the annotation mapper. Desktop images stay in memory;
report only pytest outcomes and JUnit, without screenshot uploads.

`QT_SCALE_FACTOR=1` and `1.5` exercise two imposed Qt scale factors on the runner's
available display. They do not demonstrate physical multiple monitors, negative
monitor origins, or different OS scaling on adjacent monitors. Follow
[the interactive Windows checklist](windows-interactive-testing.md) on actual
mixed-DPI hardware for those claims. This test also does not verify a frozen
application bundle, other applications' accessibility providers, microphone,
OAuth, agent handoff, or global hotkeys.

On Linux, a passing skip/collection check validates only test syntax and gating.
A successful native Windows run is required before reporting real UIA or desktop
capture validation.

## Frozen offline speech check

`test-windows-install.ps1` now performs explicit voice-test setup before its
portable and installed checks. Windows PowerShell 5.1 uses an enabled installed
English `System.Speech` voice to synthesize a 16 kHz, 16-bit mono WAV saying:

> Move the blue button below the heading and keep sixteen pixels of spacing.

The script explicitly prepares the public Whisper base weights under
`build/windows/voice-model-home/models` (cached by CI), copies them into its
isolated test data directory, and runs:

```powershell
python main.py --speech-smoke .\synthetic-english.wav .\source-speech.json
.\ArrowMCP.exe --speech-smoke .\synthetic-english.wav .\frozen-speech.json
```

The source, portable and installed checks must transcribe the real WAV in fixed
English and auto modes and preserve the button, direction, heading and sixteen
pixel requirement. Missing/corrupt input, unavailable model, native load failure,
empty/wrong transcript or only one successful language mode fails the check.
Model setup requires internet; recognition loads only local files and runs with
Hugging Face offline flags and Python socket connections disabled in that fresh
smoke process. The guard restores its environment and socket hooks afterwards.
It does not instrument native-library network syscalls.

This opt-in command includes the **synthetic transcript** and runtime errors in
its JSON report. Use the generated fixture, not private recordings, in CI. It
never opens the microphone, starts Qt or submits content to an agent. The normal
`--diagnostics` report still excludes audio/transcripts. CI uploads only speech
reports, not WAV files or model weights. Downloaded test weights are not included
in Setup or the portable ZIP.

Synthetic English TTS passing demonstrates packaged local inference, not live
microphone acquisition, natural Hinglish quality, silence handling or general
recognition accuracy. Keep those interactive results separate.

## Decoder compatibility regression

`tests/test_audio_decoder_compatibility.py` exercises Faster Whisper's real PyAV
PCM decoder without any model or network. This caught an actual PyAV 19 API change:
`av.open(metadata_errors=...)` is no longer accepted, while Faster Whisper 1.2.1
still supplies it. Speech installs constrain PyAV below 19; PyAV 18.1.0 passes the
real decoder regression. A user encountering this error should update Arrow (or
reinstall the source speech extra); downloading the voice model again does not
repair an incompatible decoder runtime. This test does not use a fake decoder.

## Recorded 0.4.1 result

[Windows run 41261023249](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41261023249)
passed the real desktop/UIA/capture test at imposed Qt scales 1 and 1.5 and real
synthetic English transcription in both fixed/auto modes through source, portable
and installed runtimes. It also passed native clipboard, frozen MCP protocol and
install/uninstall checks. These observations do not establish physical microphone,
natural Hinglish, adjacent mixed-DPI monitors or authenticated agent-session results.
