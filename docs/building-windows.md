# Building a Windows executable

## Quick build

```powershell
cd D:\projects\bluely
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean arrow.spec
```

Output: `dist\ArrowAnnotate\ArrowAnnotate.exe`.

Ship the whole `dist\ArrowAnnotate\` **folder**, not just the exe — the
executable loads its dependencies from it.

## What the spec does, and why

- **One-folder, not one-file.** A single-file build unpacks to a temp
  directory on every launch. That is slow for a tray-style app that starts on
  login, and it interferes with the native probing that `mss` and
  `uiautomation` rely on.
- **`console=False`.** Arrow is an overlay/tray app; a console window must
  never appear behind the notch.
- **Hidden imports** cover the desktop stack that is imported lazily at
  runtime: `uiautomation`, `mss`, `speech_recognition`.
- **Dev tooling excluded.** `pytest`, `mypy`, `ruff` and friends are not
  bundled, so the build is smaller and carries no test surface.

## Where user data lives

Nothing is written next to the executable. Everything resolves through
`ARROW_HOME` (default `~/.arrow`):

```
~/.arrow/
  arrow.db            capture + task metadata
  screenshots/        raw, annotated and crop images
  captures/           generated context files
  token               per-install API bearer token
  logs/
```

This is what makes it safe to install under `Program Files`, which is not
writable by a normal user. `ARROW_DB_PATH` overrides just the database.

## First run

The first launch applies migrations (schema version 3). If a database
created by an older release is sitting in the checkout, it is moved into
`ARROW_HOME` once, and is **never** overwritten if one already exists there.

## Enabling the agent pointer and actions

Off by default. The agent endpoints require the `CONTROL_NATIVE` capability:

```env
# .env
ARROW_ENABLED_CAPABILITIES=control_native
```

With it off (the default) `/agent/preview` and `/agent/action` return 403, so
an agent cannot draw a pointer or request an action at all. See
[`security-review.md`](./security-review.md).

## Known gaps

- **No code signing.** SmartScreen will warn on first run.
- **No icon.** Windows shows the default application icon.
- **Not tested on a second machine.** The build was produced and launched on
  one Windows desktop at 1920×1080 / 125% scaling.