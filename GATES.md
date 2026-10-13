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
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=c2fcfc54e002e1a8b7d92c2519d141568667b88ea604291c77b7081b653a7f0b; output-bytes=827

- [x] G2: ruff lint clean on repository
  CHECK: .venv\Scripts\python.exe -m ruff check .
  EXPECT: All checks passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18; output-bytes=19

- [x] G3: mypy type-checks the arrow package with no errors
  CHECK: .venv\Scripts\python.exe -m mypy arrow
  EXPECT: Success: no issues found
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=834bd60a61a94c70e823fa5a870573323bf86c82ad389ccd0ae9946d8df46746; output-bytes=1586

- [x] G4: browser extension JS and manifest are syntactically valid
  CHECK: node scripts/verify-extension.mjs
  EXPECT: extension verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a746dec08bc1bd6f531b4c99fbca195f5524872d1f26ec5c515a973185b176fa; output-bytes=30

- [x] G5: unauthenticated and wrongly-authenticated access to private screenshot/context endpoints is rejected while authorized access works
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_security.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=ed769f3f712fe9024df7656e4ea9168bbd0b5aca9a4676a4ed0c72d8020d75b5; output-bytes=501

- [x] G6: screenshot filenames are collision-resistant under same-second and concurrent saves, and saved uploads are validated
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_screenshot_upload.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=7459f74aa300a1c045227164de601adbfea480691a6db666d304d32bbb4000e9; output-bytes=101

- [x] G7: crop geometry is correct for nonzero/negative monitor origins (multi-monitor)
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_crop_geometry.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=4a7a681458c41df32870635250738c8dbabc6038c8e530a18d9ddbe5c0bc3698; output-bytes=100

- [x] G8: capture session state machine rejects invalid transitions and attaches failures to the correct capture
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_session.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=69e797f3800e0698e8427bc7eea8af3cbe63664e093989099c3f9b4996127200; output-bytes=100

- [x] G9: voice capture uses generation-based cancellation; a stopped session cannot clobber the next session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_voice_input.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=52fdf12ef24ea82daf9c1b072f37d739d37d06b35d33efb660d1a7dd27e7b7ae; output-bytes=101

- [x] G10: background workers never touch Qt widgets directly; stale callbacks are discarded; screenshot failure cannot wedge the session
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_threading.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=0ba0b5338040ae1904192dfff69a6afe8b469a10336b84706d09f6b43eadc1e5; output-bytes=101

- [x] G11: notch status methods (set_status/update_status) drive a real visible status model instead of no-ops
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_notch_status.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=8b7aa674210f048f6461ff98d81b4e00cab5f8ea36e25a51305a1d2d266d93a7; output-bytes=101

- [x] G12: configuration is validated (ports, loopback binding) and read from environment with a single source of truth
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_settings.py tests/test_config.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=1ef450ce4094e7fc0fd00d683855d5925a378a6b3e62bfbf448666cbd518eb18; output-bytes=101

- [x] G13: capture → store → intent → provider end-to-end flow works with Agentation offline degrading gracefully
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_orchestrator.py tests/test_providers.py tests/test_agentation.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=c9be1cc22aee9b2c4e3067eae9d29362bba770c0098d68f5219a0ffa8e5be6c0; output-bytes=101

- [x] G14: scoped short-lived screenshot share tokens let an approved consumer fetch a shared capture and reject expired/foreign tokens
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_share_tokens.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=62bc3f799dd58271b7d374b539674087d4954b3f0b8770e5208ba789fedad2c5; output-bytes=101

- [x] G15: documentation set exists and matches the implementation
  CHECK: node scripts/verify-docs.mjs
  EXPECT: docs verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=a0b8a56b9e9cb377e1fea7fae83d4d29732b8b0c504e680f2cb1a3871fed8f8a; output-bytes=25

