# Development Guide

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
python main.py
```

Optional: copy `.env.example` to `.env` to override ports, Agentation URL,
or binding behaviour. Config precedence is: defaults → `.env` → real
environment variables. Non-loopback hosts are rejected unless
`ARROW_ALLOW_NON_LOOPBACK=1`.

## Code layout

| Path | Responsibility |
| --- | --- |
| `arrow/app.py` | Qt application, hotkeys, capture orchestration |
| `arrow/capture/` | Session state machine, screenshot service, context |
| `arrow/core/` | Config, logging, `UiBridge` thread marshaling |
| `arrow/ui/` | Notch widget, overlay, voice input |
| `arrow/server/` | Local Flask server, share tokens, upload validation |
| `arrow/providers/` | Agentation client, Codex/Claude providers |
| `arrow/storage/` | SQLite capture store |
| `browser_extension/` | MV3 extension (state machine + popup) |
| `scripts/` | Verification scripts (extension, docs, CI) |

## Quality gates

Every change is verified against the ledger in `GATES.md`. Each gate has a
machine-checkable oracle (`CHECK` command + `EXPECT` regex) or is explicitly
marked manual (G17 — GUI smoke run).

```bash
node "C:\Users\Mayur\.agents\skills\unlazy\scripts\gate-check.mjs" --approve GATES.md
```

Approvals are keyed to the exact command, working directory, and expected
output; a changed oracle automatically invalidates the approval.

## Rules of the road

- Typecheck and lint before every commit: `mypy arrow`, `ruff check .`.
- Tests are part of the change, not a follow-up. New behaviour ships with
  tests in `tests/`.
- Qt code: never touch widgets from worker threads. Post through
  `UiBridge` (`arrow/core/threads.py`) and discard stale captures by id.
- Keep `.env`, tokens, and `arrow.db` out of git (already ignored).

## Browser extension

```bash
node scripts/verify-extension.mjs
```

Runs manifest/permission assertions plus the vm-sandboxed state-machine
tests in `browser_extension/tests/`.

## CI

`.github/workflows/ci.yml` runs install → ruff → mypy → pytest → extension
verification on a Windows runner (`QT_QPA_PLATFORM=offscreen`).
