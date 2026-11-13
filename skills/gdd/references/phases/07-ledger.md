# Phase 7 — durable state (what makes the next session possible)

Every stage ends with one ledger row. This is the operator's job, not the agent's:

```bash
scripts/delivery-state.py append --repo <path> --goal <id> --stage <stage> \
  [--base SHA] [--head SHA] [--pr N] [--gates "test rc=0"] [--rounds-review N] \
  [--findings "real=3 rej=1"] [--next <stage>] [--note "…"]
scripts/delivery-state.py show --repo <path> --goal <id>     # resume here
scripts/gdd.py close --repo <path> --goal <id> --pr <N>       # landing row: stage=done + PR + head
```

The `close` row is not optional bookkeeping: without it the ledger's newest row for a shipped goal stays
`fix`, and the next session reads a merged increment as unfinished. Write it in the same breath as the
merge, not from memory later.

`show` prints the latest row, the stage history, live git/PR facts (including whether the branch is
**behind** `origin/main`, which the ahead-count alone cannot show), and rewrites
`<task_root>/<date>/<repo>-<goal>/state.md`. A new session resumes with `show` + `git status` +
`git log origin/main..HEAD` — three commands, no archaeology through prompt files.

A run whose pane died is finalized as failed (`recovered_stale`) by the next `status`/`list`/`result`;
a `state.json` stuck at `running` is not evidence of a live run — read the `finalized` marker or the
`stale_recovered` flag.

## Phase 8 — reset before the next increment

Fresh run (never resume a previous increment's session); verify the agent build is current;
delete merged local and remote branches; fork from freshly fetched `origin/main`; report the base SHA.

## Reporting mid-flight

One status line first (state + head SHA + what is running), then evidence bullets with paths, then the
next step — never a narrative of tool calls. Keep the task dir's `state.md` current per phase via
`delivery-state.py` and name the watcher job and log path so the operator can re-check without you.
Derive the answer from evidence (`show`, `git log --oneline -2`, `git status --short`,
`gh pr list --state all`), never from the run you remember: hours pass between turns while other runs
advance the repo, so a remembered status is stale by construction. When a round contradicts what you
said earlier, say what changed and why.

Answering a bare "how is it going?" mid-flight: read live state, never reconstruct from the
conversation. `delivery-state.py show` (or `gdd.py status`) for the stage and next action,
`gh pr list --state open` for unlanded reviews, `git branch -r` (anything but `main` = unlanded work),
and the launcher's run list for the running stage. Report three bullets — landed / in flight / waiting
on the operator — plus the next stage and who executes it; run the probes yourself rather than handing
the operator commands.

## Pitfalls this phase answers

- **A stale completion notification is not a new event.** Re-read live state, then continue.
- **A late completion notification is not news.** Read `state.json`, the ledger and the repo first; it
  usually describes work you already landed.
- **A stalled increment with no ledger row is the expensive failure.** Work sits in a dirty worktree
  and the next session cannot tell "not started" from "implemented, awaiting review".
- **On handover, inventory uncommitted work across *every* worktree** (`git worktree list`), not only the
  main clone, before deciding which stage to re-dispatch.
- **When a PR is `CONFLICTING`, GitHub dispatches no workflows** — an empty `gh pr checks` set is a
  merge conflict, not "CI has not run yet".
- **Don't start the next increment while the previous branch is unmerged** — the review range stops
  meaning anything.
