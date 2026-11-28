---
name: hermes-concurrent-agent-repo-workflow
description: Use when several agents or sessions share one repo.
version: "0.1.0"
license: MIT
author: Zoe
metadata:
  version: "0.1.0"
  areas: "software-development"
  targets: "runtime-agnostic"
  summary: "worktrees per task, fetch-first, detect a peer's reconcile before rewriting, generator-resolved conflicts, squash-merge landings"
  kind: "entry"
  hermes:
    tags: [git, worktree, multi-agent, pull-request, merge-conflict]
    related_skills: [gdd, code-review-gates, kanban-workflows, multi-model-generation-pipeline]
---

# Working a repository several agents contribute to

One repo, several sessions, agents or machines writing to it at once. The rules below keep your work
recoverable and keep you from destroying or duplicating someone else's. The policy layer (branch → PR →
squash merge, fetch before writing) belongs to the project's operating contract; this skill carries the
procedure and the detection commands.

## When to Use

- The owner says other sessions/agents/machines contribute to this repo, or you see local branches and
  `~/…/tasks/…` worktrees you did not create.
- You are about to rewrite, regenerate or resolve conflicts in a file that more than one lane can touch
  (a plan document, a catalog index, CI config, version scalars).
- A PR of yours gained commits you did not write, or a branch you pushed is gone.

## Procedure

1. **Never work in the shared checkout.** One worktree per task, branched off the current remote base:
   `git worktree add -b <type>/<slug> ~/…/tasks/<date>/<task>/wt-<x> origin/main`. Other lanes keep using
   the main checkout; a worktree also gives you a throw-away sandbox for read-only audit lanes.
2. **`git fetch origin` immediately before anything that writes** (branch, merge, push, rebase) and read
   the new head. A peer can move `main` between your last look and your push — that gap is what turns a
   clean PR into a 60-file conflict.
3. **Before rewriting a shared artifact, check whether a peer already reconciled it.**
   `git log --oneline --all -- <path>` · `git worktree list` · `git branch -a --contains <sha>` (a `+`
   prefix means that branch is checked out in another worktree) · `gh pr list --state all`. When a peer's
   commit covers the same findings, **verify their numbers and stop** — a second rewrite over a reconciled
   artifact loses their fixes and re-opens findings they closed. Their reconciliation may also be better
   than your plan (measurement tooling, a sanitized evidence record); adopt it, and report the delta.
4. **Confirm authorship before discarding uncommitted changes.** `git worktree list` (whose branch is
   checked out), file mtimes against your own session, `git reflog`. Back the diff up first
   (`git diff > <task>/backups/<name>.patch`) and only then `git checkout -- <paths>`. A change that looks
   like leftover generator noise can be another lane's in-flight edit.
   **When a rewrite or an owner decision supersedes a lane's uncommitted work, make the discard provable and
   start the successor from a known head.** Snapshot three things — `git diff HEAD > <task>/artifacts/<head>-dirty.patch`,
   the `git status --porcelain` listing, and whole-file copies of every modified path (a patch alone misses
   untracked and binary content) — then *prove* recoverability instead of asserting it:
   `git worktree add --detach <scratch>/verify <head-sha>` (a throwaway, in the harness scratch dir) and
   `git apply --check <patch>` inside it, then `git worktree remove --force`. Restore with
   `git restore --source=HEAD --staged --worktree .`, confirm `git status --porcelain` is empty, and put the
   patch path, its `sha256` and that reversal command in the decision ledger — a later session reads the
   ledger, not the chat. **Name what the restore does NOT supersede:** a finding in the discarded work that
   belongs to a different face (a separate defect in an unrelated file) goes into the successor's brief, or
   restoring the tree drops it silently and the next report counts it as never having existed.
5. **Resolve generated-file conflicts with the generator, never by hand.** Take the base's side for the
   whole generated/version-scalar set (`git checkout --theirs -- <paths>` during a merge, or delete and
   regenerate), then re-run the repo's own command (`python scripts/version.py bump`, `generate_index.py`,
   a lockfile install). Hand-editing a mirror that a script owns guarantees the next run contradicts you.
6. **Merge the base into your branch; do not rewrite history to look tidy.** Where a repo forbids
   force-pushing a feature branch, `git merge origin/main` and resolve; the landing is a squash merge, so
   `main`'s history stays linear regardless of what your branch looks like.
