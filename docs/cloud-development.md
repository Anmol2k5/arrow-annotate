# Arrow Annotate: GitHub Codespaces (cloud development)

**Scope:** GitHub Codespaces provides a persistent Linux-based cloud editor and terminal for implementing Arrow, using OpenCode, Matt Pocock's engineering skills, Ponytail, and cross-platform static tests.

**It does NOT run the native Windows Arrow desktop application.** The real PyQt notch, Windows global hotkeys, UI Automation, physical screenshots, and microphone tests require an interactive Windows computer. The repository's Windows GitHub Actions verifies the full automated suite separately.

## 1. Create the cloud workspace

Open this branch-specific GitHub Codespaces link while signed into the repository owner's account:

https://codespaces.new/Anmol2k5/arrow-annotate/tree/fix/arrow-annotate-prelaunch

Choose **Create codespace**. GitHub determines whether Codespaces usage is included or billable for your account. Check that information before creating a machine.

The Codespace reads `.devcontainer/devcontainer.json`, creates a Python 3.12 + Node.js 22 development environment, and runs `.devcontainer/bootstrap.sh`.

Bootstrap attempts to install:

- Cloud-safe Python libraries, Ruff, Mypy, pytest.
- `opencode-ai` CLI (official npm distribution).
- Selected skills from `mattpocock/skills` (global to that Codespace).
- Ponytail for OpenCode, via `opencode plugin add @dietrichgebert/ponytail`.

The script reports installation failures explicitly; it does not pretend an unavailable plugin is ready.

## 2. Check setup

In the Codespaces terminal:

```bash
pwd
git branch --show-current
python --version
node --version
opencode --version
bash .devcontainer/check-cloud.sh
```

The cloud checker runs Python compilation, Ruff, Mypy, extension verification, docs/CI verification and a deliberately restricted Python test subset.

**Do not treat a cloud pass as proof that the Windows GUI works.** Windows-specific packages (`uiautomation`, `keyboard`, `PyAudio`) are intentionally omitted from the Linux requirements.

## 3. Use OpenCode in the cloud

```bash
opencode
```

Configure your coding model with OpenCode's `/connect` interface. It requires your own supported model/provider credentials or subscription. **Do not paste API keys into prompts, source files or Git commits.**

Ponytail commands, if installed:

```text
/ponytail full
/ponytail-audit
/ponytail-review
```

Matt Pocock skills should be available to OpenCode. Apply `diagnosing-bugs`, `tdd`, `implement`, `code-review`, and related workflows.

If tool installation failed during bootstrap, retry only the failed step:

```bash
npm install -g opencode-ai
npx --yes skills@latest add mattpocock/skills -g -a opencode -s diagnosing-bugs -s tdd -s implement -s code-review -y
opencode plugin add @dietrichgebert/ponytail
```

## 4. Work on the correct branch

```bash
git branch --show-current
git status
```

Stay on `fix/arrow-annotate-prelaunch`. Don't modify `main` or blindly stage local reference directories. Commit verified changes to the feature branch according to the existing project workflow.

The uploaded SupaMaus videos and extension reference files in ChatGPT are **not automatically mounted in a Codespace**. If needed, upload a copy of the relevant reference material through the Codespaces file explorer; avoid committing third-party copies or private media.

## 5. Full Windows testing

GitHub Actions runs `.github/workflows/ci.yml` with the full `requirements.txt` on a Windows runner.

For interactive desktop validation, pull changes onto your Windows PC and run:

```powershell
cd D:\projects\bluely
git switch fix/arrow-annotate-prelaunch
git pull --ff-only origin fix/arrow-annotate-prelaunch
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
```

Check notch, capture/hotkey, blue trail smoothness, microphone, extension, and agent interaction on the actual desktop before marking the GUI release gate complete.

## 6. Security note

Cloud environments are not the user's local desktop. Do not change Arrow's localhost-only bindings merely to expose a screenshot/token API through Codespaces. `devcontainer.json` has no forwarded ports and asks VS Code to ignore the development HTTP/WebSocket ports by default. Keep all provider keys and user screenshots out of source control.

Codespaces bills/consumes resources according to GitHub account settings. Stop the Codespace when you're not using it.
