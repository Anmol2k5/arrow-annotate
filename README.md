# Arrow Annotate

Local-first spatial-context tool for coding agents. Draw an annotation on a
screenshot of any screen region, add a voice or typed instruction, and hand
the result to a coding agent (Agentation, or the built-in Codex/Claude
providers) with the exact coordinates, window, and context it needs.

Everything runs on your machine. The only network traffic is:

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

- Press the annotation hotkey (default `Ctrl+Shift+A`) to capture a region.
- Drag to select an area; the overlay opens for arrows, highlights, and text.
- Hold the push-to-talk key to add a voice instruction, or type one in the
  preview panel.
- Approve the preview to send the capture to your agent. The notch widget
  shows status through the whole flow (capturing → processing → sending →
  done/failed).

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
