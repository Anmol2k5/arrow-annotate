# Native Windows validation follow-up

User instruction: keep working on the remaining Windows validation after 0.4.0.
Extend the existing app/CI; do not claim physical microphone or multiple-monitor
validation from a synthetic runner test. Preserve installer data and existing
voice privacy (no network inference, model download only explicit setup).

- [x] Reproduce/fix the empty-instruction review error with a focused UI test.
- [x] Add a WAV speech smoke command that exercises the actual offline runtime,
  validates synthetic instruction content, and writes clear success/failure evidence.
- [x] Generate synthetic English speech on Windows, explicitly install/cache model
  weights, and exercise the portable/installed frozen runtime in fixed and auto modes.
- [x] Add a real Windows Qt/UIA/screenshot test at scale factors 1 and 1.5, checking
  frozen target ownership after an overlay appears and marker/image alignment.
- [x] Verify source suite, lint/types, browser tests and native CI; review and push.
- [ ] Publish a patch only after its Windows functional checks pass. Keep physical
  mic/Hinglish, mixed monitor scaling and real account sessions explicitly pending.

Boundaries: new speech smoke command is opt-in and uses synthetic test audio in CI.
Its report may include that synthetic transcript; the normal diagnostic command
continues to omit audio/transcripts. Network access is disabled during recognition
in the smoke subprocess. No provider accounts or secrets are needed for these tests.

Local verification after the decoder fix: 637 Python tests passed, two native Windows tests skipped;
4 browser tests passed, Ruff and mypy passed. Independent review found no important
issues. Actual new native desktop/TTS/inference results are pending the pushed
Windows workflow; no success claim for these is made from Linux skips/fakes.

First native run [41260195577](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41260195577)
passed real desktop/UIA/capture checks at both imposed Qt scales and built the
installer. The new real source speech check then failed in both language modes:
PyAV 19.0.2 removed `av.open(metadata_errors=...)`, still used by faster-whisper
1.2.1. This was independently reproduced locally with its real decoder and a
small PCM WAV, without weights/network. The same regression passes with PyAV
18.1.0. The speech extra now constrains PyAV below 19, and a model-free native
PCM-decoder test catches this incompatibility in the ordinary source suite.
Corrected run [41261023249](https://github.com/Anmol2k5/arrow-annotate/actions/runs/41261023249) passed actual synthetic-WAV transcription in English and auto modes through source, portable and installed runtimes, real desktop/UIA/capture checks at Qt scale 1 and 1.5, native PNG clipboard, frozen MCP protocol, and install/uninstall/data preservation. This validates synthetic English inference, not physical microphone or natural Hinglish accuracy.
