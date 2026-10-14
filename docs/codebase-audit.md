# Codebase audit and fixes — 14 October 2026

The baseline had 159 passing tests, but Ruff and mypy stopped on a syntax error.
Additional regression tests found failures across boundaries that the original
suite tested separately. This audit covers Python modules, HTTP/WebSocket and MCP
entry points, storage, capture and source mapping, Qt callbacks, provider command
construction, browser scripts, and package installation.

## Confirmed defects fixed

| Area | Failure before the fix | Result |
| --- | --- | --- |
| Logging | `arrow/core/logging.py` started with `/import`, causing `SyntaxError`. | Module imports; static checks can run. |
| Packaging | Editable installation failed because setuptools discovered both `arrow` and `browser_extension`. | Explicit package discovery and build backend; Windows dependencies have platform markers. |
| Desktop → MCP | Desktop captures existed only in `contexts`, while MCP read `change_requests`. | Both views persist in one transaction; migration 3 backfills existing captures and assets. |
| Capture editing/deletion | MCP missed edited instructions; deleting a desktop capture left most image assets behind. | Edits update the relational view while preserving agent status; deletion uses asset cleanup/retry handling. |
| Source mapping | Production bypassed SourceMapper, trusted nonexistent React file/line metadata, and could map outside the selected repository. | Production uses the verified mapper, including DOM IDs; traversal and symlink escapes are rejected. |
| Intent compiler | `padding` matched `add`; duplicated voice text; movement discarded style changes. | Word-boundary matching, duplicate removal, and preservation of combined move/style requests. |
| Qt callbacks | Worker-thread timers had no Qt event loop; hotkeys could touch UI from a worker; capture exceptions escaped Qt callbacks. | Queued dispatch to the main thread, guarded capture errors, and visible status messages. |
| Capture sessions/voice | An old capture could transition a new session; an old voice worker could cancel a new recording. | Capture-ID-bound transitions under a lock; per-recording generations and local recognizers. |
| Monitor geometry | Negative coordinates were clamped to zero; clipped crops expanded into unrelated pixels; multiple monitors reused different local origins. | Negative coordinates preserved, correct rectangle intersection, and desktop composition with one origin/scale. |
| Highlight capture/resolution | Offset monitor crops could be black; native resolver rejected the browser bridge's actual response shape. | Direct region capture and compatible response handling. |
| HTTP/token boundaries | Wrong JSON types caused 500s; non-ASCII bearer strings raised; invalid PNGs were accepted; same-second uploads overwrote files. | Input validation, token rejection, PNG verification, and unique asset names. |
| Server lifecycle | Stop did not stop either service; WebSocket bind failures stayed in the worker thread. | Owned HTTP/WS lifecycles, propagated startup errors, and released ports on stop/restart. |
| MCP protocol | Non-object JSON could terminate stdio; ordinary notifications got replies; screenshots were base64 text rather than image content. | JSON-RPC errors for invalid requests, notification handling, and MCP image content. |
| Latest mirror | Mirroring ignored `ARROW_HOME`; Markdown omitted repository root/branch due to wrong field names. | Shared runtime path resolution and correct repository schema fields. |
| Provider launch | A second run could overwrite the first subprocess; prompts could become CLI flags; screenshots were only mentioned in text. | Running-process guard, argument delimiters, explicit Codex sandbox, and image attachment. |
| Agentation | Offline optional service marked a valid capture failed; first unrelated session was reused; session closing targeted an annotation endpoint. | Offline captures remain ready; active sessions match URL/project; unsupported session closing raises a clear local error. |
| Browser bridge | Concurrent connects created multiple sockets; old token reads won races; selectors did not escape CSS punctuation; isolated-world React inspection missed page metadata. | Connection generations, socket-specific callbacks, escaped selectors, and MAIN-world metadata inspection. |

## Validation and limits

Final Linux validation: **215 Python tests passed**, **4 Node tests passed**,
repository-wide Ruff passed, configured mypy passed (47 source files), Python
compilation passed, editable installation with the development extra succeeded,
and installed dependencies passed compatibility checks. Pytest reported one
MSS factory deprecation warning; there were no failed or skipped tests.


Validation commands are documented in the README. Python regressions cover the
storage/MCP handoff, actual stdio subprocess requests, real local HTTP/WS server
lifecycle, headless Qt callback delivery, simulated display composition, and
simulated microphone cancellation. Node tests exercise browser script behavior
with mocked Chrome boundaries; they are not a loaded-extension Chrome test.

The Windows desktop cannot launch on this Linux machine. Actual Windows UIA,
keyboard input, microphone hardware, compositor/DPI behavior, and Chrome extension
installation must still be exercised on Windows. End-to-end authenticated Codex,
Claude Code, and Agentation agent runs were not performed. CLI argument support
was checked against the installed Codex help and official published Claude CLI
sources. Claude permission enforcement belongs to its CLI; prompt classification
is not a filesystem sandbox or a per-command permission interceptor.

React debug-source availability depends on the React version and development
build. Missing metadata is reported as unresolved and other repository mapping
tiers remain available. Agentation screenshot references use local file paths;
the agent consuming them must have access to those files.