7. **After the merge, re-derive the next step from the new head**, not from your pre-merge notes:
   `git checkout main && git pull --ff-only`, then read the branch's successor work. A merged PR is not a
   finished task, and a deleted branch is a merge, not a failure.

## Pre-flight: prove you are the only writer

Before picking up a defect list, a handover or "these items need fixing", settle who already owns it — the
owner asks, and "nobody else is on it" is worthless when it is wrong. Cite one cleared line per source, not
an impression:

```bash
git ls-remote --heads origin '<feature>*'         # a peer's branch for the same feature
gh pr list --state all --search '<feature>'        # an open or closed PR for it
git worktree list                                  # a checkout holding a branch for it
grep -rl '<feature>' <run-ledger> <run-root> ~/…/tasks/*/   # a peer's run or decision record
```

Distinguish an owner from an assessor: a read-only study of the same subject is not the migration, and a
closed PR is not a claim. A remote branch or an open PR for the same work means stop and hand the item over.

A hit in the task tree is a **brief**, and a peer's brief can prescribe a *different edit to the same lines*
than yours does. Read the hit before you write: when two briefs disagree on the edit — not merely on the
branch — both may pass every gate yet each overwrites the other's line, so stop and put the choice to the
operator with both prescriptions named, rather than applying yours and silently dropping the peer lane's fix.
Two conflicting briefs are an operator decision, not a race to win.

**Check for a duplicate dispatch of your own task before you take ownership.** The operator can send the same
request into two chats at once, and the other session starts on it immediately — so your "nobody else is on it"
is wrong before you have read a single file. Grep the gateway's inbound log for the task's own wording:

```bash
grep 'inbound message' ~/.hermes/logs/agent.log | tail -20        # same request, a chat/thread that is not yours
grep -o 'session=[0-9a-f_]*' ~/.hermes/logs/agent.log | sort -u | tail  # session ids, to map one to its chat
```

A matching request served into another chat names the peer session; read its turn in the same log before you
write. **Your session's start is not the artifact's state.** A peer's fix can land seconds before your first
command, so a read you took a minute ago is not evidence of the current content — re-read the artifact at the
moment you are about to act, and run the gate rather than trusting your earlier snapshot. If it already carries
the intended value, you are an **assessor, not the writer**: verify their result, report it with the evidence
(the artifact's sha/mtime against your own turn), and do not redo the edit. A "before" backup taken at that
point copies the *after* state and mislabels it — take the backup only once you have confirmed the artifact is
still in its pre-change state, and delete a snapshot that turns out to be post-change so it cannot be read as
proof of a change you never made.

**A stop-and-redo order can arrive after the lane has already delivered.** "Halt lane X and redo it" is
answered by the lane's *state*, and that state can already be `done`: its card may read blocked (a worker
that died on a shared-database lock) while its session has already committed, pushed and gone green. Settle
the end state from the *destination* before you act, never from the lane's file or the card's status —
`git ls-remote origin <default>`, `git log -1 origin/<default>`, the gate's own final verdict line, the
publisher's state/receipt. When the goal is already met and the artifact shipped, applying a second version
churns a green, published artifact and buys a redundant delivery; report "already done" with that evidence
(head SHA + verdict) and put *which variant should win* to the operator. A collision report is a deliverable,
not a cue for a second edit, and "stop the lane" is only meaningful for a lane that has not yet delivered.

## Detection: is another lane writing right now?

A branch that gained a commit between two of your own read-only calls has a **live writer**, not a stale
one. Identify it before touching anything:

1. `git log -1 --format='%h %ci %an %s'` + `git reflog --date=iso -5` — a commit minutes old that you did not
   author means a peer is mid-run right now.
2. `find <repo> -path ./.git -prune -o -newermt '<hh:mm>' -type f -print` — tracked files touched in the last
   minutes, including the uncommitted ones `git status` lists; a growing diff (60 → 113 entries) is a writer,
   not noise.
