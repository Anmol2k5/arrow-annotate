# Real Windows desktop validation

Run this on a Windows 10/11 desktop with the installed or portable build, actual
microphone, and your normal monitors. Linux tests and offscreen Windows CI do
not establish that microphone input, recognition, display alignment or real
Codex/Claude sessions work. Those results remain unverified until performed.

The harness enumerates Qt screen geometries/scales, MSS physical monitor bounds,
PyAudio input devices, offline-model files/runtime, runtime file presence, and
read-only provider authentication/MCP registration/local protocol checks. It does
not register clients, download models, log in, submit prompts or start agents.
Client probes can take several seconds each. No default audio recording,
transcript, screenshot, device name, credential output, local path or free-form
reviewer note is stored in its JSON report. Screen coordinates are numeric.

Use PowerShell in a real desktop session, with `QT_QPA_PLATFORM` unset. Run the
console executable, since `ArrowAnnotate.exe` has no interactive stdin:

```powershell
$Arrow = Join-Path $env:LOCALAPPDATA 'Programs\ArrowAnnotate'
& "$Arrow\ArrowMCP.exe" --diagnostics .\inventory.json
# Opt in to recording your observations after performing the tests below:
& "$Arrow\ArrowMCP.exe" --diagnostics .\windows-review.json --interactive
```

From a source checkout the equivalent commands are:

```powershell
.\.venv\Scripts\python.exe main.py --diagnostics .\inventory.json
.\.venv\Scripts\python.exe main.py --diagnostics .\windows-review.json --interactive
# Or use the installed-build wrapper:
.\scripts\test-windows-interactive.ps1 -Executable "$Arrow\ArrowMCP.exe" -Interactive
```

Every manual prompt accepts `p` only for an observed pass, `f` for an observed
failure and `n` for not run. Anything else becomes not run; entered text is
discarded. Answer only after the real test, using a second window to operate
Arrow. Missing console input leaves the checks unverified. A cancelled review
keeps earlier observations and leaves remaining tests unverified.

Each check has `passed`, `failed`, `not_run` or `manual_required` status. Automated
observations and `user_confirmation` are distinguished. The overall report is
`unsupported` on non-Windows, `failed` if any probe/test failed,
`needs_manual_validation` while any check remains unverified, and `passed` only
when all checks passed. Exit codes are 2 for unsupported, 1 for failed, and 0
otherwise: **zero does not establish completed hardware testing**.

## Microphone, pauses and Hinglish

Before the capture tests, open **Settings → Capture → Microphone**. Refresh the
inputs, choose your actual microphone, and select **Use microphone**. Start
**Test microphone** and wait for Recording before speaking. The meter reflects
real PCM input. Stop and transcribe, or let this test stop after ten seconds.
The test opens the actual production recorder and decodes locally; it creates no
capture, screenshot, audio file or saved transcript and sends nothing to an agent.
Normal shortcut-held captures have no ten-second limit.

Try “Blue button ko heading ke neeche rakho, spacing sixteen pixels.” Use
**Auto · Hindi / English** and inspect the words rather than assuming a test pass
from a moving level meter. Hindi may appear in Devanagari. Quiet input, recognition
accuracy, Windows privacy denial and actual USB hotplug require this physical
desktop check; mocked PortAudio and synthetic English inference are insufficient.
An unavailable or ambiguous selected input must report a problem instead of
silently recording another microphone. Switch to System default if two inputs
have indistinguishable names and host APIs.

1. Launch `ArrowAnnotate.exe`. In inline Settings → Capture, explicitly download
   the offline voice model if needed and choose automatic Hindi/English. Wait
   for the download to finish. This setup action is separate from diagnostics.
2. Hold the configured capture shortcut, speak “Move the blue button below the
   heading”, then release. Inspect the saved instruction. Record a pass only if
   real microphone input produced the expected words. Device enumeration alone
   says nothing about Windows privacy permissions, signal level or recognition.
3. Hold the shortcut continuously. Say “Move the blue button”, pause for three
   seconds, say “below the heading”, then release. Verify both parts appear and
   capture did not stop during the pause. Also try releasing without speech:
   Arrow should recover and permit another capture without an unexplained hang.
4. Say “Is blue button ko heading ke neeche move karo, aur spacing sixteen pixels
   rakho.” Verify that the saved instruction preserves the placement and sixteen
   pixel requirement. Hindi may appear in Latin or Devanagari script. A model
   being present is not a recognition-quality pass.

Recording occurs only when you explicitly hold Arrow's capture shortcut. The
diagnostic harness itself never opens the microphone or saves audio/transcripts.
Normal captures and their instructions remain in your normal Arrow history;
only the reviewer status enters this diagnostic report. Use synthetic phrases.

