# Security review

Date: 2026-10-13. Covers the agent control surface added for the agent
pointer and the Allow/Deny action flow, plus the surfaces it sits next to.

## Threat model

Arrow observes screenshots and can, with approval, move the cursor. The
things worth protecting:

1. Anything on the user's screen must not leak to an untrusted party.
2. No agent may change the user's machine without an explicit, informed,
   one-shot yes.
3. An agent must not be able to convert a permission for one thing into
   permission for another.

## Permission boundaries

| Boundary | Control | Default |
|---|---|---|
| Local HTTP API | Per-install bearer token in `ARROW_HOME/token` | required |
| Loopback binding | Non-loopback hosts rejected unless `ARROW_ALLOW_NON_LOOPBACK=1` | off |
| Agent endpoints | `CONTROL_NATIVE` capability | **disabled** |
| Agent actions | Single-use, expiring, target-bound approval | none pre-granted |
| Screenshot assets | Bearer token or a single-file, 15-minute share token | required |
| Microphone | `ARROW_VOICE_TRANSCRIPTION=off` never opens the device | opt-out honoured |
| Browser extension | `activeTab` + `scripting`, loopback-only host permissions | minimal |

`/agent/preview`, `/agent/action`, `/agent/action/<id>` and `/agent/stop` all
require `CONTROL_NATIVE`, which is **off unless the user explicitly opts in**.
An agent therefore cannot even draw a pointer on a default install.

## Fail-closed behaviours

Each is covered by a test in `tests/test_agent_actions.py` or
`tests/test_agent_pointer_integration.py`:

- **No approval, no action.** `AgentActions` ships with `executor=None`; an
  unwired instance refuses with `no_executor` rather than acting.
- **Preview is not permission.** `/agent/preview` cannot reach an action
  executor, and previewing never raises an approval prompt.
- **Deny** executes nothing and is final.
- **Stop** drops every pending approval and hides the pointer.
- **Expiry.** Approvals default to 45s and are re-checked at execution.
- **Changed focus window.** The approval records the window title and the
  live title is compared immediately before acting.
- **Moved or vanished target.** An `observe` hook re-resolves the element
  live. If it cannot be identified, Arrow refuses rather than clicking
  recorded coordinates. This is why the app's executor also re-resolves and
  refuses a fallback target.
- **Stale state.** `decide()` looks the action up before pruning, so an
  expired approval reports `expired` rather than being indistinguishable from
  one that never existed.

## Injection surface

- Action payloads carrying `command`, `shell`, `script`, `args` or `argv` are
  refused with `forbidden_field`. Arrow has no arbitrary-command path.
- `action_type` must be in a fixed set: `preview_target`, `highlight_target`,
  `capture_screenshot`, `click_target`, `scroll_target`.
- Coordinates must be integers (`bool` is rejected explicitly, since it is an
  `int` subclass in Python).
- Highlight rectangles are bounded and must be positive-sized.
- Bounded state: pending approvals and the outcome history are both capped,
  so an agent cannot grow memory without limit.
- The MCP layer resolves image paths **from the database only**. A caller
  cannot pass a path; an unknown asset name falls back to the recorded
  screenshot. A capture id cannot be turned into an arbitrary file read.

## Honest reporting

- "submitted" is never reported as "performed". An executor refusal is
  recorded as `refused` with its reason.
- Task status is never advanced by availability alone; it stays `draft` until
  something moves it.
- `arrow_get_fresh_screen_context` timestamps its capture and states plainly
  that it is new.
- An unresolved target exports as `resolution_method: "fallback"` with
  `confidence_kind: "none"` — a guess is never presented as a detection.

## Known residual risks

- **AI Assist is powerful by design.** With `CONTROL_NATIVE` enabled and the
  user clicking Allow, Arrow moves the real cursor. That is the feature, but
  it means the opt-in is the security boundary. It is off by default.
- **Sensitive on-screen content.** Arrow captures whatever is visible. There
  is no redaction of passwords or payment fields; the user is responsible for
  what is on screen. The capture never leaves the machine unless the user
  sends it to an agent.
- **`click_target` moves the cursor, it does not synthesise input.** Arrow
  deliberately does not expose arbitrary keyboard injection, so it cannot
  type into password fields.
- **Trust is per-install.** Any local process that can read
  `ARROW_HOME/token` has full API access. That is the same trust model as any
  localhost-bound tool.
- **The agent sees screenshots through the MCP bridge.** Whoever can run the
  MCP stdio server locally can read capture images. This is a local-user
  boundary, not an internet-facing one.

## Not done

- No code signing on the Windows executable; Windows SmartScreen will warn
  on first run.
- No audit log file for executed actions. Outcomes are recorded in memory and
  exposed via `arrow_action_status`, but are not persisted across restarts.