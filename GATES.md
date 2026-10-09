# Gates: Arrow Annotate prelaunch hardening

OWNS: arrow/**, tests/**, browser_extension/**, docs/**, README.md, AUDIT_REPORT.md, IMPLEMENTATION_REPORT.md, TEST_RESULTS.md, .env.example, .gitignore, pyproject.toml, requirements.txt, .github/**, main.py

Scope: take Arrow Annotate from the audited partial state to a verified, hardened, production-ready Windows desktop app — security, threading, capture correctness, integrations, UI/UX, tests, docs.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node "C:\Users\Mayur\.agents\skills\unlazy\scripts\gate-lint.mjs" GATES.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=d6d0b1681353280410d607ab28582f3dc1775651fe69d8f072acd75d657296c9; output-bytes=151

- [x] G1: full python test suite passes
  CHECK: .venv\Scripts\python.exe -m pytest -q
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=2aade03fe2a74ee1662756a1202cf15b845f5946e09ee82046f1812da29ae707; output-bytes=827

- [x] G2: ruff lint clean on repository
  CHECK: .venv\Scripts\python.exe -m ruff check .
  EXPECT: All checks passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18; output-bytes=19

- [x] G3: mypy type-checks the arrow package with no errors
  CHECK: .venv\Scripts\python.exe -m mypy arrow
  EXPECT: Success: no issues found
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=d118a4201f267325695bdc581e6b10cc8bd325c8bd311be8db6a62db052e092f; output-bytes=45

- [x] G4: browser extension JS and manifest are syntactically valid
  CHECK: node scripts/verify-extension.mjs
  EXPECT: extension verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a746dec08bc1bd6f531b4c99fbca195f5524872d1f26ec5c515a973185b176fa; output-bytes=30

- [x] G5: unauthenticated and wrongly-authenticated access to private screenshot/context endpoints is rejected while authorized access works
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_security.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=fb40b1ffdb43e82beb4efb686faa9a119ad6b4a9185efe2c3c19230b4b7e1aaf; output-bytes=501

- [x] G6: screenshot filenames are collision-resistant under same-second and concurrent saves, and saved uploads are validated
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_screenshot_upload.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=025d9328ad9710bdf4e6d6a351c65c6600fab978c52f64379bdbf3c4608e9adb; output-bytes=101

- [x] G7: crop geometry is correct for nonzero/negative monitor origins (multi-monitor)
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_crop_geometry.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=b0fece4589e3ff9bf3abb8bcfea9cca418616cbafd3cb09c837e34e6b8bff584; output-bytes=100

- [x] G8: capture session state machine rejects invalid transitions and attaches failures to the correct capture
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_session.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=faba4362ed858461c9928ec7f97b0e4aa1fa7073e972d94c2f65bf19010404bd; output-bytes=100

- [x] G9: voice capture uses generation-based cancellation; a stopped session cannot clobber the next session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_voice_input.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=77e9653a0dac9c9f63469a6d07127eaf468c9d487a52b7291da4aefa8bc3019b; output-bytes=100

- [x] G10: background workers never touch Qt widgets directly; stale callbacks are discarded; screenshot failure cannot wedge the session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_threading.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=051fa8acf6c07dbcbb716f26836d309322473ec2ceb565ef1add3b1238c0a638; output-bytes=101

- [x] G11: notch status methods (set_status/update_status) drive a real visible status model instead of no-ops
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_notch_status.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=20eaa3d825cec28147bbae84843b788556bdd6a2e88ff5ca5fbf1bd4bd524d56; output-bytes=101

- [x] G12: configuration is validated (ports, loopback binding) and read from environment with a single source of truth
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_settings.py tests/test_config.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=b370d921997c772ebc63c570ad85ca7d574a7eba9da8bb821438a0db81369149; output-bytes=101

- [x] G13: capture → store → intent → provider end-to-end flow works with Agentation offline degrading gracefully
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_orchestrator.py tests/test_providers.py tests/test_agentation.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=24dcfe410010ca8142c67744cc8b6a283dce69f7e0cb4fdb25f2237e224edb8f; output-bytes=101

- [x] G14: scoped short-lived screenshot share tokens let an approved consumer fetch a shared capture and reject expired/foreign tokens
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_share_tokens.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=37122cc0b624fc2975720da509c68eb8e36bbe769b62bd1161b8bf662d43ebdf; output-bytes=101

- [ ] G15: documentation set exists and matches the implementation
  CHECK: node scripts/verify-docs.mjs
  EXPECT: docs verification passed
  EVIDENCE: pending

- [ ] G16: GitHub Actions CI workflow runs install, lint, typecheck and tests on a Windows runner
  CHECK: node scripts/verify-ci.mjs
  EXPECT: ci verification passed
  EVIDENCE: pending

- [ ] G17: end-to-end GUI capture flow exercised on a real Windows desktop session
  EVIDENCE: pending
