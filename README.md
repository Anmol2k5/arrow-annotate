# Arrow Annotate

Local-first spatial-context tool for coding agents. Draw an annotation on a
screenshot of any screen region, add a voice or typed instruction, and hand
the result to a coding agent (Agentation, or the built-in Codex/Claude
providers) with the exact coordinates, window, and context it needs.

Screenshots and metadata are stored locally. Voice transcription can use Google's speech-recognition service when enabled; other network traffic may include:

- the optional local Agentation bridge (`http://127.0.0.1:4747` by default),
- short-lived, single-image share links minted for approved consumers,
- your chosen coding provider, invoked as a local CLI.

## Prerequisites

PyAudio requires system-level PortAudio headers before `pip install` will
succeed on some platforms:

```
# Linux
sudo apt install portaudio19-dev

# macOS
brew install portaudio
```

Windows: no extra system dependencies.

## Install

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
python main.py
```

Copy `.env.example` to `.env` to override defaults (ports, Agentation URL,
loopback binding). Non-loopback hosts are rejected unless
`ARROW_ALLOW_NON_LOOPBACK=1` is set.

## Usage

Arrow has two capture modes. **Ctrl+Shift+Space** launches whichever mode is
currently selected; the notch's **Capture** and **Point** buttons set it.

### Point mode — one click is one capture

- Click **⊙ Point**, then click any element on screen.
- That single click completes the capture: the overlay closes, the screenshot
  is taken with the overlay already hidden, and a card appears in the notch.
- Arrow resolves the element through Windows UI Automation (and OCR where UIA
  finds nothing), crops to its real bounds, and records the resolution method
  and confidence.
- Click **⊙ Point** again to add another capture. Related captures are grouped
  into a task bundle so they can be sent to an agent together.
- If a capture is still processing, the notch says so rather than silently
  dropping the previous one.
- When no element can be identified, Arrow still saves a crop around the click
  and records the target as `fallback` with no confidence — it never reports a
  guess as a detected element.
- Press **Esc** to cancel. Finishing without clicking cancels rather than
  saving a full-screen screenshot.

### Annotate mode — freehand regions

- Click **✦ Capture** (or press **Ctrl+Shift+Space**), then draw a source
  region; draw a second stroke for an optional destination. A blue gesture
  trail follows the pointer and fades over about 3 seconds, while the
  red/green source/destination marks remain until you finish.
- Press **Ctrl+Shift+Space** again or **Ctrl+Shift+Enter** to finish;
  press **Esc** to cancel the capture without taking a screenshot.
  Starting without drawing any stroke and finishing captures the full
  screen; cancelling never does.

### Tasks — grouping several captures

- Click **+ Task**, then take captures as normal. They are grouped into one
  task in the order you made them.
- **Copy task** puts the task on your clipboard as Markdown an AI agent can
  read, including the instruction, each capture's app/window, the target
  resolution method, and screenshot paths.
- Tasks persist across restarts. Deleting a task keeps the captures and their
  screenshot files.
- A task stays `draft` until an agent actually works on it — Arrow never shows
  "sent to AI" just because a file exists.

### Sharing a task with an existing AI agent

Register Arrow's MCP server once, then ask your agent for it:

```powershell
claude mcp add arrow -- .\.venv\Scripts\python.exe -m arrow.mcp.server
```

Then, in an existing Claude Code session: *"Read my latest Arrow task and
implement the requested change."* The agent pulls the task manifest and calls
`arrow_get_capture_image` to actually see each screenshot. This is a
handoff into your **existing** session — it does not start a new CLI process.
See [`docs/claude-mcp-setup.md`](docs/claude-mcp-setup.md) and
[`docs/codex-mcp-setup.md`](docs/codex-mcp-setup.md).

### Both modes

- Voice recognition starts during capture when available; it uses Google
  speech recognition by default, which requires a network connection.
  Unrecognized speech no longer ends the capture. You can instead edit
  the instruction on the resulting screenshot card.
- The notch shows captured images. **Edit** or **Copy** a compiled request,
  or select **Codex**/**Claude Code** when the matching local CLI is installed.
The app currently also attempts to hand completed captures to Agentation
at `ARROW_AGENTATION_URL` (default `http://127.0.0.1:4747`); that optional
integration may report offline while local screenshots remain available.

