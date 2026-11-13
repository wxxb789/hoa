---
name: gdd-recover
description: >-
  Take a clean handover when a multi-stage unattended run stopped mid-goal: read the state, clear the
  block, re-dispatch the stage that stopped instead of restarting from the top. Use when a run exited
  non-zero, a watcher reports BLOCKED, a stage's state says killed or failed, or an earlier session left
  a ledger-backed run in flight. Do not use for a run that never started, or for one failed command
  inside a stage that is still running.
metadata:
  version: "0.1.49"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "read the stalled run's state, clear the block, re-dispatch that stage — never restart from the top"
  summary_zh: "接手停住的无人值守流程：读状态、清阻塞、重派那一阶段，不从头顶重跑"
  kind: "entry"
---

# Unattended pipeline recovery

Take a clean handover when a multi-stage unattended run (conductor + per-stage agent runs + stage
ledger) stopped mid-goal. A conductor that stopped is not a broken pipeline: it is a state you read, a
block you clear, and a stage you re-dispatch. Restarting from the top is the expensive mistake.

## When to use

- An unattended run exited non-zero, a watcher reports `BLOCKED`, or a stage's `state.json` says
  `killed`/`failed`.
- A handover: another loop, another session, or an earlier you left work in flight.
- "它挂了 / 接着跑 / 你来接手" on a multi-stage, ledger-backed run.

