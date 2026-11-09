---
name: goal-driven-delivery
description: >-
  Land a written, machine-checkable increment in a repo end to end — one goal contract, one fresh
  authoring-agent run per stage, gates the operator re-runs, a scripted merge gate, and a durable stage
  ledger so a later session can resume in three commands. Use when an increment is delegated end to
  end, including the merge. Do not use for one-line fixes, exploration with no acceptance criteria, or
  work no machine can check (that is a conversation, not a delivery).
metadata:
  version: "0.1.5"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
---

# Goal-driven delivery

One written increment (a goal), authored by a coding agent, verified and landed by the operator, with
the loop running end to end and no per-step approval.

**This file is the protocol and nothing else.** Repo facts live in a project profile — a profile is
deltas only and may never restate or override the protocol. Transport mechanics live in
[`references/transport.md`](references/transport.md). Language- and stack-specific build knowledge
lives in its own skill. One fact, one home.

## When to Use

- "Start the next goal", "run the goal-driven flow", "finish this the usual way" — in any language.
- Any multi-hour repo increment: a feature, a research-feasibility study, a migration, a docs
  rewrite — anything with a written completion contract and machine-checkable gates.
- A repo where the operator delegates end to end, including the merge.

Not for: one-line fixes, exploratory poking with no acceptance criteria, or work whose result no
machine can check.

## Stage order — fixed, no skipping

```
contract → implement → verify → simplify-report → apply → code-review-report → fix
        → gates → PR → babysit → merge → reset
```

Both two-phase steps are mandatory: an unapplied report or an unfixed review does not close a stage.
Caps: `implement` 2 recovery attempts, `simplify` 2 rounds, `review→fix` 2 rounds. On a third round,
stop and report — do not burn budget in silence.

## Roles — authoring vs inspection

- **The agent authors**: product code, tests, docs, evidence records, applying simplify/review fixes,
  re-running measurements. Dispatch it; never type it yourself, not even a two-line fix.
- **The operator inspects**: reading diffs, running gates read-only, grading findings, deciding to
  merge, and the mechanical git work (commit, push, PR, merge, cleanup).
- Why: a hand-edit from the wrong surface is an unaccounted write — the diff can no longer be
  attributed to the agent that owns the code, and the next review cannot reason about it.

## Phase 0 — the dispatch contract

Before any agent run, the increment must be dispatchable. Six clauses, all required:

1. **Observable pass condition** — one sentence a command can judge.
2. **Judging artifact** — the command / file / browser observation used to assess it.
3. **Failure control** — what counts as "not achieved", stated up front.
4. **Out of scope** — an explicit "we are not doing X" list, to stop scope drift.
5. **Evidence plan** — which rows get measured, at which tier, with which counter.
6. **Mergeable alone** — the PR is safe to merge by itself; no unmerged sibling is required.

Scale rule: one goal ≈ one agent run (≤12 h) ≈ one PR. If a goal needs two PRs, it was two goals.
If the contract fails any clause, fix the contract — do not dispatch and hope.

## Phase 1 — branch and dispatch

1. `git fetch origin --prune`, fast-forward `main`, branch `feat/<kebab-outcome>` **from
   `origin/main`**, never from a stale local main. Report the base SHA every time.
2. Dispatch one implementation run carrying the goal file, the repo's contract docs, the most recent
   comparable increment as the shape reference, the exact gate commands, and "do not commit/push".
   Use `scripts/gdd.py stage` so prompt, run name and ledger row come from one template.

## Phase 2 — verify before believing anything

The agent's report is a claim, never evidence:

- Run the repo's gates yourself and read real exit codes.
- **Exit 0 means the process ended, not that the phase finished.** Read the run's final assistant text
  (`answer.md`): a report ending with "the gate is running, waiting for its result" ended mid-gate.
  Resume it, or run the remaining gates yourself — never accept the exit code as completion.
- **A non-zero gate that names a missing build output is a prerequisite failure, not a regression.**
  Read the message before calling it a delta; produce the artifacts and re-run.
- Map every contract clause to a test name or evidence row; a clause with no test is unfinished work.
- **An assertion that only checks a count is not verification.** A clause "proven" by
  `assert(checks > 0)` stays green after the entire section it guards is deleted — read the
  assertion's substance, not its existence. Raise a weak proof test as its own increment and tell the
  operator; do not let it be absorbed silently into the current apply round.
- Diff the plan's file list against `git status`; missing tests or docs are the usual gap.
- Re-run gates on the FINAL tree, even if they passed earlier — a resumed run keeps adding code and
  the counts move.
- Research-outcome increment: the deliverable is a decision, not a feature →
  [`references/evidence-fairness.md`](references/evidence-fairness.md) before accepting any
  "faster/cheaper" claim.

## Phase 3 — simplify, then apply