3. If the peer is another agent session on this host, the log names it: `grep <session-id>
   ~/.hermes/logs/agent.log | tail -1` (last activity) and `grep 'conversation turn: session='
   ~/.hermes/logs/agent.log | tail` (maps a session id to the chat/thread it serves). Its own task dir
   (`~/…/tasks/<date>/<task>/`) and backup patches say what it is doing.
   A **dispatched/headless worker** (a board card, another profile) does not appear in the root log at
   all — it runs under its own profile home, so tail `<profile home>/logs/agent.log` for its API-call and
   heartbeat lines to judge whether it is progressing; its live `state.db` is refused by the runtime's
   lifecycle guard ("SQLite database open in this gateway process"), and the card's own run events only
   ever say `running`/`heartbeat`.
   **Read the turn lifecycle, not just the last line.** A gateway `inbound message: … session=<id>` with no
   matching turn-completion/response line for that session is a turn still **open** — a live lane; a
   `tool completed (Ns)` line with a large N means it is mid-long-tool right now, not stalled. Silence in a
   log is not evidence of a dead lane until you have confirmed the turn line closed, and an
   "active sessions" registry can read empty while a turn is open — the turn log is the authority. When you
   filter such a log by field, check which field you are comparing: a `line:timestamp`-shaped grep that comes
   back empty because it compared the timestamp against a line number reads as "no activity" and will have
   you call a live lane dead.
4. `ps -ef | grep -E '[p]aseo|[o]mp|[p]i '` catches launcher-driven runs. No live session, no fresh mtime,
   no owned worktree → you are clear.
5. **Read the launcher's own state for an exact answer.** An agent-run launcher writes `<run>/state.json`
   per run carrying `cwd`, `state` and a pid (`<run root>/<date>/<slug>/state.json`, or the task root's own
   `omp-runs/`): match `cwd` against the repo and `state == running`. That names the live lane exactly,
   where a `ps | grep` matches shim paths, wrapper shells and the prompt text of a neighbouring lane.
   Then confirm the recorded pid is actually alive (`os.kill(pid, 0)`, or the record's own
   `tmux_alive`) — liveness decides, `state` only narrows: `state=running` + dead/absent pid is **not** a
   lane, and treating it as one refuses every future run for that repo.
6. **Put the guard in the driver, not in your habits.** An unattended driver must refuse to start when a
   live run's `cwd` is this repo or when the repo already has open pull requests, and say which; a rule you
   remember to apply is a rule that lapses on the night a long series is meant to start. The refusal is the
   feature: it converts "two writers, discovered later" into "one writer, discovered at preflight".

Then stop or adopt — never write into a checkout a live lane is using. Report the collision with the
evidence (HEAD drift, mtimes, session id) and hand the item to the owning lane.

## A shared append-only ledger has no lock

Decision logs, run ledgers and evidence indexes are appended to by every lane, and none of them takes a lock.
Two lanes that each carry a private running number ("mine was 79, so this is 80") produce **duplicate entry
numbers** the moment their writes interleave — and a number is how later sessions, reports and decision records
cite an entry, so the file stops being citable and each writer reads as the record's owner.

- Re-read the file's tail immediately before appending and take `max+1` from what is **there**, never from your
  own last entry; put the writing session/actor in the entry heading once a second writer exists.
- **Before trusting your own picture of "where this task stands", read the tail for entries you did not author.**
  A scheduled relay on the same task (a block-triage, poller or watchdog job) does not wait for you: it may have
  dispatched an authoring lane, committed, pushed a branch and opened the increment's pull request while you were
  waiting on the owner — and its own entries are where that is recorded, along with what it holds (a patch ready
  to apply, branches it cut, the decision it is blocked on).
- Cite entries in reports by date plus head SHA when more than one lane can write the file; on a shared ledger the
  number is the weakest identifier there is.
- **A shared status surface is read by sessions you cannot see, so refresh it at every stage boundary.** A
  blocker/handoff file left describing a stage that already landed (an open round, an unmerged PR, a lane that
  died) is acted on as current by the next session and by any watcher that parses it. Re-read it, back it up,
  and rewrite it with the four fields a resuming reader needs: current state plus head SHA, the in-flight lane's
  name/session id/run dir and what it may not do, next-in-order, and the single-writer note. The backup is not
  ceremony — it is the same file another lane may have written since your last read.

## Shared-resource leases: blocked is not failed

A writer-exclusion lease (or any atomic lock on a shared resource) creates a third outcome beside success
and failure: the lane acquired nothing, wrote nothing and exited non-zero. Read the receipt before calling
it a defect — `lease status --json` naming another holder, its id and its note is the whole explanation.