The companion browser extension lets you annotate live web pages the same
way; captures flow through the same local pipeline.

## Letting an agent point at your screen

Arrow can animate a blue pointer at an element so an agent can show you where
it means, and — only with your explicit approval — perform one bounded action.

**This is off by default.** The agent endpoints require an opt-in capability:

```env
# .env
ARROW_ENABLED_CAPABILITIES=control_native
```

Until you set that, `/agent/preview` and `/agent/action` return 403 and an
agent cannot draw a pointer or ask for anything. With it enabled:

- `arrow_preview_target` moves the pointer. It **never** clicks.
- `arrow_request_action` raises an Allow/Deny prompt and returns
  `awaiting_approval`. Nothing happens until you decide.
- Allow is **single use and expires in 45 seconds**. It is bound to one
  action, one target and the foreground window at the time you approved it.
- Deny, Stop, an expired approval, a changed window, or a target that can no
  longer be identified all execute **nothing**.
- `arrow_stop_agent` cancels everything pending immediately.

Arrow has no arbitrary-command path: action payloads carrying `command`,
`shell` or `args` are refused. See [`docs/security-review.md`](docs/security-review.md).

## Documentation

## Browser extension setup

1. Open `chrome://extensions`, enable Developer mode.
2. Click "Load unpacked" and select the `browser_extension/` directory.
3. The popup walks you through pairing: it connects only to loopback
   (`127.0.0.1` / `localhost`) on the configured port, authenticates with a
   token from the desktop app, and shows live connection state
   (connecting / authenticating / connected / auth failed / server
   unavailable). If you changed `ARROW_WS_PORT`, enter the same
   `ws://` URL in the popup's "Bridge URL" field — non-loopback
   addresses are rejected.
4. The extension requests `activeTab`, `storage` and `scripting`; its host
   permissions are loopback-only. Page access is optional and per-site: click
   "Allow access to this site" in the popup for sites you want to annotate.

## Building a Windows executable

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean arrow.spec
```

Produces `dist\ArrowAnnotate\ArrowAnnotate.exe` (ship the whole folder).
User data stays under `ARROW_HOME`, never beside the binary, so it is safe to
install under Program Files. See
[`docs/building-windows.md`](docs/building-windows.md).

## Privacy

- No telemetry, no analytics, no third-party servers.
- All user data lives under `ARROW_HOME` (default `~/.arrow`): screenshots in
  `screenshots/`, the SQLite database (`arrow.db`) holds capture metadata only,
  and generated context sits in `captures/`. On first start after upgrading, a
  database previously kept in the checkout is moved into `ARROW_HOME`
  automatically, and never overwritten if one already exists there.
- Share links are HMAC-signed, expire after 15 minutes, and are scoped to a
  single file — they are not reusable as a general API token.
- The extension cannot read arbitrary sites: its required host permissions are
  loopback-only, it declares no content scripts, and its inspector is injected
  on demand — and only on sites you explicitly allow in the popup.

## Documentation

- `docs/current-architecture.md` — how the pieces fit together
- `docs/security-audit.md` — threat model and mitigations
- `docs/development.md` — dev setup, gates, contribution workflow
- `docs/cloud-development.md` — Codespaces/OpenCode cloud setup (development only; Windows GUI remains local)
- `docs/testing.md` — test suites and patterns
- `docs/troubleshooting.md` — common issues and fixes
- `AUDIT_REPORT.md` — prelaunch technical/UI audit
- `IMPLEMENTATION_REPORT.md` — what changed and why
- `TEST_RESULTS.md` — latest verification evidence

## Development

```bash
python -m pytest -q          # full test suite
python -m ruff check .       # lint
python -m mypy arrow         # typecheck
node scripts/verify-extension.mjs   # extension syntax + state-machine tests
```

See `docs/development.md` for the gate ledger workflow (`GATES.md`).

## Cloud development with OpenCode

You can develop in a Linux Codespace using the checked-in `.devcontainer/` setup.

[Create a Codespace on the prelaunch branch](https://codespaces.new/Anmol2k5/arrow-annotate/tree/fix/arrow-annotate-prelaunch)

See [cloud setup and limitations](docs/cloud-development.md). The interactive PyQt6 Windows desktop app cannot run inside this Linux Codespace; run its GUI manually on Windows.
