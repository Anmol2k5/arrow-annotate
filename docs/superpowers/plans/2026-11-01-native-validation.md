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
- [ ] Verify source suite, lint/types, browser tests and native CI; review and push.
- [ ] Publish a patch only after its Windows functional checks pass. Keep physical
  mic/Hinglish, mixed monitor scaling and real account sessions explicitly pending.

Boundaries: new speech smoke command is opt-in and uses synthetic test audio in CI.
Its report may include that synthetic transcript; the normal diagnostic command
continues to omit audio/transcripts. Network access is disabled during recognition
in the smoke subprocess. No provider accounts or secrets are needed for these tests.

Local verification: 636 Python tests passed, two native Windows tests skipped;
4 browser tests passed, Ruff and mypy passed. Independent review found no important
issues. Actual new native desktop/TTS/inference results are pending the pushed
Windows workflow; no success claim for these is made from Linux skips/fakes.