## Multiple monitors, scaling and desktop startup

1. On every connected monitor, use a synthetic window. Capture and mark four
   corners plus the center; inspect each saved image at full size. Include a
   monitor left of or above the primary if your setup supports it. Select not
   run for the multi-monitor check if there is only one monitor.
2. In Windows Display settings, use different scaling on two monitors, such as
   100% and 150%. Repeat after moving the window between them. Restore your
   normal scaling afterwards. Mark not run if distinct scales were not tested.
3. Compare the report's numeric Qt logical geometry/DPR and MSS physical bounds.
   The automatic comparison checks counts and the multiset of physical widths
   and heights, allowing two pixels for rounding. It cannot establish matching
   monitor order, origins, correct screenshot pixels or annotation alignment.
   Identical-resolution monitors especially require actual visual inspection.
4. Launch the installed app from the Start menu, complete a capture, close and
   restore it from the tray, Quit, then relaunch. Confirm there are no duplicate
   notches, lost tray entry or startup errors. Lock-file presence alone does not
   prove that the app is running. This is desktop launching, not auto-start at
   Windows sign-in; Arrow's installer does not register automatic logon startup.

## Actual Codex and Claude Code sessions

For an automated synthetic check, use **Settings → Agents → Verify live handoff**
for each client. It verifies an actual MCP receipt and two answers, including a
random code visible only in the PNG; see [live agent validation](live-agent-validation.md).
This explicit action uses your CLI account. It is separate from the inventory
and guided diagnostics harness below and never runs at startup.

These steps send the synthetic capture to your chosen client when you explicitly
submit it; normal provider usage/account charges may apply. Do not use a private
repository, screenshot or real task. The harness never performs these steps.

Create a disposable, local sample project and open its page in your browser:

```powershell
$Project = Join-Path $env:TEMP ('arrow-client-test-' + [guid]::NewGuid().ToString('N'))
New-Item $Project -ItemType Directory | Out-Null
Set-Location $Project
git init
@'
<!doctype html><meta charset="utf-8"><title>Arrow synthetic test</title>
<style>body{font:24px sans-serif;padding:60px}button{background:blue;color:white;padding:16px}</style>
<h1>Sample heading</h1><button>Blue button</button>
'@ | Set-Content .\index.html -Encoding utf8
Start-Process .\index.html
```

1. Select this disposable project in Arrow. In Settings → Agents, use Connect
   for each desired client, configure Arrow MCP and Test connection. Confirm
   registration and local protocol separately. Restart existing client sessions
   after registration. Never count these actions as a completed agent session.
2. Hide private windows on **all monitors** first. Arrow saves the virtual desktop;
   drawing a region annotates it rather than cropping other screens out. Use only
   the synthetic page and blank/clean backgrounds for this test. Make a fresh capture. Put marker 1 on the blue
   button and review the image and window text before submitting. Set the current
   instruction to: “Marker 1 identifies the blue button. Explain how to put this
   button below the heading with sixteen pixels of spacing. Do not modify files.”
   Exclude unrelated window text in capture review. Do not make another capture
   until the two clients have retrieved this synthetic one.
3. Use Arrow's Open Codex handoff. In the visible session, submit this exact
   diagnostic request if the prefilled task needs clarification:

   ```text
   Call Arrow MCP arrow_get_capture_bundle for the synthetic capture supplied
   by Arrow. Read its current_instruction and annotated image. State which
   control marker 1 identifies and the requested spacing. Explain the change
   without modifying files. Do not call arrow_look or read other captures.
   ```

   Inspect the actual tool call and response. The client must retrieve the
   capture bundle and correctly identify the blue button and sixteen-pixel
   requirement. A process opening or a successful sign-in is insufficient.
4. Repeat with Arrow's Open Claude Code handoff. Inspect its actual tool call
   and answer independently. Do not mark Claude passed because Codex passed.
5. To reproduce a session manually after configuring MCP, use the normal client
   commands below from the sample project. Paste the same request, replacing
   “the synthetic capture supplied by Arrow” with its explicit capture ID from
   the handoff prompt. These commands do not bypass either client's approvals:

   ```powershell
   codex --sandbox workspace-write --cd $Project
   claude --permission-mode default
   ```

6. Return to the interactive harness and record each observed result. If a client
   was unavailable, unauthenticated, never submitted, or never retrieved the
   bundle, record not run or failed as appropriate. No client transcript or task
   output is collected in the diagnostic report. Keep synthetic captures only
   as long as useful, then remove the disposable project when finished.

Review the JSON locally before sharing it. It provides reported observations;
human confirmation is explicitly labeled and is not automated proof of a real
client transcript or a working desktop.
