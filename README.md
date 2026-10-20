# Arrow Annotate

Local-first spatial-context tool for coding agents.

## Install on Windows

The installer bundles Python and the app's dependencies. Windows 10/11 x64 users
can run `Arrow-Annotate-Setup-<version>-x64.exe`, install for their own account,
and launch **Arrow Annotate** from Start. Hold **Ctrl+Space** to draw and speak;
release to capture. The system tray provides settings, a quick guide, and Quit.

Installer builds and a portable ZIP are produced by the
[Windows installer workflow](https://github.com/Anmol2k5/arrow-annotate/actions/workflows/windows-installer.yml).
Open a successful run and download its Windows artifact; extract it before
running Setup. A native Windows build must pass before an installer is ready to
share. Settings and captures remain in `%USERPROFILE%\.arrow` after upgrades
or uninstall. Codex/Claude CLI installation and sign-in are optional separate steps.

See [installer and distribution instructions](docs/windows-installer.md) for
portable use, browser extension setup, installed MCP configuration, and building
an installer locally.

## Run from source on Windows

The desktop application requires Windows for UI Automation, global hotkeys, and
native OS control. Use Python 3.12:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python main.py
```

Microphone input requires a working recording device. Speech recognition uses
Google's speech service. Agentation at `http://127.0.0.1:4747` is optional;
captures remain available through MCP and direct providers when it is offline.

## Capture and send

Hold **Ctrl+Space**, draw around the source (and optionally a destination), and
speak your complete instruction. Release either shortcut key to finish. Speech
pauses do not end the capture. Arrow captures the screen immediately on release,
then waits for transcription before showing the saved card. **Esc** cancels.
The capture button also starts a session; use **Done** or **Enter** to finish it.

Open the notch and select **⚙ Capture settings** to change the held shortcut and
speech language. **Ctrl+Shift** works as a two-key alternative. Fn is usually
handled by keyboard firmware, so it cannot be registered reliably. Preferences
persist across restarts. If a chord conflicts with another application, choose
another one in settings.

Each card offers **Copy image + prompt**, **Image only**, **Prompt only**,
**Codex**, and **Claude Code**. The combined clipboard includes actual annotated
image pixels and prompt text. Some destination apps paste just one format; use
the two separate copy buttons in that case. Select a repository with **📁** before
direct sending. Install and sign in to the chosen CLI separately, then restart
Arrow if PATH changed. Codex receives an image attachment; Claude receives the
image in its stream input. Existing screenshots captured before this update
retain their original pixels; make a new capture to test the drawing fix.

## Linux development and MCP

Linux supports the test suite, headless Qt checks, and the MCP stdio server.
`main.py` intentionally rejects Linux. Windows UI Automation and PyAudio are
installed only on Windows.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
mkdir -p /tmp/arrow-dev
export ARROW_HOME=/tmp/arrow-dev
export ARROW_DB_PATH=/tmp/arrow-dev/arrow.db
export QT_QPA_PLATFORM=offscreen
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check arrow main.py
.venv/bin/python -m mypy arrow main.py
node --test tests/browser_extension.test.cjs
```

Start MCP from the repository directory with the same runtime variables:

```bash
.venv/bin/python -m arrow.mcp.server
```

The client owns this process and exchanges newline-delimited JSON-RPC over
stdio. Screenshots and UI Automation tools still need an actual desktop.

## Browser bridge

Load `browser_extension/` as an unpacked Chrome extension. In its popup, load the
bearer token from `ARROW_HOME/token` (default: `~/.arrow/token`). The bridge
connects to port 5002. Reload the extension after updating its files or manifest.
The `scripting` permission lets React metadata inspection run in the page's
JavaScript world; DOM inspection remains in the isolated content script.

Codex runs use its `workspace-write` sandbox and attach the annotated screenshot.
Claude Code uses the configured permission mode. Arrow does not intercept a
child agent's individual tool calls; Claude's permissions remain CLI-controlled.
