# Arrow Annotate

Local-first spatial-context tool for coding agents.

## Install on Windows

The installer bundles Python and the app's dependencies. Windows 10 (1809+) / Windows 11 x64 users
can run `Arrow-Annotate-Setup-<version>-x64.exe`, install for their own account,
and launch **Arrow Annotate** from Start. Hold **Ctrl+Space** to draw and speak;
release to capture. The system tray provides settings, a quick guide, and Quit.

Installer builds and a portable ZIP are produced by the
[Windows installer workflow](https://github.com/Anmol2k5/arrow-annotate/actions/workflows/windows-installer.yml).
Open a successful run and download its Windows artifact. Extract it and run
`dist/artifacts/Arrow-Annotate-Setup-<version>-x64.exe`. A native Windows build must pass before an installer is ready to
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
.venv\Scripts\python -m pip install -e ".[dev,speech]"
.venv\Scripts\python main.py
```

Microphone input requires a working recording device. In **Settings → Capture →
On-device voice**, download the multilingual Whisper base model once (about
150 MB). Recognition then runs on this device, without uploading audio or fetching
weights during a capture. No account or cloud API key is required by Arrow.
Typed instructions work without a model or microphone. Optional Agentation
forwarding is disabled unless `ARROW_AGENTATION_ENABLED=1` is explicitly set.

## Capture and send

Arrow rests as a slim rounded pill at the top center of the primary screen.
Hover or click it to expand captures and settings. A compact blue waveform
indicates recording; leaving the expanded panel collapses it unless it is pinned
or settings are being edited.

Hold **Ctrl+Space**, draw around the source (and optionally a destination), and
speak your complete instruction. Release either shortcut key to finish. Speech
pauses do not end the capture. Arrow captures the screen immediately on release,
then waits for transcription before showing the saved card. **Esc** cancels.
The capture button also starts a session; use **Done** or **Enter** to finish it.
You can type in the overlay instead of speaking; typed instructions take priority.
Each selected window contributes its accessible text where available. Password
controls are excluded; inaccessible or bounded text is marked unavailable/partial.

The first stroke gets a red **1 Source** box; the second gets a green
**2 Destination** box and a connecting arrow. These markers appear in both the
overlay and the saved image. Two clearly closed, separated loops joined by a
line can also identify source and destination in one continuous stroke. If the
gesture is ambiguous, draw the two regions separately. Move requests without a
destination ask for clarification in the copied prompt.

Open **⚙ Settings** in the notch. Settings stay inside the notch, with
**Capture**, **Agents**, and **General** tabs. Capture changes the held shortcut
and speech language. **Ctrl+Shift** works as a two-key alternative. Fn is usually
handled by keyboard firmware, so it cannot be registered reliably. Preferences
persist across restarts. If a chord conflicts with another application, choose
another one in settings.

For ChatGPT, click **Copy image + prompt**, paste to attach the image, then click
**2 · Copy prompt** and paste again. The clipboard changes only when you click;
there is no timed overwrite. **General → Clipboard** also offers combined copying
for apps that accept image and text together. Windows receives actual PNG image
data, not a screenshot path. **Image only** and **Prompt only** remain available.

In **Settings → Agents**, open the install guide if a CLI is missing, then choose
**Connect** for Codex or Claude Code. Finish the official sign-in in its browser
or CLI window; Arrow checks the result and shows **Connected** only when confirmed.
**Refresh connections** detects newly installed CLIs and retries status checks.
Choose your project repository in the same tab, then use **Codex** or **Claude
Code** through **Open in agent**. Codex receives an image attachment; Claude
receives access to the immutable context bundle and images through MCP/local files.
Arrow does not store account credentials. The connected agent has its own account
and data-processing policy.

**Agents → Local MCP and REST** shows the shared local endpoint and copies an
HTTP MCP connection configuration. Existing stdio clients still work. See the
[local endpoint guide](docs/local-context-api.md) for Claude/Codex commands and REST.

**General** also controls automatic expansion for capture updates and keeping
the notch open. Existing screenshots retain their original pixels; make a new
capture to test drawing changes. Draw source and destination as separate mouse
strokes when a continuous gesture is ambiguous.

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

## Visible agent handoff (0.2)

Capture cards now offer one client selector and **Open in agent**. Codex/Claude
Code open visible interactive sessions with a capture-ID bundle and per-session
MCP configuration. VS Code supports its documented agent draft link. Codex desktop
opens the workspace and copies context for manual paste; unsupported prefill is
not reported as completed. Desktop login/focus behavior still needs testing on
an installed user's Windows machine.

See [current architecture](docs/current-architecture.md) and the
[local Heyclick audit prompt](docs/local-heyclick-audit-prompt.md). The reference
Supamaus site was blocked by the cloud proxy, so exact product parity is unverified.