- **Do not retry while the holder is live, and never release someone else's lease.** Queue the blocked
  step and re-dispatch only once `status --json` is empty *and* the holder's own release receipt exists
  (`RELEASED` / absent from the active readback) — a released lease is the precondition, not a hope.
- **Re-dispatch as a resumption, not a rerun.** Name the already-reviewed artifact (with its sha256) in
  the prompt and instruct: reuse it if the base has not moved, rebuild only the delta if it has. The
  expensive analysis is not re-paid, and the bytes being promoted stay the bytes that were reviewed.
- **Re-validate the base before reusing anything:** `git fetch` + `merge --ff-only`, then compare the
  candidate's pinned commit against the current head. Moved ⇒ update only the affected parts and state
  what changed; unchanged ⇒ say so explicitly rather than implying a fresh computation.
- **A resumption needs its own artifact path.** A completion gate keyed on "artifact mtime ≥ chain start"
  rejects the report the blocked attempt already left behind, so a resumption writing back to the same
  path fails acceptance for a file it produced correctly. Point `--expect` at a new name.
- **Keep both reports.** The blocked attempt stays as "not promoted" alongside the resumption's report;
  the pair is the audit trail proving the failed attempt wrote nothing, and overwriting it erases that.

## Handing an item to another lane

- **Your post into another lane's chat thread is a record, not a wake-up.** A messaging gateway drops events
  authored by its own bot account before admission, so a peer session does not start a turn because you
  posted. Wake it by naming it to the operator, or by a board/task item the owning profile pulls; post the
  handoff anyway (`<platform> comment <thread_id>`) — the peer reads its channel history on its next turn —
  and write in the post that it is queued.
- Say four things in the handoff: the item, its current state with the head SHA it refers to, what is still
  missing, and what you want the peer to do. A handoff written against a head that has since moved is worse
  than none — re-read the state immediately before posting, and post a correction if it moved.

## Conflict class: mirror scalars

A repo that mirrors one version into every unit (catalog `SKILL.md` frontmatter, package manifests, a
lockfile) conflicts on **the same N files for every concurrent PR**. Expect it, resolve it mechanically in
this order: fetch → merge base → take base's side for the mirrored paths → re-run the bump/generator → run
that repo's gates. Do not "fix" the mirror by hand or by dropping the mirror from one side only, and do
not resolve a mirror conflict by pinning your branch's older version over a newer base.

**Run a conflict census before scheduling the rebases.** When several PRs have all gone quiet and every one
reads `DIRTY`, prove they share one mechanical class instead of assuming real divergence — per branch:

```bash
git merge-tree --write-tree origin/main origin/<branch> \
  | grep -oE 'CONFLICT \(.*\): .*' | sed 's/.*: //' | sort -u   # distinct conflicted files
git merge-tree --write-tree origin/main origin/<branch> | grep -c CONFLICT
```

The same handful of generated paths (CHANGELOG, every catalog `SKILL.md` version line, CI config) showing
up on every branch *is* the mirror signature: one generator run per branch on the fresh base clears them
all, and the branch's own diff is usually conflict-free. A docs-only or one-line PR hits the identical set —
so "my change is tiny" is no exemption from fetch-and-regenerate, and a PR sitting `DIRTY` for days is not
evidence that its content diverged.

**A conflicted PR is not scheduled at all — `pull_request` workflows do not run while it reads
`CONFLICTING`.** So a head that shows no checks, or checks that only appear after a sync, is a symptom of
the conflict rather than a CI outage, a broken workflow or a suppressed event. Read the state first
(`gh pr view <n> --json mergeable,mergeStateStatus`), fetch, merge the base, push, and only then wait on
CI — every sync restarts the check set, so read `gh pr checks <n>` after the **last** sync and never grade
a table belonging to an earlier head. In a repo whose base moves hourly this is the ordinary rhythm of a
long branch, not an incident to investigate.

**A renumbering is not finished until the prose that names the old pair is rewritten.** When the base
advanced past your own version bump, the branch takes a fresh number from the repo's generator; every
record that spelled out the earlier from→to pair (a changelog bullet, a release note, a doc line) now
asserts a transition that never happened. Sweep by the pair's text rather than by filename, and re-run the
repo's own changelog/version checker: a bullet naming a superseded pair is a blocking review finding,
because release prose ships permanently.

