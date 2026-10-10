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

- Hover over the top-center notch, select a project with the folder icon,
  and click **Capture** (or press **Ctrl+Shift+Space**).
- Draw a source region; draw a second stroke for an optional destination.
  A blue gesture trail follows the pointer and fades over about 3 seconds,
  while the red/green source/destination marks remain until you finish.
- Press **Ctrl+Shift+Space** again or **Esc** to finish. Note that Esc
  currently completes the capture, rather than cancelling it.
- Voice recognition starts during capture when available; it uses Google
  speech recognition by default, which requires a network connection.
  Unrecognized speech no longer ends the capture. You can instead edit
  the instruction on the resulting screenshot card.
- The notch shows captured images. **Edit** or **Copy** a compiled request,
  or select **Codex**/**Claude Code** when the matching local CLI is installed.
  The app currently also attempts to hand completed captures to Agentation
  at `http://127.0.0.1:4747`; that optional integration may report offline
  while local screenshots remain available.

The companion browser extension lets you annotate live web pages the same
way; captures flow through the same local pipeline.

## Browser extension setup

1. Open `chrome://extensions`, enable Developer mode.
2. Click "Load unpacked" and select the `browser_extension/` directory.
3. The popup walks you through pairing: it connects only to loopback
   (`127.0.0.1` / `localhost`) on the configured port, authenticates with a
   token from the desktop app, and shows live connection state
   (connecting / authenticating / connected / auth failed / server
   unavailable).
4. The extension requests only `activeTab` and `storage`; page access is
   limited to loopback HTTP(S) endpoints of the local app.

## Privacy

- No telemetry, no analytics, no third-party servers.
- Screenshots stay on disk under `screenshots/`; the local SQLite database
  (`arrow.db`) stores capture metadata only.
- Share links are HMAC-signed, expire after 15 minutes, and are scoped to a
  single file — they are not reusable as a general API token.
- The extension cannot read arbitrary sites: its host permissions are
  loopback-only and its content scripts do not run on the open web.

## Documentation

- `docs/current-architecture.md` — how the pieces fit together
- `docs/security-audit.md` — threat model and mitigations
- `docs/development.md` — dev setup, gates, contribution workflow
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
