# Review and Windows readiness

The user authorized implementation of capture review, clean prompts, one-click
agent setup, voice improvements, public distribution and real Windows testing.
Extend the existing Python/PyQt/SQLite application. Retain inline notch settings
and immutable capture bundles. An independent rewrite would duplicate working
capture/installer behavior; an external review window would contradict the user.

The capture review shows the saved annotated image, editable instruction and
editable/excludable window text before handing context to any client. Changes
persist for both clipboard and MCP bundles; original voice stays immutable.
Human-facing prompts lead with user words and numbered markers, retaining useful
constraints/clarification without unknown-intent/confidence/inference boilerplate.
Structured diagnostic metadata remains in capture.json for tools.

Agent setup registers Arrow through documented CLI MCP commands, runs a local
stdio initialize/tools-list probe, and verifies client registration separately.
Never infer client connection from account sign-in or process launch. Never log
credential output or overwrite unrelated MCP servers. Voice supports automatic
Hindi/English detection, explicit download progress/cancel/retry and recording /
transcribing feedback. No cloud speech fallback.

Release tags publish verified artifacts publicly, with SHA256 hashes. Signing
uses an externally supplied trusted certificate, never a fabricated/self-signed
identity. Update checks are explicit user actions, use the official GitHub release
API, and open a reviewed release page rather than auto-running downloaded code.

Windows hardware testing must distinguish pass/fail/not-run for microphone,
recognition, monitors/scaling, GUI startup and actual agent sessions. The Linux
cloud can automate unit/integration checks and native Windows CI packaging;
it cannot claim interactive hardware/account validation. Provide a reproducible
local test harness and checklist without collecting raw audio/screenshots in a
report by default. Existing captures/settings survive upgrades.