- [x] G16: GitHub Actions CI workflow runs install, lint, typecheck and tests on a Windows runner
  CHECK: node scripts/verify-ci.mjs
  EXPECT: ci verification passed
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=3854f9438c6d2794b7bd0919dd904c22c7d14899860815de67abdb264edec66e; output-bytes=23

- [x] G18: Escape cancels an active capture without emitting a selection, and a duplicate finish trigger emits selection_complete exactly once
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_overlay_cancel.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; shell=C:\WINDOWS\system32\cmd.exe; cwd=D:\projects\bluely; path=f77c8548f2cb/56 entries; EXPECT=matched; output-sha256=6a44ac67f3984606178c8277ebbfd551311e0a64d71d16847a2ce984d7fbbb13; output-bytes=100

- [ ] G17: end-to-end GUI capture flow exercised on a real Windows desktop session
  EVIDENCE: partial. Verified on 1920x1080 / 125% scaling: app launch, notch
    rendering, notch stays above the foreground app (z-index 2 of 23), hover
    expansion ((909,10,100,40) -> (484,10,950,759) = 760x560 logical x 1.25),
    hover collapse, task shelf rendering, and packaged-exe launch. NOT
    verified: the click->capture round trip, a populated shelf on screen, the
    agent pointer watched moving, the Allow/Deny panel displayed, and the
    global hotkey (synthetic key events did not trigger it here; cause
    unknown, needs a human press). G17 stays open until a human completes the
    capture round trip.

- [x] G19: Point Mode tears the overlay down on the GUI thread before the
  worker screenshots, so the capture cannot contain Arrow's own overlay
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_point_lifecycle.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 19 passed; proven red-capable (moving the worker dispatch
    ahead of teardown turns 4 tests red)

- [x] G20: an unresolved point target is reported as a fallback, never as a
  detected element, and never fabricates an identity
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_point_mode.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 19 passed; asserts resolution_method=fallback with
    confidence_kind=none and element=None

- [x] G21: task bundles persist, order, edit and export valid JSON and Markdown
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_tasks.py tests/test_point_task_integration.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 37 passed; includes restart persistence and the
    capture-history-survives-task-deletion rule

- [x] G22: an existing MCP client can retrieve a task and see its screenshots
  as real image content
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_mcp_tasks.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 21 passed. Additionally verified against a REAL Claude
    Code 2.1.205 client (claude mcp list reported "Connected") and a REAL
    stdio JSON-RPC round-trip to a separate server process, whose image block
    decoded to a valid PNG signature.

- [x] G23: no agent action executes without a live, matching, unexpired,
  single-use approval bound to its target and foreground window
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_agent_actions.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 41 passed; covers deny, expiry, changed window, moved and
    vanished target, Stop, 8-thread double-fire race, and command injection

- [x] G24: agent endpoints are refused unless the user opted in, and refuse
  rather than pretend when no desktop is attached
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_agent_pointer_integration.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 35 passed; 401 without a token, 403 without
    CONTROL_NATIVE, 503 with no desktop, 409 on a refused decision

- [x] G25: the task shelf fits inside the notch window and is not clipped
  CHECK: .venv\Scripts\python.exe -m pytest -q tests/test_task_shelf.py
  EXPECT: /^\d+ passed/m
  EVIDENCE: exit=0; 33 passed. Found on a real 125%-scaled desktop: the
    footer was clipped at the bottom and '+ Task' overflowed the right edge.
    Both fixed; regression tests pin the shelf height and assert every
    control ends inside the shelf.

- [x] G26: a Windows distributable builds and launches
  CHECK: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean arrow.spec
  EXPECT: dist/ArrowAnnotate/ArrowAnnotate.exe exists and launches
  EVIDENCE: exit=0; 9.7 MB exe in a 342 MB folder; launched and stayed
    running; ships no database or asset directories, because all user data
    resolves through ARROW_HOME. NOT code-signed, and tested on one machine
    only.