1. Dispatch `simplify`: report only, standalone mode — never a pipeline mode that applies silently.
2. Read the report; dispatch `apply` with the accepted numbers and a one-line reason per rejection.
   A bare "apply all" hands the skill permission to delete tests and evidence.
3. Accept: invariant fixes, misleading names, duplicated fixtures, tests that would still pass with
   the semantics swapped. Reject: deleting a clause-pinning test, deleting an evidence row or a
   disclosed measurement, unmeasured micro-optimizations, sentinel encodings that break
   default-value semantics.
4. **A "dead / unreachable / unused" finding needs mechanical evidence, not a reviewer's confidence:**
   a reference search (zero call sites) or an instrumented run proving the branch is never taken. An
   unevidenced deletion of a defensive guard is how a contract check disappears. Conversely, an
   unreachable branch that cannot run is dead code and keeping it "just in case" is the failure —
   decide, and record which way.
5. If the accepted set touches measured consumers, re-run the measurement harness — not just tests.

## Phase 4 — review, then fix

1. Dispatch `review` (report only) only after the simplify fixes are applied, so the reviewer reads
   the tree that will ship. The stage range is `origin/main..HEAD`, so **commit the agent's stage
   output before dispatching the next stage**: `gdd.py` does not refuse a dirty worktree, and
   uncommitted apply fixes are invisible to the reviewer's diff and one stray `git checkout` from
   gone. Commit, rebase onto `origin/main` when the branch has fallen behind, then confirm the
   `--dry-run` range covers exactly the whole increment.
2. Grade by what is FALSE, not by the reviewer's severity label: a P2 that makes documentation state
   something untrue outranks every tidy-up. Gaps that pin a documented promise are real; gaps that
   mirror an internal shape are not.
3. Dispatch `fix` with a per-finding table requirement and an explicit reason for anything judged
   invalid. A silent skip reopens next round — that is why the table is mandatory.

## Phase 5 — gates, commit, PR

1. Re-run gates on the exact tree you ship; commit with explicit paths; push; open the PR.
2. **Before opening the PR, prove the branch is not behind main.** `git rev-list --count
   origin/main..HEAD` reads `1` whether you are one commit ahead of the current main or one commit
   ahead of a main that has since moved — it cannot see behind-ness. Check
   `test "$(git merge-base HEAD origin/main)" = "$(git rev-parse origin/main)"`; when it fails, a sibling
   PR merged mid-increment and you must rebase onto `origin/main` first, or the review range is not
   exactly one increment.
3. The PR body is a contract artifact: what landed, decisions with explicit non-adoptions, one
   evidence table with its tier and counter, a **Known limits** section, and the real test plan.
4. Treat PR checks as a floor, not a gate — Phase 6 decides.

## Phase 6 — merge gate (mechanical, not remembered)

```bash
scripts/pr-merge-check.py <pr> --repo <path> --verified-head <sha> --gates-rc <rc> [--marker TEXT]
```

Boolean lines and a verdict; exit 0 = merge allowed. `--verified-head` is the SHA you actually ran
the gates on (usually `git rev-parse HEAD` in the worktree you verified), and `--gates-rc` without it
is `UNKNOWN`. A PR whose branch is not checked out reports `head not verified`, never a false mismatch;
a merged or draft PR reports `pr not open` / `pr is draft`. A repo with no machine-review bot reports
`marker: none` and stays blocked unless `--allow-no-machine-review` is passed explicitly. Never merge
on any other basis:

1. every CI check green **on the head SHA**;
2. machine-review marker `status: completed`, `has_any_findings: false`, **on that same head SHA**;
3. unresolved review threads = 0;
4. local gate re-run recorded for this tree (no `--gates-rc` ⇒ `UNKNOWN` ⇒ blocked).

Then `gh pr merge <N> --squash --delete-branch`, `git fetch --prune`, `git checkout main`,
`git pull --ff-only`, prove `gh pr view <N> --json headRefOid` equals the head you verified, report.

A review bot typically posts minutes AFTER CI turns green; a merge fired at "checks pass" skips it
every time. A push does not trigger a re-review — request one and match the marker's `commit_sha` to
the NEW head; the old review keeps the old sha and looks finished.

## Phase 7 — durable state (what makes the next session possible)

Every stage ends with one ledger row. This is the operator's job, not the agent's:

```bash
scripts/delivery-state.py append --repo <path> --goal <id> --stage <stage> \
  [--base SHA] [--head SHA] [--pr N] [--gates "test rc=0"] [--rounds-review N] \
  [--findings "real=3 rej=1"] [--next <stage>] [--note "…"]
scripts/delivery-state.py show --repo <path> --goal <id>     # resume here
```

`show` prints the latest row, the stage history, live git/PR facts (including whether the branch is
**behind** `origin/main`, which the ahead-count alone cannot show), and rewrites
`<task_root>/<date>/<repo>-<goal>/state.md`. A new session resumes with `show` + `git status` +
`git log origin/main..HEAD` — three commands, no archaeology through prompt files.

