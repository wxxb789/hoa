# Phase 0 — the dispatch contract

Before any agent run, the increment must be dispatchable. Six clauses, all required:

1. **Observable pass condition** — one sentence a command can judge.
2. **Judging artifact** — the command / file / browser observation used to assess it.
3. **Failure control** — what counts as "not achieved", stated up front.
4. **Out of scope** — an explicit "we are not doing X" list, to stop scope drift.
5. **Evidence plan** — which rows get measured, at which tier, with which counter.
6. **Mergeable alone** — the PR is safe to merge by itself; no unmerged sibling is required.

Scale rule: one goal ≈ one agent run (≤12 h) ≈ one PR. If a goal needs two PRs, it was two goals.
If the contract fails any clause, fix the contract — do not dispatch and hope.

## Protocol boundary

**This file is the protocol and nothing else.** Repo facts live in a project profile — a profile is
deltas only and may never restate or override the protocol. Transport mechanics live in
[`references/transport.md`](../transport.md). Language- and stack-specific build knowledge
lives in its own skill. One fact, one home.

## Project profiles

| Where | What | State |
|---|---|---|
| `references/profiles/_template.md` | the onboarding template — copy, fill, run | shipped |
| `private/profiles/<repo>.md` | your real profiles (git-ignored, never published) | local only |

A profile supplies only what the protocol cannot know: contract location and numbering, exact gate
commands and how to read them, branch/PR/bot conventions, frozen surfaces, evidence conventions,
release path, resource rules. Keep it under ~120 lines; a 500-line profile means protocol facts leaked
into it.

## Configuration discipline

Nothing about one install lives in the protocol. Every value that differs between machines is an env
var with a documented default — `GDD_STATE_FILE`, `GDD_TASK_ROOT`, `GDD_RUN_ROOT`, `GDD_LAUNCHER`,
`GDD_TEMPLATES`, `GDD_GOAL_GLOB`, `GDD_MODEL`/`GDD_THINKING` if your adapter accepts them — and a
profile may point at its own files. When adding behaviour, resolve it the same way rather than
inlining a path: a skill that reads the operator's configuration customises itself, one that hard-codes
a path only works where it was written.
