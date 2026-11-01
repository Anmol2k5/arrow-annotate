# Windows upgrade preservation validation

Run the published 0.4.1 installer, then the candidate installer into the **same installation directory**. Use a fresh, isolated `ARROW_HOME` throughout. The installer test must verify the downloaded published installer against its trusted SHA-256 before executing it. Keep any running Arrow process closed while replacing its installation.

The repository helper exposes these commands (reports must be outside `HOME`):

```powershell
python scripts/windows_upgrade_smoke.py seed "$DataDir" --report "$Reports/upgrade-seed.json"
python scripts/windows_upgrade_smoke.py check "$DataDir" --mcp-executable "$InstallDir/ArrowMCP.exe" --expected-version 0.4.1 --report "$Reports/upgrade-before.json"
# Install the candidate into the SAME $InstallDir, using the SAME $DataDir.
python scripts/windows_upgrade_smoke.py check "$DataDir" --mcp-executable "$InstallDir/ArrowMCP.exe" --expected-version 0.4.2 --report "$Reports/upgrade-after.json"
```

Set `$env:ARROW_HOME = $DataDir` for both desktop launches. The helper sets `ARROW_HOME` and `ARROW_DB_PATH` explicitly for its own MCP subprocesses. Perform the real desktop lifecycle checks against the old installation and again after upgrading; helper success alone does not establish GUI startup or shutdown behavior.

`seed` refuses a nonempty directory, including any existing configuration or database. It creates only public synthetic data: a valid PNG, a selected repository folder containing spaces and non-ASCII characters, nondefault capture and UI preferences, and one saved capture. The capture has different original speech and edited instruction text, persisted annotations, window text, selected repository context, and image assets. Its schema is frozen in `tests/fixtures/upgrade_0_4_1.sql`, copied from released `v0.4.1:arrow/storage/migrations.py` migrations 1–3 with SQLite `user_version = 3`. Fixture construction never imports current migrations or current `CaptureStore`, which could otherwise hide an upgrade regression. Its row/context format matches released `CaptureStore.add`.

`check` requires the fixture marker and exact saved preferences, including `ctrl+shift`, `hi-IN`, combined clipboard mode, disabled automatic expansion, pinned notch, and the existing selected repository. It opens the SQLite database read-only for integrity, foreign key and semantic record checks, verifies the saved PNG SHA-256, then starts the **actual installed `ArrowMCP.exe`** with no mode flag. It verifies `--version`, performs JSON-RPC `initialize` and `tools/call` for `arrow_get_capture_bundle`, and compares returned original speech, current instruction, annotations, window context, request, repository, context JSON and image bytes against the expected fixture. It checks storage again afterward. Added bundle assets and newer schema columns are allowed; metadata loss, a missing repository, changed shortcut or voice, missing capture, corrupt image or incorrect executable version fails with exit code 1 and a JSON failure report.

The seed report records expected preferences, semantic capture fields, image path and image SHA-256. The checks compare semantic data rather than the database file hash, because building an MCP bundle legitimately adds asset rows. Reports contain synthetic fixture content only; do not run this helper against real user data. The checked-in tests run the real source MCP stdio server through `main.py --mcp`, while the installer workflow must exercise both installed executables. This MCP storage roundtrip does not establish an authenticated Codex or Claude Code session or account integration.
