# Windows installer

Arrow Annotate packages Python and its native dependencies. Recipients need Windows 10 (1809+) or Windows 11 x64; they do not need Python, pip, or a compiler.

## Install and use

Download `Arrow-Annotate-Setup-<version>-x64.exe` from a successful **Windows installer** GitHub Actions run's artifact. Extract the downloaded artifact zip, then run `dist/artifacts/Arrow-Annotate-Setup-<version>-x64.exe`. You can share that installer file with other users; they do not need the source checkout or build tools. It installs for the current user in `%LOCALAPPDATA%\Programs\ArrowAnnotate` without administrator access, adds a Start menu shortcut, and offers an optional desktop shortcut. Launch **Arrow Annotate** from Start. Close the app from its tray menu before installing an update.

The alternative `Arrow-Annotate-Portable-<version>-x64.zip` contains the same application. Extract its entire `ArrowAnnotate` folder and launch `ArrowAnnotate.exe`. Keep `_internal` next to both executables. Portable means the application folder can move; user settings and captures still use the normal user data directory. Do not run the executables from inside the zip.

Windows may warn about an unknown publisher because these builds are unsigned. Only use artifacts from a trusted repository/run. `SHA256SUMS.txt` records SHA-256 hashes of the installer and portable zip; compare with `Get-FileHash <download> -Algorithm SHA256` to detect corruption.

The app stores data in `%USERPROFILE%\.arrow` by default; set `ARROW_HOME` to override it. Updating or uninstalling preserves this directory. Uninstall from Windows **Installed apps** or the Start menu uninstall shortcut. Delete the data directory yourself only when you want to discard settings and captures.

The Chromium extension is bundled in `_internal\browser_extension`. Enable Developer mode in `chrome://extensions` or `edge://extensions`, choose **Load unpacked**, and select that folder. Keep that folder in place after loading it. Browser permissions and extension installation remain a user choice.

For an agent's MCP configuration, use the absolute installed path to `ArrowMCP.exe`, for example:

```json
{
  "mcpServers": {
    "arrow": {
      "command": "C:\\Users\\YOUR_NAME\\AppData\\Local\\Programs\\ArrowAnnotate\\ArrowMCP.exe"
    }
  }
}
```

`ArrowMCP.exe` runs the MCP server over standard input/output. `ArrowAnnotate.exe` launches the desktop UI. The windowed GUI executable cannot provide MCP console streams; use `ArrowMCP.exe`. Voice transcription requires network access to the configured speech service; microphone permissions, input devices, global hotkeys, and desktop capture must be tested on a real interactive Windows desktop. OCR models are included for offline OCR.

## Build locally

Use Windows x64 with Python **3.12 x64**, Git, and **Inno Setup 6.4.3**. From the checkout root in PowerShell:

```powershell
# Optional: download the official compiler and verify its Authenticode signature.
$compiler = & ./scripts/install-inno.ps1
./scripts/build-windows.ps1 -InnoCompiler $compiler
./scripts/test-windows-install.ps1
```

Alternatively supply the absolute path to an existing `ISCC.exe`. The build script creates `build/windows/venv`, installs the project and pinned build tools, runs the Python test suite, collects license/provenance records, builds a shared PyInstaller one-directory bundle, compiles Setup, and emits the portable zip plus hashes under `dist/artifacts`. The project version in `pyproject.toml` controls version resources and filenames. A tag build rejects a tag that does not equal `v<project version>`.

`packaging/windows.spec` analyzes `main.py` once, then produces the GUI `ArrowAnnotate.exe` and console `ArrowMCP.exe` with one shared `_internal` runtime. It explicitly collects PortAudio/PyAudio, speech recognition, global keyboard hooks, Windows UI Automation/COM, ONNX Runtime DLLs, RapidOCR's models, Qt assets, the browser extension, and project package metadata. Builds are native: PyInstaller on Linux cannot produce a Windows executable.

`build-requirements.txt` records the full resolved build environment. PyInstaller and Inno Setup are pinned; application dependencies follow `pyproject.toml`, so builds are traceable but not byte-for-byte reproducible. `_internal/THIRD-PARTY-NOTICES` contains original wheel license/notice files, metadata, source URLs when supplied, and a manifest. Packages without separate license files are listed for review. Review these notices, bundled native/model licenses, and the repository's own distribution rights before public redistribution. PyQt6's GPL/commercial licensing applies to bundled distributions.

## Automated verification and release

`.github/workflows/windows-installer.yml` builds on relevant code/packaging pushes to `main` or `work`, pull requests, `v*` tags, and manual dispatch. It runs tests before freezing, exercises both frozen executables from an unrelated working directory, silently installs to a temporary path containing spaces, repeats both smoke checks, uninstalls, and checks that user data survives. It also starts `ArrowMCP.exe` without arguments and exchanges real MCP initialization and tools/list messages over stdin/stdout, rejecting startup banners or invalid protocol output. Reports and installer logs are uploaded even on failure.

Smoke checks use `--smoke-test <report.json>`, verify the JSON `success` field, and require successful process exit. They validate imports, native libraries, bundled OCR resources, storage, and extension assets without requesting microphone access or capturing the desktop. They do not replace an interactive Windows check of capture, hotkeys, tray behavior, microphone access, browser pairing, or MCP use by an actual agent.

The workflow uploads artifacts and does not publish a release. After a successful native build and interactive acceptance checks, a maintainer can manually create a draft GitHub release and attach the installer, portable zip, `SHA256SUMS.txt`, and provenance files. Code signing with a trusted certificate is a separate release step; never store signing credentials in the repository.
