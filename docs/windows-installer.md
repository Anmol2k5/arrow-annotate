# Windows installer

Arrow Annotate packages Python and its native dependencies. Recipients need Windows 10 (1809+) or Windows 11 x64; they do not need Python, pip, or a compiler.

## Install and use

Download `Arrow-Annotate-Setup-<version>-x64.exe` from the [official public releases](https://github.com/Anmol2k5/arrow-annotate/releases). A release appears after its tagged native Windows build, frozen-app checks, install checks and uninstall checks pass. Development builds are also available as **Windows installer** Actions artifacts; extract those artifacts to find `dist/artifacts/Arrow-Annotate-Setup-<version>-x64.exe`. You can share the installer file with other users; they do not need the source checkout or build tools. It installs for the current user in `%LOCALAPPDATA%\Programs\ArrowAnnotate` without administrator access, adds a Start menu shortcut, and offers an optional desktop shortcut. Launch **Arrow Annotate** from Start. Close the app from its tray menu before installing an update.

The alternative `Arrow-Annotate-Portable-<version>-x64.zip` contains the same application. Extract its entire `ArrowAnnotate` folder and launch `ArrowAnnotate.exe`. Keep `_internal` next to both executables. Portable means the application folder can move; user settings and captures still use the normal user data directory. Do not run the executables from inside the zip.

No signing identity has been configured yet: builds are unsigned, and Windows may warn about an unknown publisher. Optional trusted signing is supported when a maintainer supplies a real certificate; each release's notes and `build-provenance.json` state whether that build was signed. Only use the official repository's releases. `SHA256SUMS.txt` records SHA-256 hashes of the installer and portable zip; compare with `Get-FileHash <download> -Algorithm SHA256` to detect corruption. Hashes detect corruption; they do not replace a trusted publisher signature.

Settings → General → Check for updates makes an explicit request to the official GitHub latest-release API. No update request runs at startup. It compares stable numeric versions and offers the official release page; it never downloads or executes an installer automatically. Network, rate-limit and invalid-response errors can be retried. Review the release, download it yourself and verify its hash before updating.

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

`ArrowMCP.exe` runs the MCP server over standard input/output. `ArrowAnnotate.exe` launches the desktop UI. The windowed GUI executable cannot provide MCP console streams; use `ArrowMCP.exe`. Voice uses local Whisper; download its model once in Settings → Capture before speaking. The installer includes the speech runtime, while model weights are installed separately. Microphone permissions, input devices, global hotkeys, and desktop capture must be tested on a real interactive Windows desktop. OCR models are included for offline OCR.

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

Pushing `v<project version>` in the official repository publishes a public GitHub Release only after the build and every automated smoke/install/uninstall check succeeds. Branch pushes, pull requests and manual workflow runs only upload Actions artifacts. The publication job alone receives `contents: write`; build and PR jobs retain `contents: read`. Publication rechecks SHA-256 sums and includes Setup, the portable zip, `SHA256SUMS.txt`, `build-provenance.json`, `build-requirements.txt` and `third-party-manifest.json`. A tag/version mismatch or failed check prevents publication. No release or tag is created by local setup scripts. Interactive hardware/account validation remains a separate maintainer check.

The native source lane additionally runs a visible Qt/UIA/desktop-capture test in
fresh Windows processes with `QT_SCALE_FACTOR=1` and `1.5`. The install lane uses
Windows TTS and explicitly cached test model weights to transcribe a real synthetic
WAV in fixed English/auto modes through source, portable and installed runtimes.
Inference runs with Python network connections blocked. Reports are uploaded;
no screenshots, WAV recordings or model weights enter release artifacts. See
[native validation scope](native-windows-validation.md). Model preparation is an
explicit network setup step and requires public Hugging Face availability; live
microphone, natural Hinglish and physical mixed-DPI monitor tests remain separate.

## Optional trusted signing

Signing support is ready, but no trusted signing identity is supplied by this repository. Unsigned releases remain supported and are clearly labeled. Never use a self-signed certificate to imply a trusted publisher.

For a future signing identity, configure repository Actions secrets `WINDOWS_SIGN_PFX_BASE64` (base64-encoded PFX) and `WINDOWS_SIGN_PFX_PASSWORD`, plus repository variable `WINDOWS_SIGN_CERT_THUMBPRINT` (the expected certificate's 40-character SHA-1 thumbprint). Only pushed version-tag builds receive these values; PR builds never receive signing credentials. Leave all three unset for unsigned builds. A partial configuration fails rather than silently publishing an unexpected unsigned build. Protect release-tag creation and signing secrets with repository access controls.

Locally, supply the same values as environment variables `ARROW_SIGN_PFX_BASE64`, `ARROW_SIGN_PFX_PASSWORD` and `ARROW_SIGN_CERT_THUMBPRINT` to `build-windows.ps1` in a clean Windows build account with Windows SDK Signing Tools installed. Do not put passwords in script arguments or repository files. `scripts/sign-windows.ps1` temporarily imports the private key, signs both app executables before they enter the installer/zip and signs Setup after Inno compiles it, then removes the temporary PFX and imported key. It uses SHA-256 with an HTTPS RFC 3161 timestamp service and requires Windows Authenticode trust validation, the configured publisher thumbprint and a timestamp before proceeding. Setup and the app executables are signing targets; Inno's generated uninstaller is not separately signed. The zip and final hashes are created only after signing completes.
