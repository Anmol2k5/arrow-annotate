# Agent handoff and desktop lifecycle validation

User scope: verify actual Codex/Claude retrieval and answers from selected image/
context; launch, tray restore, quit/relaunch and upgrade/settings persistence.

Approach: retain current Python/PyQt desktop and CLI handoff. Add explicit opt-in
live-agent checks using synthetic isolated captures and installed clients' own
accounts. The model must return a code contained only in the PNG and another
nonce contained only in capture context. Record an actual scoped MCP retrieval
receipt/hash; login/registration/process launch alone never counts as success.
No real captures or provider credentials go in reports; no agent task runs at
startup or in credential-free CI. CLI/account unavailable is not_run/failure.

Desktop validation runs the normal launcher, instance lock, server, Qt widgets,
shortcuts and tray. An optional startup observer schedules programmatic native
Qt/tray actions and checks visibility/cleanup. Use an isolated home and no mic or
agent tasks. This proves app startup/handlers, not physical shell icon clicking.
Upgrade validation installs public 0.4.1 with checksum verification, seeds a
0.4.1-compatible SQLite/config/image fixture, retrieves it with the old MCP, then
installs the new build into the same directory and checks preferences, capture,
image hash and old-data migration. Verify new launch/quit/relaunch in that home.

- [x] Live-agent synthetic challenge, scoped MCP receipts and strict answer checks.
- [x] CLI/inline diagnostics entry point with explicit account usage and no auto task.
- [x] Native desktop lifecycle smoke against the production startup path.
- [x] Old-version fixture and actual installer-upgrade persistence checks.
- [ ] Source tests/lint/types, independent review, native Windows CI and live checks
  where available; preserve precise pending statuses for inaccessible accounts.
- [ ] Publish only after required native lifecycle/upgrade checks pass.

Failure focus: old capture returned instead of ID, agent never calls MCP, image
code leaked in prompt, wrong/empty reply, stale receipts, CLI timeout/cleanup,
tray absent, close hides and prematurely exits, lock not released, port still
bound, upgrade changing shortcut/language/repository or losing images/data.

Current live results: Linux Codex startup fails because its account home has a
read-only `installation_id`; CLI SQLite/log directory overrides do not address
that required state write. Claude Code is not installed. Neither returned an
MCP receipt or model answer; neither is recorded as verified. No account home,
authentication files or global MCP configuration were changed.

Review corrections: own Windows CLI/MCP descendants in a kill-on-close Job Object
before resuming the CLI; wait for the entire job to stop before deleting the
fixture. Cancel live workers and allow cleanup on tray Quit. Default desktop
smoke suppresses an inherited real database override, restores the environment,
and requires a fresh process if data-path-caching modules were already imported.

Source verification: 702 Python tests passed, 3 native Windows checks skipped on
Linux; 4 browser tests passed. Ruff, mypy and dependency consistency passed.
Native installer/lifecycle/upgrade verification remains pending the Windows job.
