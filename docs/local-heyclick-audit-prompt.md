# Prompt for a local Heyclick/Arrow audit

Keep the reference folder under `reference/heyclick/`, outside `arrow/`, and run
this from the Arrow repository. Pull the current `work` branch first if testing
source changes; installing a new setup is separate from `git pull`.

```text
Analyze this entire repository and reference/heyclick before changing code.
I need a complete explanation of how both products work, then a working Arrow
implementation with a simple native Windows UI and reliable agent handoff.

Inventory every first-party file in both trees. Group generated files, bundles,
node_modules and binaries separately; do not pretend to have reviewed unreadable
or unavailable source. Describe their purpose and dependencies. Do not print
secrets or .env values.

Trace actual entry points, event loops, IPC, storage, capture/drawing, microphone,
window/DOM context, clipboard, settings, MCP and agent launching. Use diagrams
and concrete file/function references. Distinguish observed behavior from guesses.
Explain exactly what happens from pressing the shortcut through opening an agent.

Create an architecture map, file responsibility map, verified defect list with
reproduction steps, dependency/license inventory, and a feature comparison.
For every claimed integration, name the actual protocol/command and validate it.
MCP context retrieval alone does not prove an app can be opened or a draft filled.

Preserve local changes and create a separate branch before restructuring. You may
split or replace whole modules when evidence justifies it. Work incrementally;
keep working capture/voice/clipboard behavior. Avoid rewrites for appearance alone.
Write regression tests for confirmed bugs, run the complete suite and appropriate
Windows integration checks, and record all remaining failures or untested claims.

Use one exact capture-ID packet for prompt, annotations, original speech, edited
instruction, source/destination evidence, project facts and actual image content.
Never substitute a newer capture or invent selectors, source files or client APIs.
Keep the UI compact: one clear capture action, history, selected capture details,
one agent selector/action, inline feedback and settings inside the notch.

Deliver concrete changes, verification commands/results and a small manual test
checklist. Explain architectural tradeoffs and remaining limitations. Do not say
an end-to-end flow works until you have actually tested that flow.
```