## After the merge: prove nothing was lost

A merge that exits 0 proves no conflict is left, not that the base's newer content survived. A resolution
that takes your side of a path the base also moved silently reverts it, and the repo's gates usually do not
read that path at all. Prove it by difference rather than by reading the merge commit:

```bash
pre=<the branch head you merged into>            # not the merge commit
base=$(git merge-base origin/main "$pre")        # what the branch was based on
comm -12 <(git diff --name-only "$base"..origin/main | sort) \
         <(git diff --name-only "$base".."$pre"  | sort)   # paths BOTH sides moved: the clobber surface
git diff origin/main HEAD -- <each of those paths>          # a removal of base content is the clobber
```

The intersection is small and is the whole risk surface; diff those paths between the base's tip and your
head and read for deletions, not for your own additions. After the merge the trivial
`git merge-base origin/main HEAD` is the base's tip, which is why the merge base must be computed against
the pre-merge head. Then re-derive every generated path with the repo's own tool (step 5) and re-run the
gates: a mirror check that passes says the scalars agree, not that the merge is faithful.

**When the increment replaces an explicit list with a data-driven mechanism, prove coverage parity too.**
The list you replaced is the baseline — read what the base added to it since the merge base
(`git diff "$base" origin/main -- <ci config>`) and confirm every one of those entries still runs: present
in the new plan's own enumeration (the runner's `--list`, its manifest), or declared as covered by a named
gate. A mechanism swap loses a command quietly, because the new plan is green about everything it never knew
about; the set of things that *used to* run is the only baseline that notices, and "no coverage was lost"
belongs in the report with those commands named — not asserted from a green run.

## Pitfalls

- **A mandated review gate's pass can still prefer the variant you are replacing.** Run the gate *before* the
  landing step and read its verdict for a preference, not just a pass — a pass authorizes a variant without
  commanding which one, so pushing yours over one the reviewer rates higher is a choice the operator should
  make knowingly rather than read about afterwards. The same holds for the redo itself: a gatekeeper asked to
  adjudicate two candidate landings can return pass while preferring the one already shipped.
