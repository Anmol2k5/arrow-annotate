# pstack audit + skill recommendations

## What this project is

`bluely` / **Arrow Annotate** — local-first spatial-context tool for coding agents.
User annotates a screen (web or native app), Arrow compiles the request, then hands
it to Codex / Claude Code via MCP or direct adapters.

Stack: Python 3.10+, PyQt6, Flask, websockets, SQLite, mss, Pydantic, uiautomation,
OCR, browser extension (vanilla JS).

## Work audit

| Area | Status |
|---|---|
| Phases 1–14 of `plan.md` | Done (20 commits, 14-phase plan executed) |
| Modular layout | `arrow/{capture,context,intent,storage,providers,mcp,server,ui}` |
| Tests | 19 test files, **159 passed** (14s) |
| Lint/type | Ruff + mypy configured in `pyproject.toml` |
| Security | Phase 14: bearer token, origin checks, capability gating, no shell |
| Docs | Architecture, refactor plan, security audit, MCP setup guides |
| Branches | `feature/phase-5-context-orchestration`, `feature/phase-6-browser-extension-context` |
| Remaining phases | 15 (testing/reliability) and 16 (packaging/onboarding) in plan |
| Warnings | 1 deprecation: `mss.mss()` → `mss.MSS` |
| Loose ends | untracked `.freebuff/`; uncommitted `arrow/core/logging.py` change |

## Recommended pstack skills

High value for this repo's work:

| Skill | Why it helps |
|---|---|
| `unslop` | All writing/commits/docs lose AI tells. Installed. |
| `poteto-mode` | Entry router — start every non-trivial task through it. |
| `tdd` | Fits plan rule "test first, then fix". 159-test suite already there. |
| `blast-radius` | Safety check before refactors — this code touches MCP + providers + storage. |
| `prove-it-works` | Matches "never claim done unless E2E passes" plan rule. |
| `fix-root-causes` | Good for Phase 15 bug-hardening. |
| `sequence-verifiable-units` | Matches "one phase, checkpoint, then next" workflow. |
| `technical-writing` | Sharpens README, MCP setup docs, commit messages. |
| `typescript-best-practices` | Browser extension JS. |
| `reflect` | Capture lessons after a long phase. |
| `why` / `how` | Untangle the existing pipeline (browser adapter, orchestrator, provider runners). |
| `interrogate` | Multiple-model review of PRs/diffs. |
| `create-verification-skill` / `maintain-verification-skill` | Turn the 159-test suite into a living verify skill. |
| `no-comments` | Strip comment cruft during reviews. |

## Installed (global, all projects)

`C:\Users\Mayur\.config\opencode\skills\`:

`unslop`, `poteto-mode`, `blast-radius`, `principle-prove-it-works`,
`principle-fix-root-causes`, `principle-sequence-verifiable-units`,
`technical-writing`, `typescript-best-practices`, `reflect`, `interrogate`,
`create-verification-skill`, `maintain-verification-skill`, `no-comments`,
`why`, `how`.

`tdd` skipped — already installed at `C:\Users\Mayur\.agents\skills\tdd`.