Answering a bare "how is it going?" mid-flight: read live state, never reconstruct from the
conversation. `delivery-state.py show` (or `gdd.py status`) for the stage and next action,
`gh pr list --state open` for unlanded reviews, `git branch -r` (anything but `main` = unlanded work),
and the launcher's run list for the running stage. Report three bullets — landed / in flight / waiting
on the operator — plus the next stage and who executes it; run the probes yourself rather than handing
the operator commands.

## Phase 8 — reset before the next increment

Fresh run (never resume a previous increment's session); verify the agent build is current;
delete merged local and remote branches; fork from freshly fetched `origin/main`; report the base SHA.

## Dispatch tooling

```bash
scripts/gdd.py stage --repo <path> --goal <id> --stage <implement|simplify|apply|review|fix> \
  [--findings FILE] [--base SHA] [--launcher CMD] [--dry-run] [--wait]
```

Renders the stage prompt from `references/stage-templates/<stage>.md`, refuses to ship an unresolved
placeholder, refuses a second run in the same worktree, launches through the configured launcher, and
records the ledger row only after the launch actually started. Templates are the single source of
prompt text — never keep prompt copies elsewhere.

**A dispatch tool is only proven by dispatching.** A `--dry-run` self-test passes while the launch
path crashes on a typo, so any tool that starts runs needs (a) a hermetic launch test with a fake
launcher on `PATH` that writes a finished `state.json`, (b) a mutation check — revert each fix and
confirm the suite goes red — and (c) one real stage run before the pipeline depends on it. Expect the
first real uses to surface four or five defects (state that lies after a failure, a merge check that
returns green for an already-merged PR, a contract file that moved into the archive); fix them in
batched rounds rather than hand-patching the tool mid-run, and never let the operator's workaround
become the documented interface.

Delivery-specific transport rules: one headless run per stage = fresh context; never resume a previous
increment; parallel increments need `git worktree add` per branch; a fresh worktree has no build
outputs, so run the repo's build before any gate that reads compiled assemblies; never run two heavy
builds at once on a host sized for one — that is an OOM kill of whichever run loses, not a code
failure. Launcher contract, artifacts, recovery and liveness: [`references/transport.md`](references/transport.md).

## Stop conditions — when to stop and ask

- Red line touched: destructive/irreversible action, production, credentials, public release, or
  anything affecting a third party. Report impact + rollback + the exact action, then wait.
- Two attempts in one stage with no convergence: stop, keep the evidence, present the choice
  (different model / narrower contract / abandon).
- Gate red for a reason the change did not cause, on a branch that must ship: fix it as its own
  commit and disclose it — decide, don't silently absorb.
- The contract itself is wrong (contradiction discovered mid-flight): stop, amend it, then continue.
  Never ask an agent to satisfy an impossible clause.

## Project profiles

| Where | What | State |
|---|---|---|
| `references/profiles/_template.md` | the onboarding template — copy, fill, run | shipped |
| `private/profiles/<repo>.md` | your real profiles (git-ignored, never published) | local only |

A profile supplies only what the protocol cannot know: contract location and numbering, exact gate
commands and how to read them, branch/PR/bot conventions, frozen surfaces, evidence conventions,
release path, resource rules. Keep it under ~120 lines; a 500-line profile means protocol facts leaked
into it.

## Pitfalls (protocol level)

- **CI green is not merge permission.** PRs have been squashed with unresolved P2 findings under green
  checks; the findings were real. That is why Phase 6 is a script.
- **The bot review loop repeats after a fix.** A fix produces a NEW review on the new head with its
  own findings; budget a second round instead of assuming one fix closes the PR.
- **A stale completion notification is not a new event.** Re-read live state, then continue.
- **`exit -9` is an OOM kill, not a bug.** The partial tree is usually salvageable — inspect it and
  dispatch a finish/verify instead of redoing the increment.
- **A self-reported "done" with no gate output is unverified.** Ask for exit codes, then run them.
- **Don't start the next increment while the previous branch is unmerged** — the review range stops
  meaning anything.
- **A stalled increment with no ledger row is the expensive failure.** Work sits in a dirty worktree
  and the next session cannot tell "not started" from "implemented, awaiting review".

## Support files

- `references/stage-templates/` — stage prompts rendered by `gdd.py`; the only copy of prompt text.
- `references/phase-prompts.md` — the variable table for those templates (no prompt bodies).
- `references/transport.md` — launcher contract, artifacts, recovery, liveness.
- `references/evidence-fairness.md` — making a "cheaper/faster" claim survive review.
- `references/profiles/_template.md` — per-repo profile template.
- `scripts/` — `gdd.py` (dispatch), `delivery-state.py` (ledger/resume), `pr-merge-check.py`
  (merge gate), `adapters/omp-run.sh` (reference tmux launcher), `tests/run-gdd-selftest.sh`.