Not for: one command that failed (retry it) or a fresh increment (start it, don't recover it).

## Step 1 — prove who is still writing

Run these before touching anything; a stop caused by a second writer repeats the moment you resume.

```bash
for p in /proc/[0-9]*; do readlink -f "$p/cwd" 2>/dev/null; done | grep -F <repo>
tmux ls
ls .git/*.lock .git/refs/*.lock 2>/dev/null
find <repo> -newermt '-3 hours' -not -path '*/.git/*' -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n'
```

Read them as: a process with the repo as cwd is a writer (your own shell is the only legitimate hit);
a tmux session named after the repo or goal is a live stage; a held `.git` lock is an in-flight git
operation; the newest foreign mtime is the last time someone else touched the tree. Nothing newer than
your own edits means the other writer is gone.

`pgrep -af <script>` on its own proves nothing: the wrapper command line that invokes the check contains
the pattern, so it reports a dead process as alive. Match an absolute script path or ignore self-matches.

Then **inventory every worktree, not just the clone you opened.** A multi-goal run spreads its state across
siblings: the goal branch in one worktree, a side fix in another, and the original clone parked at a
detached HEAD in the middle of a rebase.

```bash
git worktree list
for d in $(git worktree list --porcelain | awk '/^worktree /{print $2}'); do
  printf '%s ' "$d"; git -C "$d" status -sb | head -2; git -C "$d" log --oneline -1
done
```

Read them as: a worktree on a `fix/…` branch with a dirty tree holds work nobody committed — its agent run
can already be `done` with `exit: 0`, and verify-then-commit is the entire remaining step; a clone whose
first status line is `(no branch, rebasing <branch>)` is mid-operation and safe to neutralize with
`git rebase --abort`, which restores the pre-rebase branch and rewrites nothing. Never conclude "nothing was
in flight" from the main clone alone — a worktree you did not look at is a stage of the handover you cannot
report.

## Step 2 — read the stop reason from records

- The block file (e.g. `BLOCKED.md`) — reason, stage, timestamp.
- The interrupted stage's `state.json` — `killed` with exit `130` is SIGINT, i.e. a deliberate stop, not
a crash; exit `-9` is an OOM kill and the partial tree is usually salvageable.
- The conductor log's last lines — the stage dispatched and the failure that followed.
- The stage ledger (`show --repo <path> --goal <id>`) — which stages the record already certifies.

The ledger decides what you may skip: re-running a certified stage redoes finished work and moves counts
that evidence rows depend on.

## Step 3 — clean handover, in this order

1. **Resolve the open question** the stop recorded — status `resolved` plus one line naming the evidence
   you actually checked (probe output, not "should be fine"). Gate and commit that doc change; a dirty
   tree blocks the next resume's preflight.
2. **Move the block file** into the goal's own directory. A lingering `BLOCKED.md` keeps the watcher
   reporting a state you already cleared.
3. **Reset the stale state file** that still says `running`/`blocked` for an interrupted goal.
4. **Confirm the resume preconditions**: clean worktree (untracked files count as dirty), HEAD on the
   increment branch, `origin` fetched.
5. **Relaunch from the interrupted stage**, not from the first stage.

## Step 4 — relaunch detached, then prove liveness

Start the conductor as a tracked background job of the runtime (its own launcher, its own handle), never
as a `nohup`/`setsid` child of the reasoning session and never in the foreground: a conductor owned by the
session dies with it, reproducing the exact failure you were fixing. Verify liveness by artifact growth —
the stage log or `events.ndjson` grows between two reads — plus `pgrep -af <absolute conductor path>`.

## Pitfalls

- **A draft PR blocks a merge gate and is a one-command fix.** Mark ready (`gh pr ready <N>`) and re-run
the gate against the **same** verified head: the head SHA did not move, so CI, the review marker and the
local gate result all still describe that commit. Never re-cut the branch or re-dispatch a stage to
clear a flag.
- **Check the ledger's stage enum before wiring a stage name.** A pipeline writing `merged` where the
ledger accepts only `done` fails on the happy path — after the merge — leaving the record later sessions
read unwritten. Re-read the tool's own enum instead of assuming pipeline vocabulary.
- **A tool whose default log path lands inside the worktree breaks the next stage, not this one.** A CI
watcher defaulting to `<repo>/ci-watch-<sha>.log` leaves an untracked file that trips the next goal's
clean-tree preflight and reads as "someone else left dirt". Pass an explicit logfile outside the repo.
- **`--repo` on gate/ledger helpers is a filesystem path, not `owner/repo`.** The slug form dies as
`fatal: cannot change to '<owner/repo>'` with exit 2 and looks like a missing repository.
- **A second writer corrupts a reviewed head, not just a diff.** A `reset --hard` + commit + push from
another loop can land on your branch mid-stage, so keep the fetch-then-rebase guard (abort on a real
conflict, never force-push) even after the other writer is gone.
- **An aliveness probe that only knows one launch method lies.** A watcher that checks a fixed tmux
  session reports "stopped" whenever the conductor runs as a runtime background job instead, while the
  conductor and its stage are both healthy. Probe the process (an orchestrator `cmdline` whose `/proc/<pid>/cwd`
  is the task dir), treat tmux as one accepted case, and prove the fix by running the watcher once and
  reading its signature (`alive: true`).
- **A block reason the pipeline computed is a claim, not evidence.** When the conductor blocks for a reason
  it derived itself ("still reporting findings after two fixes", "merge gate refused", "pr is draft"),
  re-run the assertion that reason names before dispatching another stage. The reason can be a logic bug in
  the loop that produced it — a `for round in range(1, N)` review loop pushes its last fix and blocks without
  ever asking for a verdict on that head, so a clean head is reported as dirty. One `gh` call is cheaper
  than a fix round spent on a head nobody reviewed.
- **A CI poller reports green on a check set it has not seen yet.** Immediately after a push, `gh pr checks`
  prints `no checks reported on the '<branch>' branch`, which contains none of
  `pending|queued|in_progress`; a poller that greps only for pending words therefore returns "settled"
  before the matrix registers, and the merge gate then fails on a job that had barely started. Green needs a
  registered row count ≥ 1, no pending words, `mergeStateStatus == CLEAN`, and the head unchanged.
- **An empty check set has a second cause that never resolves on its own: GitHub dispatches no workflows for a
  PR whose merge state is `CONFLICTING`.** The poller sees `no checks reported` on every iteration and the
  conductor eventually blocks on "CI not green", which reads as an infrastructure problem and sends you to
  re-run CI, which also produces nothing. Diagnose with
  `gh pr view <N> --json state,mergeable,mergeStateStatus,statusCheckRollup`: `CONFLICTING` + an empty rollup +
  zero runs for that sha is a conflict, not a race. Recovery is a rebase onto the current base and a **fresh
  branch name** with a new PR (`gh pr view` shows the old one `CLOSED` afterwards; never force-push a head
  another reviewer may have read), and the PR body must say the contents are unchanged and only the base
  moved. Any PR that touches a shared append-only file — decision log, changelog, open-questions doc — will
  conflict again on the next goal, so rebase it before opening rather than after it stalls.
- **A ledger row names the stage, not the work in flight.** A later run than the ledger's last row can
already have applied part of the fix and left it uncommitted: `git status` the worktree and read the
newest run dirs the launcher wrote (`state.json`, `answer.md`) before writing a fix prompt, or you
re-dispatch findings that are already fixed — one wasted round (20–40 minutes) and a prompt that can
let its successor revert the earlier fix. The tell is a stage row whose head equals its base while the
tree is dirty.
- **A poll loop that swallows its own parse error is alive and useless.** A watchdog written with mismatched
  quoting (Python embedded in a bash heredoc) records nothing on every iteration while still running its whole
  poll budget, which reads exactly like a slow stage. Require a real state on poll 1 — `running` with the new
  sha is healthy, an empty field or `none` is the probe, not the pipeline — and log each iteration with a
  timestamp so a silent loop is visible afterwards.
- **A resolve step that does not re-read the state it changed is a log line, not a resolution.**
  `gh api graphql` takes the document as `-f query=…`; a bare `-f 'mutation {…}'` exits non-zero with
  `invalid key: "mutation …"`, and a helper that never checks the return code prints "resolved thread"
  for every thread while GitHub still shows them open — the merge gate then blocks on threads that were
  already addressed. Send the mutation with `-f query=… -f tid=…`, assert `isResolved: true` in the
  response, re-query the unresolved count, and only then move on; block with the thread ids if it stays
  non-zero. Test a new mutation shape against a throwaway/already-resolved subject before wiring it in:
  the two forms differ by one prefix and only one of them works.
- **Return the head the review/fix loop produced and feed it to the merge gate.** `head =
  wait_for_clean_review(pr, head)` — the gate verifies that exact SHA. Keep the pre-fix head in the
  variable (calling the wait function without assigning it) and the gate reports `head mismatch`, which
  turns the local gate result into `UNKNOWN` and reads like a gate failure while every other signal is
  green. When a gate says only "head mismatch + gates UNKNOWN", fix the plumbing, do not re-run a stage.
- **A stage killed without a finalize leaves `state.json` claiming `running` forever.** A host OOM kill
  (systemd-oomd above 90% for 30 s) takes the agent and its tmux session together, so nothing writes a
  terminal state: `state.json` stays `running`, `exit.code` never appears, `answer.md` stays empty and
  the last `events.ndjson` write is tens of minutes old. A waiter that polls only `state.json` spends
  its whole budget on a dead run (an hour, once). Bound every wait and decide termination from artifact
  growth (two reads of `events.ndjson` size/mtime), `tmux has-session`, and the launcher's own status;
  `journalctl` showing `systemd-oomd … Killed … due to memory pressure` is the confirmation, and it also
  means the stop was not a code failure. Then treat the uncommitted diff it left as **unverified work**:
  read the diff, run the gate yourself, commit only what the gate certifies. Drive the remaining steps as
  their own tracked jobs with completion notifications, never as one script that sleeps for an hour.
- **The operator's git moves have to be non-destructive forms, because the destructive ones block.**
  `git reset --hard origin/main` is approval-gated as destructive; in an unattended window the prompt
  times out and the branch never moves. `git checkout main && git merge --ff-only origin/main` lands on
  the same commit without a prompt, and it is the step that must come before deleting a branch a
  worktree still has checked out. Two increments at once is one increment per worktree
  (`git worktree add ../<repo>-<goal> -b <branch> origin/main`), with the repo's own install run inside
  the new worktree and a rebase onto the merged head before its PR — never two agents editing one tree.
- **A rebase onto a merged sibling goal moves the fixture baseline, not just the diff.** When the sibling added an emitted asset, a rasterized image or a rendered element, downstream counts change and a packaged smoke or gate script carrying literals (`media: 7 referenced`, `9 images`, `7 objects`) fails on a tree that is correct — the branch is stale, not broken. Re-run the packaged smoke after the rebase, re-derive every literal from its new output, and say in the PR that the assertion followed the fixture instead of being relaxed. The dependency side hides a second conflict: a branch that adds a package conflicts in the lockfile, and the resolution is `package.json` as a union of both sides plus the manager's regenerate-only install (`pnpm install --lockfile-only`), never a hand-merge of lock entries.
- **A pipeline that creates the increment branch with `checkout -B <branch> origin/main` silently drops
  commits you put on that branch.** Anything the next stage must read — a refined contract, an activated
  goal doc, a decision row — has to reach `main` first, through its own reviewed PR; carrying it on the
  feature branch means the stage resets the branch to `origin/main` and dispatches against the old text
  while your commit disappears from the tree (recoverable from the reflog, invisible in the log). The
  tell is a second `branch … from <merge-base>` line in the conductor log after you already committed.
- **A launcher's "another run is active" guard reads `state.json`, so a killed stage blocks the next
  dispatch with an opaque rc=3.** The refusal prints `refusing to start: run(s) still active … (use
  --force to override)` and the pipeline reports only `dispatch failed rc=3`, which reads like a bad
  argument set. Finalise the stale run (`state: failed`, `exit: 137`, write `exit.code`) instead of
  forcing, then re-dispatch: `--force` starts a second run over the same worktree while the old one is
  still the one whose diff you have not read. Check `status` for `state == running` with
  `tmux_alive: false` — that pair *is* the stale record.
- **A known-flaky matrix leg is a fixable defect, not a reason to re-run CI.** When one OS leg fails and the
  failing test is the one the flake ledger already lists, re-running buys a single green and leaves the defect
  for every later goal; re-cutting the goal branch buys nothing. Diagnose it the way the ledger asks (the test
  passes on a re-run at the same commit ⇒ racy test, not a product regression from this head), then fix it
  *off* the goal branch: side worktree from current `main`, agent-driven fix, your own gate run, its own PR,
  merge, and only then does the goal branch rebase and go green. Name the failed leg and the test in the
  handover, so the operator does not read it as the goal's own code failing.
- **Trust recorded gate results, not reported ones.** A gate result the previous operator session ran is
  evidence; a gate result a stage agent described in its answer is a claim. Re-run it through the repo's
  documented entrypoint with its pinned toolchain first on `PATH` (the version-manager shims directory), or a
  bare shell resolves an older system copy and you certify a toolchain the gate never tested.
- **Your own gate run is a plausible cause of the stage's death, so serialize heavy work.** The full
  suite you launch to verify the previous increment and the stage agent's build/scan/test chain compete
  for the same RAM on a host sized for one; the loser is whichever allocates second, and when that is the
  agent its whole session scope goes down. Run your verification either before dispatching the stage or
  after it reports, never beside it, and treat `systemd-oomd … Killed /user.slice/…/session-N.scope` in
  the journal as the explanation for any stage that went quiet around the time you started a suite.
- **Resume the killed stage by session id with a continuation prompt; never restart it.** The partial
  work is usually most of the delivery, and a fresh dispatch re-derives it, reverts decisions it does not
  know were deliberate, or burns its budget rediscovering the tree. Assess what exists yourself first —
  `git status` in the worktree, the sizes of the new modules, and a run of the sub-feature's own test
  file (seconds, and it tells you whether the core path already works). Then resume the same session
  (`--resume <session-id>`) with a prompt that states: it was killed by the OOM killer, the tree's work is
  its own and must not be reverted, the exact files present, what you already verified, the remaining
  steps, and the serial gate order with the ban on concurrent runs. A resume prompt that omits "do not
  start over" produces exactly that.

## Reporting the handover

Status line first (what landed, what is running, what waits on the operator), then evidence bullets with
paths and SHAs, then the single decision you need. Do not narrate the recovery steps — the operator wants
the state, not the archaeology.
