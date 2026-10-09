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
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a4530786d5409e9da1ef234b268bccf686409bdb43e87e9f2269d280ebd31ea6; output-bytes=827

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
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=23c92264ae9303fdd1653bc7c4beb200f0286a17b0e5935874496347dc81a822; output-bytes=501

- [x] G6: screenshot filenames are collision-resistant under same-second and concurrent saves, and saved uploads are validated
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_screenshot_upload.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=bb44da337dda6c02c8b19156a6b55849f15850871d92c70b67a2c96eef815013; output-bytes=101

- [x] G7: crop geometry is correct for nonzero/negative monitor origins (multi-monitor)
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_crop_geometry.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=58961c51cd7c08b734aefecf8e62256f8c3718049b5c28ef7147735af109dede; output-bytes=100

- [x] G8: capture session state machine rejects invalid transitions and attaches failures to the correct capture
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_session.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=99e75346e1943fb4bf2776003e61eb0ac20b2fb2a3834663dfdf6a7d11879970; output-bytes=100

- [x] G9: voice capture uses generation-based cancellation; a stopped session cannot clobber the next session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_voice_input.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=70de5d173f1569e2b4ddedab6e04c93c2bc13112303e98073f8d65e8eb62b78e; output-bytes=101

- [x] G10: background workers never touch Qt widgets directly; stale callbacks are discarded; screenshot failure cannot wedge the session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_threading.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=f6241ecc253a2b72e5ab89d8963fa418f4b48048b0f0875d06fc4c4aca6a759a; output-bytes=101

- [x] G11: notch status methods (set_status/update_status) drive a real visible status model instead of no-ops
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_notch_status.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=1441c6f047e5b9a329a66421fcdc902715a8d17252c6d3f16ccb236a9c5815d1; output-bytes=101

- [x] G12: configuration is validated (ports, loopback binding) and read from environment with a single source of truth
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_settings.py tests/test_config.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a1679af5ca531a192b6a4c8d806f4dd301f611101276a4cc997dfb6a205ed3d9; output-bytes=101

- [x] G13: capture → store → intent → provider end-to-end flow works with Agentation offline degrading gracefully
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_orchestrator.py tests/test_providers.py tests/test_agentation.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=4f5dd5940e185f6a1d0ec2c31f6e61ce9df288a9a32a4a433db7d12d860835ac; output-bytes=101

- [x] G14: scoped short-lived screenshot share tokens let an approved consumer fetch a shared capture and reject expired/foreign tokens
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_share_tokens.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=414202a270a592a6d66041f686b6160d762c6ae9395d9ce5b49f469fd187a069; output-bytes=101

- [x] G15: documentation set exists and matches the implementation
  CHECK: node scripts/verify-docs.mjs
  EXPECT: docs verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a0b8a56b9e9cb377e1fea7fae83d4d29732b8b0c504e680f2cb1a3871fed8f8a; output-bytes=25

- [x] G16: GitHub Actions CI workflow runs install, lint, typecheck and tests on a Windows runner
  CHECK: node scripts/verify-ci.mjs
  EXPECT: ci verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=3854f9438c6d2794b7bd0919dd904c22c7d14899860815de67abdb264edec66e; output-bytes=23

- [ ] G17: end-to-end GUI capture flow exercised on a real Windows desktop session
  EVIDENCE: pending