- **A peer's merge makes your local branch stale, not wrong.** Re-check `origin/<branch>` and `gh pr view
  <n>` before concluding your push failed or your PR vanished.
- **Do not re-do work you can verify.** Re-deriving a peer's measurements is cheap and worth it; rewriting
  their reconciled document is expensive and destroys their fixes.
- **A `git status` that is clean in the main checkout does not mean no lane is mid-edit** — most lanes use
  their own worktree, so read `git worktree list`, not just the current tree.
- **Do not open the PR from an agent run.** An implementer commits on its branch and stops; the operator
  opens the PR, runs the repo's review phases and merges, so the evidence and the merge decision stay with
  one lane.
- **Pass a PR or issue body by file, never as a shell-quoted argument.** A body carrying markdown backticks
  is command-substituted by the shell before the forge CLI ever sees it, so the PR lands with those spans
  silently gone — while the CLI's own output can read as an unrelated help text, which sends the next reader
  debugging the wrong thing. Write the body to a file and pass `--body-file`; when a body was already created
  mangled, read it back (`gh pr view <n> --json body`) and repair it with `gh pr edit <n> --body-file`.
- **Liveness, not `state`, decides a lane.** `state=running` with a dead or null pid is the ordinary
  debris of an interrupted driver — and since the step-6 guard keys on that record, the debris refuses
  lanes for that repo indefinitely while looking exactly like a live writer. Check the pid before
  refusing: an unreadable or missing pid counts as **live** (fail closed), `os.kill(pid, 0)` raising
  `ProcessLookupError` is dead, and a pid that *is* alive but whose `/proc/<pid>/cmdline` no longer names
  this run's own run dir is dead too — a recycled pid otherwise resurrects a lane that ended days ago, and
  that arm is the one a `kill(pid, 0)`-only check always misses. Prove the guard on all three arms (dead
  pid, live pid naming its own dir, live pid naming another run's) before trusting it. Clear the debris with
  the launcher's own read command (`omp-run.sh status <slug>`), which
  re-finalizes a stale or half-written record from its recorded exit code — never hand-edit `state.json`,
  which the launcher overwrites on its next write, so the edit is lost and the record still lies. When the
  record sits in another session's task dir, run that read and report the outcome to the lane that owns it
  rather than rewriting its files.
- **Never push `main` directly** in a PR-flow repo, even for a one-line docs fix, and never force-push a
  branch another lane may have based work on.
- **One guard rule shared across the repos of a fleet travels as a vendored copy, not as an import.** A
  harness that runs from a cloned checkout or in CI cannot import a file that lives only in the operator's
  home, so the canonical file stays with the skill/home that owns the rule and each repo carries a physical
  copy at a fixed path with the canonical file's SHA-256 in a one-line header, plus a `--check-vendor` mode
  wired into that repo's gate — drift then fails loudly instead of being promised away in a comment. Patching
  the repos one at a time leaves the next one without the rule, and fixing a live copy in place instead of
  the canonical file means the next materialization reverts it.
- **A checkout a runtime reads through symlinks is a deployment surface, not a workspace.** When host paths
  (`<runtime>/skills/<name>`, plugins, a rendered config) are symlinks into one repo's main worktree, the
  branch parked there is what *every* session on the machine executes — a shared worktree sitting on an
  unmerged branch silently downgrades the whole fleet's tooling, and the symptom shows up far away (a helper
  misreading a CLI field, a gate "errored" on a state the committed version handles). Keep that worktree on
  the default branch permanently, land changes as merged PRs, and do the work in a dedicated `git worktree`.
  Redirecting it is a coordinated change: check the branch it holds out into its own worktree first
  (`git worktree add <path> <branch>`) so its commits keep a home, switch and fast-forward, then prove the
  live path serves the new revision (run the helper's own selftest) instead of assuming the switch took.
- **A repo-serving tool must take the repository's identity from git, not from the directory it is run in.**
  A worktree's path is the operator's choice, so a helper that derives the GitHub `owner/name` (or any repo
  name) from the working directory's basename asks about a repository that does not exist the moment it is
  pointed at a worktree — measured: a review lane run from `…/wt-prep-toprule` queried
  `owner/wt-prep-toprule` and died on GraphQL, which reads as an infra failure rather than as the naming
  bug it is. Read `git remote get-url origin`, parse `owner/name`, and fall back to a configured owner +
  directory name only when there is no usable remote; then prove it with a negative control — a checkout in a
  directory named nothing like the repo must still answer the real `owner/name`. Expect the same shape
  wherever a lane is handed a path (review lanes, PR gates, publish scripts): the argument is a checkout, not
  a name.
- **Stage explicit paths, not `git add -A`, in a checkout another lane can touch.** A blanket add sweeps a
  peer's in-flight edits into your commit: their work lands attributed to you, and the lane still running
  believes it is the only writer over a tree it no longer authored — so its own later write looks like a
  conflict it cannot explain.  Name the paths you wrote unless you know you are the only writer.
- **A tree-reverting command kills a lane's uncommitted output, and the next `git add -A` commits its absence.**
  `git restore <path>`, `git checkout -- <path>` and `git stash push` all resolve against HEAD, so a path holding work
  nobody has committed yet returns to its pre-stage revision — typically while you are only trying to undo your own
  mutation-check edit on it. Copy the bytes aside (`cp <path> <task>/artifacts/`) before the experiment and restore from
  that copy, or commit the lane's output on its branch first. If it has already happened, the lane's own run record still
  holds the work: `events.ndjson` logs every edit tool call with its `old_string`/`new_string` verbatim, so replay them in
  order, asserting per edit that the old string occurs **exactly once**, then re-run the lane's tests and the gate on the
  result. Before committing, compare `git diff --stat` with the numbers the lane reported and re-run those tests on the
  exact tree — a smaller increment than the accepted stage produced is the signature of an accidental revert, and a commit
  message quoting the stage's green gate over the reverted tree is how a red head gets pushed.
- **A destination you just created can already be live.** A task card, forum thread or kanban item you open
  *is* a session, and whoever drives it may act before your handoff lands — in this class of work, by
  dispatching a fix lane for the very PR you are still editing. Read the destination's thread before
  duplicating a fix, write the handoff as an input among others rather than as a briefing to a listener,
  and expect to correct your own record once you see what it has already done.
