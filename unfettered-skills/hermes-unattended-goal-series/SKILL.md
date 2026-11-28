---
name: hermes-unattended-goal-series
description: Use when a whole goal series must run unattended.
version: "0.1.0"
license: MIT
author: Zoe
metadata:
  version: "0.1.0"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "conduct a written goal series to completion with no per-goal approval: harness first, encoded dispositions, mechanical single-writer guard, block-not-retry, one-command resume"
  summary_zh: "无人值守跑完整 goal 系列：先落 harness、把操作者判断写成规则、单写入者靠守卫、卡住就报不重试、一条命令续跑"
  kind: "controller"
  consumes: "goal-contract"
  hermes:
    tags: [unattended, goal-series, conductor, single-writer]
    related_skills: [gdd, concurrent-agent-repo-workflow, mechanical-gate-design, omp-headless-orchestration, discord-tasks-forum]
---

# Unattended goal series

The owner hands over a written series of goals (numbered contracts in a repo) and asks for it to be driven
to completion with no per-goal approval — "持续推进直到所有 goals 都完成". The protocol for landing **one**
increment is skill `gdd`; this skill is the machine that loops it while nobody watches, and the rules that
decide whether that machine is safe.

## When to Use

- A repo already carries numbered goal contracts and the ask is the whole series, unattended.
- A long delegated series is mid-flight and a later session has to resume, audit, or hand it over.
- Not for a single increment (that is `gdd`) and not for a multi-card board of independent work (that is
  `kanban-workflows`).

Read [`references/conductor-design.md`](references/conductor-design.md) before building or resuming one; it
carries the script's shape, the file layout, the constant block to patch, the stage runner's exit-code
contract and the resume commands.
[`references/stage-handoff-discipline.md`](references/stage-handoff-discipline.md) covers the seams between
stages — proving a report-only run wrote nothing, handing findings to the apply stage as data, ordering the
review last, re-rendering a round's prompt off the previous round's without inheriting its literals,
bridging two stages without idling a turn — for a driver and for a hand-driven harness alike.
[`references/block-triage-lane.md`](references/block-triage-lane.md) wires a blocked series back to an agent
that repairs it (a condition-gated cron) instead of back to the owner.

## Instantiate, don't rewrite

A new series is a **copy of a working conductor with a patched constant block**: repo, task root, gate
command, model/effort env, template paths, notification channel and thread, the goal table with its
prerequisites and slugs. The loop, the guards and the interlocks already exist — write new code only for a
real design gap, and report which constants you changed. The driver, the goal cards, the stage reports and
the evidence are operator artifacts: they stay outside the repo (a public repo especially), and only what
the increment itself needs gets committed.

## The rules that make it safe

1. **Harness before the first goal.** A goal's acceptance is a gate, so the gate must exist first. The
   series' first increment lands the harness — instruction file, gate (with its own `selftest`), CI, a
   conventions document, an append-only decisions log — as a normal branch → PR → review → merge increment.
   Never let the first implement run invent the thing that verifies it. That increment is a goal in every
   respect except the goal file: its contract is the harness documents plus the PR description, and it is
   hand-driven through the same stages before the driver may launch — the open-PR guard refusing to start
   until it is merged is the guard working, not a broken install.
2. **Select goals from the series' dependency table, at build time.** A goal runs only when every stated
   prerequisite is accepted. Provisional goals are **not** runs: leave them out and report them as the
   decision the owner still owes. Higher numbers added later are not "later work" — they follow
   dependencies too.
   **A goal this host cannot validate is deferred, never closed cheaply.** When acceptance needs a runtime,
   an OS or a product the host does not have (an IDE, a vendor CLI), there are two honest shapes — *defer* it
   or *run* it — and not a third in which the increment ships with a declared evidence gap: that docks the
   goal's own `Done when` while looking exactly like a merge, and every goal behind it then reads a contract
   nobody verified. Deferral means the id leaves the **dispatch registry** (not the goal documents), the goal
   index carries the reason per id, the series' end is restated as the last runnable goal — otherwise a
   `--all` relaunch keeps re-entering a runtime that is not there — and the unblock condition (the
   environment that would make it runnable) is written beside the id, because a deferral with no reopening
   condition is a silent deletion. Prefer deferring a whole goal to grading half of it.
   **A hold written into a status column is not a hold.** Parking an id by editing prose — an index cell, a
   "not dispatchable" note, a line in the goal file — holds nothing while the driver dispatches from its own
   registry and prerequisite table, which is a *different* artifact: the goal file read "superseded, rescope
   pending" and the driver still listed that id as the next runnable one, with an operator stand-down as the
   only real brake. Express the hold where the consumer reads it (leave the id out of the dispatch registry and
   repoint its dependants), keep the goal's own acceptance clauses untouched, and say in both places that the
   hold is **operator-enforced** whenever no mechanical reader honours it — a hold nobody's code reads is a note
   about a stop, not a stop.
3. **One goal, one branch, one PR, one writer.** Branch from freshly fetched `origin/main`, squash-merge,
   and reset before the next goal. Two goals in one repo at once is not a speed-up.
4. **Encode the operator's dispositions as explicit rules** — this is what replaces the human who would
   otherwise grade each round. Working defaults: simplify findings ACCEPT, except anything that deletes or
   weakens a test, an evidence row, a disclosed limit, a non-adoption or a contract statement (SKIP those
   and name them in the apply prompt); review findings FIX, or be answered with evidence in the report.
   A disposition with a threshold in it — "after N rounds of the same class, stop patching and prove every
   rule mechanically" — is **code keyed on the round number**, not a sentence someone must remember:
   compute it into the note the fix stage receives. The same holds for the protocol's own round caps
   reaching one is a signal to cross it deliberately with the reason recorded and to change the mechanism,
   never a request for approval — a cap is an anti-thrash budget. The dispositions cover the *grading*;
   the prompt side is the other half: every report-only dispatch carries the increment's settled-decision
   boundary and its do-not-report list, or the round is spent re-proposing the design that was already
   decided (see [`references/stage-handoff-discipline.md`](references/stage-handoff-discipline.md#bind-the-report-to-the-decisions-already-settled)).
5. **Block, never improvise.** Any unexpected condition writes one `BLOCKED.md` (goal, stage, reason, when,
   log path) plus a notification that states the block **and its route** — repairing under the delegation, a cross-family consult, or the one decision that is his — then exits. Never retry the same failed
   step, never fall back to a weaker gate, never continue into the next goal after a blocked one. The one carve-out
   is a failure **positively classified as transient infrastructure** — a refused or reset connection, a
   timeout, a 429/5xx, or an empty answer whose recorded stop reason is an error — which gets **one**
   recorded retry after a bounded wait, then blocks like anything else. Classify fail-closed: a refusal from
   the lane (receipt or validation failure, dirty tree, moved head), a findings verdict, and a non-zero exit
   that still produced a substantive answer are content, not infrastructure — no retry — and content follows
   the normal path: a findings verdict is dispatched to the fix stage and never writes `BLOCKED.md`, while
   anything you cannot positively classify keeps blocking. Without that path a series stops for hours on a ninety-second
   service restart; with it unbounded, it loops — so keep the budget per stage and print it in the state
   file and in the goal's own notification.
6. **Blocking is for conditions, not for your own repairs.** A defect in the harness itself — a crash path,
   a misread exit code, a decoder, a size limit, a guard refusing the goal it was written for — is the
   series' own problem: diagnose it from the trace, fix the tool, prove the fix with a probe that
   reproduces the original failure, and continue in the same run. Turning that into a question spends the
   owner's attention as a retry budget and is itself a defect. Escalate only when the answer changes what
   "done" means, when recorded owner decisions conflict, or when the action is in the red zone
   (credentials, production, public release, spend, third-party systems). When the path is genuinely
   ambiguous, consult a cross-family model (the reviewer model via `pi`) with the trace, the reproduction
   and the options already excluded — then decide, and record the decision and its reasoning next to the
   series (the operator wants questions asked early *when* they are owner questions, and none otherwise).
6. **The guards are mechanical, not habits.** Refuse to start while a live agent run's recorded `cwd` is
   this repo, or while the repo has an open pull request. A rule you remember to apply lapses on the night a
long series is meant to start (see skill `concurrent-agent-repo-workflow` for the detection commands).
   On a repo several sessions share, the open-PR guard means the series **pauses** (BLOCKED + notification)
   while a peer's pull request is open. That is the guard working, not a crash: read the repo's open PRs
   before predicting how far the series will get, and report a pause as by design.
7. **Resumable in one command, provable by a dry run.** A `--dry-run` that dispatches nothing and prints
   the plan plus one `PROBLEM` line per missing prerequisite / dirty tree / wrong branch / red gate; a
   `--start-stage` that resumes an in-flight goal and refuses when it cannot prove the earlier stages are
   committed. **Cover every stage the run can block in, not just the authoring ones:** resume points that
   stop before the push/CI/review/merge tail make a ten-minute outage cost hours of redone implement,
   simplify and review work, because the only way back in is the beginning. The dry run also prints the
   gate-relevant state that can change mid-series and is therefore re-resolved on every run — target
   visibility, whether the CI provider will actually schedule jobs, the notification surface. A state file plus a dated log, so a later session resumes with: conductor status → launcher
   run list → `git status` + `git log origin/main..HEAD` → state file.
8. **Make policy observable.** "Every agent and subagent uses model X at effort Y" is a claim; the run's
   event log is what settles it. Record the distinct model ids that actually appeared per run into the
   state file and report them once. Any policy enforced by instruction rather than configuration needs the
same treatment.
9. **Notify per goal, not per stage**, on start / PR open / merged / blocked. Stage detail lives in reports
   on disk; narrating every stage in chat is the failure mode the protocol exists to avoid. The target must be a
   **durable surface** — a board post or forum thread — never the chat thread the work was discussed in:
   that thread archives, and a driver whose only listener archived goes silent mid-series.
10. **State the horizon honestly before starting**: the goal series' own feedback window times the number
    of goals is the floor on wall-clock, and free-pool inference does not shorten it. Per-goal merges are
    what make a multi-day run acceptable — it can be paused between goals without losing work.
11. **"Run it unattended, don't stop" does not licence a second writer.** The safe reading when the
    driver has never run: launch it anyway and watch goal 1 from *outside* — read the run logs, the gate
    output, the PR; never the checkout. Dispatching a hand-driven lane into a repo a driver owns or is
    about to own is the one act that breaks the single-writer invariant, and it happens exactly when the
    operator feels most helpful. Reserve hand-driven lanes for pre-flight repairs made before the first
    launch, and name them in the handoff.
12. **Cover the driver's silence with an independent check.** Per-goal notifications only exist while the
    driver is alive, so a killed, hung, or silently exited driver is indistinguishable from one that is
    quietly working. Pair the series with a zero-token watchdog — a `no_agent` cron script that stays
    silent unless `BLOCKED.md` exists, the unit is not active while the series is unfinished, or a stage
    has not advanced for hours (`templates/series-watchdog.py` is the copy-and-patch starter) — and keep
    its job id in the handoff. Cap the dedupe window per alert class, and re-alert while the condition still
    holds: a window long enough to outlive the block is a mute button, and a blocked series that pings once
    and then goes quiet reads to the operator like work in progress. While a session is the one that owns
    the series, pair the cron with a **bounded waiter** in that session
    (`terminal(background, notify_on_complete)`) that returns on merge, on `BLOCKED.md`, or on the unit going
    inactive: the cron answers *whether* the series is stuck, the waiter is what wakes the operator *when* it
    changes state. Arm it on the **next decision's own artifact** too — the verdict file of the round whose
    result the next step depends on, the stage directory the loop is about to write — not only on terminal
    states: a waiter that wakes only on merge or block makes the session sit through a stage whose output
    decides what happens next, and reading that output late is the same as not having it. Build detail, dedupe rule and the
    detached-launch nuance: [`references/conductor-design.md`](references/conductor-design.md#liveness--cover-the-silence-not-just-the-failures).

## Scaling to many similar goals

When the series ends in a queue of similar items (N skills to split, N repos to migrate), do not hand-type
N cards:

- Write a generator script beside the cards that re-measures each item from the tree and writes its card,
  then re-run it whenever the queue changes. A card carrying the generator's own numbers states its entry
  criterion in the item's terms, and the queue cannot drift from the tree.
- Keep one acceptance skeleton across the generated cards so every item is judged by the same gate; the
  topic is the only per-item variable.
- Chain the prerequisites to force one-at-a-time execution (`0009 → 0010 → …`), which composes with rule 3
  without inventing a second lock.
- Expect more than one tranche: a second driver that waits for the first to finish and then runs the rest
  keeps a multi-day series alive across a single launch, and refusing to start while `BLOCKED.md` exists
  preserves block-not-retry across tranches.

## Review-loop convergence

- **A fix round that adds verification surface moves the goalposts.** When each audit finding is repaired by
  adding a new helper, needle set or scanning rule, the next audit finds something inside *that* new code —
  a fixed point that never arrives (observed: 4 + 2 + 3 findings over three audits, every one inside the
  previous round's repair). Before authorizing another audit, check whether the planned repairs are
  **corrections inside existing code** (surface-neutral → the loop can close) or new machinery (it cannot) —
  and for a prose-only increment the same test reads: a corrected sentence *inside* an existing statement is
  surface-neutral, while a new claim the next round can grade is new surface and the loop keeps producing.
- **A fix that lands one side of a symmetric pair IS the next round's findings — enumerate the siblings
  before the round closes.** Where a rule is spelled more than once, repair every spelling in the same
  round: the write side of a read-side encoding fix, the consumer of a producer's renamed field, the
  document that still names the field the round renamed, the same path shape under a second relative form.
  Each leftover is an *edge of the round's own fix*, which is why a round that repairs the instance it was
  handed and stops reads as a loop that cannot close when it is one round of unfinished enumeration. Put
  the rule in the fix prompt ("repair every site this rule is spelled at") and require the report to list
  the siblings it checked, including the ones already correct — an unlisted check is indistinguishable from
  a skipped one.
- **Classify a round's finding by *surface*, not by whether it is new** — the same-class trigger is about the
  same *domain*, not the same defect. Cluster the round findings' `path` fields (the per-round
  `review-findings-r<N>.md`, or the lane's `report.md`) and read the file names: rounds that each find a
  genuinely **new** defect in **one shared surface** (one subsystem's logic spread over a few files, e.g. the
  progress/outstanding-call path shared by every target writer) are the systemic class and want the mechanical
  close-out — *even though* every finding is individually new and the diff grows a little each round — while
  rounds landing on **distinct** files/areas are ordinary convergence. "A new finding every round, so it must
  be fine" is the misread: the tempo and the surfaces, not the novelty, are the signal. Read the count as a
  trend beside the constant, exactly as for a cap stop.
- **Churn observed from outside a live, owner-blessed loop is not itself a licence to interrupt it.** Before
  stopping a run whose rounds keep finding things, read the driver's constant block: if it already carries
  the post-cap systematic switch (ordinary rounds → a scoped audit of a **frozen obligation list** → a bounded
  self-continue → a block for a design fork), then the mechanism the same-class rule asks for is *already
  encoded* and the run is behaving as designed — label the churn with its surface cluster, predict the
  endgame from the constants (round number where the audit starts, the cap, what the cap block asks), and
  **pre-draft the shortcut** (the systematic sweep it will fall back to) rather than stopping a blessed
  bounded loop. Intervening by hand is for when the loop's *instrument* is the problem, not when its tempo
  alarms a reader; escalate only when the constant block carries no such switch.
- **Report the head the audit actually read, not the head in hand.** A CI repair inside the wait loop moves
  the branch head after the audit's target was captured, so a blocked-record built from the captured
  variable names the wrong commit. Read the reviewed head out of the audit report itself.
- **A green local gate does not predict a green matrix on other platforms.** A new assertion whose
  *expectation* is built from the local host (temp paths, quoting, separators) passes on Linux and fails on
  `windows-latest`. The real runner is the referee; treat that red as content to repair, not as infra.
- **Price a stop condition in wall-clock before you design it: a gate that asks the owner once per round
  spends his wake-ups, not his judgement.** A letter round-trip costs hours of dead run (the owner is
  asleep, at work, or answers into a thread nobody relaunches), while the round it gates is tens of minutes
  of machine time. Once the loop is converging — the findings trend above — buy the *remaining* loop in ONE
  authorization: "repair and re-audit continuously, at most N rounds; stop and ask only to decompose, to
  accept a residual, or to cross a budget", and offer that continuous grant as the recommended option
  whenever a fork still has to be asked. Then report what each design cost: sum the dead windows that sat
  between the letters and say it in hours — the owner is the one who notices them, and the design is what
  produced them.
- **When the loop's problem is the instrument, stop the loop before you change the instrument — and land the
  change as its own increment.** A non-converging audit is repaired by the gate, not by another round. The
  sequence: stop the series (the unit, and mute both watch lanes, so a deliberately stopped run does not get
  paged about — mechanic and resume condition are under the block-triage pitfall below), **leave the in-flight
  goal's PR open and unmerged** at the head the last round wrote (merging a half-reviewed head to "clear the
  deck" is the one act that leaves the mechanism change unverifiable against the thing it was built for),
  record the decision with its evidence chain, then land the mechanism change as its own branch → two-stage →
  squash increment off freshly-fetched `origin/main`, and only then resume the goal. Three corollaries: the
  mechanism increment belongs in its **own worktree**, never the checkout the (stopped) driver owns — a
  stopped driver is still that tree's writer, and a harness hand-edited in it is a second writer the next
  launch cannot see; and the change must be **merged** before the resume, because the resumed goal's
  acceptance is exactly what the new gate will judge. Third corollary: this increment has **no numbered
goal**, so the driver's own stage dispatcher (it requires a goal id and a goal-file substitution) cannot
launch it — render the stage template by hand (repo name, repo path, base and head SHA, the increment's
slug, and the plan document standing in for the goal file), append a note saying there is **no goal
file** so the lane does not hunt for one it will never read, and launch through the same launcher
contract. Only the contract's *address* changes: same stage order, report-only simplify, operator-run
gates, same caps — the plan document plus the PR description carry the clauses the goal file would have.
- **Superseding the attempt is a disposition the driver cannot see — capture the head before the branch goes.**
  When the fork that ends a non-converging loop is *abandon this attempt* rather than *change the instrument*,
  the pull request closes unmerged and its branch gets deleted, and the reviewed artifact is then unreachable —
  which is exactly the evidence the narrowed replacement has to be red against. Tag the head first
  (`git tag archive/<goal>-pre-<fork> <sha>`), push the tag, and delete the branch only once the tag is on the
  remote; then keep the superseded attempt's review log as the corpus of negative cases, carrying them into the
  narrowed contract as **must fail without the mechanism / pass with it** rows rather than as prose.
- **When two forks have not closed the loop, decompose the goal along its proof obligations — and land the
  verifier first.** A goal that has already survived a narrowed restart and an instrument change is too large
  for one contract to judge: split it into ordered increments, one per proof obligation, ordered so the
  **independently-checkable artifact lands first** (the checker and its fixtures, frozen), then the facts
  everything else depends on, then the semantics, then the lowering — so no later round can move the thing that
  judges it. Two clauses make the split bind instead of decorate: each increment's contract states its
  **Non-scope** as the named artifact a later increment owns, plus its own **changed-path set**, so "this
  increment did not touch that surface" is provable from the file list; and the new dependency chain is
  registered in the driver **in the same increment**, because the goals that depended on the original id must
  be repointed at the last increment of the split, or they branch off a tree where the feature never landed.
  Keep the original goal file as the umbrella contract — its status becomes *decomposed* and its id stops being
  runnable — rather than deleting it: the split's rationale and its per-increment obligations are what the next
  reader needs, and the driver's goal table is what decides which ids are real.

- **A convergence breaker's default action splits on whether the residue changes what "done" means — and the
  merge side is capped.** A breaker that trips because the findings count stopped falling (P0/P1 flat or
  rising) while the executable surface kept growing is a *disposition* question with a known answer, not a
  fork to hand back: consult a cross-family model with the decomposition, the per-round findings curve and the
  executable-surface bytes, then act on the reading. *Surface/document-class* residue (new text pressing on
  new text, records out of step with the implementation) → a **single** one-time residual merge, in the
  accepted form: the residue **and its diagnosis** written into the increment's own evidence as a closeout
  section, the repo's no-machine-review flag on the merge check, one decisions-log entry. *Definition-changing*
  residue (splitting a goal, a semantic trade-off, more budget) → **stop and ask**, never re-decompose
  unattended. Bound the merge side as a count in the driver (`0` disables it) and print it in the block
  reason: uncapped, "one bounded residual" becomes the loop's way of merging past unconverged work a round at
  a time, and the count is what the next reader checks. State in the same record what the grant does **not**
  cover — merging ahead of the two machine stages on an ordinary round, widening the chain, touching a goal's
  `Done when`.

## When the owner delegates the judgement

The owner's standing rule (state it back to him once, then encode it): **decide what you can decide;
when you cannot, consult a cross-family model; only ask the owner if neither can decide.** For a series
that means the audit-findings stop becomes a *bounded self-continue*, not a letter round-trip:

- Give the delegation its own constant beside the authorized-round count (`SELF_CONTINUE_ROUNDS`), so the
  cap is `ordinary + authorized + self-continued`; an audit returning findings repairs and re-audits on the
  operator's own authority while the allowance lasts, and only the round at the cap blocks. Print all three
  terms in the block reason and in the notification — a cap nobody can decompose is the next session's
  mystery.
- Make the block at the cap ask for the *consult*, not for a rubber stamp: name the fork (shrink the goal /
  accept a disclosed residual / raise the bound), and reach for the cross-family model (the reviewer model
  via `pi`, medium effort) with the trace, the reproduction and the options already excluded before the
  owner is asked at all. Record the outcome next to the series either way.
- Keep the delegation in the driver, not in the session that received it: the next launch must inherit the
  same authority, or the loop reverts to asking per round the moment a different session resumes it.
- Verify the new branch the same mechanically as a bumped budget: run the round dispatcher by hand for the
  round numbers the constants now produce — the self-continue rounds repair and continue, the cap round
  blocks, a clean audit returns — with the stage runner stubbed, before launching anything.
- **Record the endgame before the round that triggers it lands.** The consult answers a fork (repair, then
  merge with a disclosed residual / decompose / raise the bound); write the chosen answer and its reason
  into the decisions record *ahead* of the round that will trigger it, so the record cannot be read
  backwards as post-hoc justification. Say in the same entry how this fork differs from any earlier one the
  owner declined — a repaired residual that goes un-audited is a different object from an unrepaired one —
  because that sentence is what a later reader uses to decide whether the delegation actually covered this
  case.

## Pitfalls

- **"Intermittent" is not a disposition a round may report.** A flaky case is a defect with a mechanism
  (a readiness handshake that demands liveness, a bounded wait on a fixed sleep, a state file read before
  it was settled), and the round that produced it has the means to name it. Accept only a named mechanism
  or a reproduction under load, and require the round to re-run the suite many times — at least ten runs,
  at least half under CPU load — inside the same round. A round that introduced a race while fixing
  something else and called it noise has not finished.
- **A number that moved invalidates every artifact written before the move.** A fix round that adds tests,
  lines or bytes leaves the evidence record, the changelog entry and the gate table certifying an earlier
  tree; two artifacts of one increment disagreeing is itself a finding. Re-derive each number on the tree
  you are about to land, and never hand-adjust one to match.
- **The operator does not edit the tree between rounds, or while one is live.** Consecutive rounds
  (fix 2, fix 3, closeout) write the same files; the temptation to get ahead — bumping `VERSION`, writing
  the changelog entry, regenerating an index — moves the tree a live run is measuring. Dispatch strictly
  one round at a time and let the round that owns the bookkeeping do it. The same holds for the **verifier**:
  an independent mutation check is itself a write, so never overlap it with a live gate or a round's own gate
  run, and give it a restore on an `EXIT` trap so an abandoned window cannot outlive the check — a gate green
  observed inside a mutation window proves nothing and must be re-run on the restored tree (protocol:
  skill `delegated-work-acceptance` §1).
- **An increment authored by hand before a resume must be committed — a driver's diff is committed-only.**
  Retrofitting a contract and handing it back at a post-authoring stage is a legitimate resume (rule 7), but a
  driver normally answers "what did this increment change?" from a committed range
  (`git diff --name-only <base>...HEAD`), so an uncommitted goal/plan/instruction edit is invisible to the guard
  that decides whether a bookkeeping or doc-fix round is still owed: the driver dispatches a round for work
  already sitting in the worktree, and the duplication surfaces later as an odd diff nobody expected. Author,
  run the gate, **commit**, then relaunch at the post-authoring stage — the dirty tree is right when a live
  stage owns the checkout and wrong when you are handing the increment over.
- **A contract authored for a goal that still owes its implementation is a prep increment, not that goal's
  increment — hand it to the driver at the goal's post-authoring stage and the goal is marked accepted with
  nothing implemented.** The authored artifact (a narrowed contract, a plan, generated goal cards) is a
  legitimate increment that lands as its own PR, but driving it through the series as the *goal's* increment
  makes the merge write the goal's `done` ledger row, and the prerequisite table then counts the goal
  accepted: the implementation the goal exists for never runs, and every goal behind it branches off a tree
  with no feature in it. Land a prep increment the operator's way — branch → PR → merge directly, **no ledger
  row** — and confirm the convention against the record before relying on it (`grep` the ledger for an earlier
  prep's goal id: it has no row at all). The tell that a run is about to do this is a dispatch at a
  post-authoring stage whose increment changes documents only.
  **Order prep increments by what the queued goals will read.** A binding rule, a boundary/layout change or a
  gate that the queued goals are accepted against belongs *before* those goals run: a repository-wide rename
  (a carried tree moving into its own folder, a root reorg) conflicts with every in-flight branch, so the only
  safe window is while the runner is stopped — and a stopped driver is still that tree's writer, so the
  migration lands as its own prep increment in its own worktree, never in the checkout the driver owns.
  Landing the rule after the goals it governs is how a series ends with implementations that satisfy the
  contract it just replaced.
- **A bulk stage must be verified by content, not by path — two artifacts can share a basename.** Staging
  several file sets through one flat directory (a scratch or backup round trip, a bulk copy, a regenerated
  set) silently overwrites the ones that collide: a goal file and its plan routinely share a slug
  (`<goal-slug>.md` under `docs/goals/` and under `docs/plans/`), and whichever copy runs last wins — so the
  merge lands a goal file whose bytes are plan text, at the correct path, with the gate green, because every
  check in the pipeline reads paths and diffs and none reads the artifact's own identity. Write each set
  directly where it belongs instead of routing it through a shared staging directory, and after any bulk
  stage print the first line of every affected file and confirm each matches its expected kind before
  committing: one `head -1` over the staged set costs seconds against a wrong artifact that is already
  merged and already relied on.
- **A per-stage round cap counts the record, so a goal redone under a new contract can never re-enter.
  Enumerate the pairs from the ledger and pass the override — with a passthrough, because the driver usually
  does not expose the flag.** `gdd` refuses a stage once N dispatches are recorded against that `goal:stage`
  (`implement has already run 2x for this goal (cap 2)`), and the rounds a **superseded** attempt consumed are
  still on that goal's own rows: the narrowed replacement blocks on its very first dispatch, reading exactly
  like a fresh defect. Give the series an operator passthrough from the start — an env var listing the
  `goal:stage` pairs (`SERIES_OVER_BUDGET=<goal>:implement,<goal>:simplify,<goal>:review`) that the dispatcher
  appends the override flag for and logs per authorization — rather than hand-editing the driver mid-run. Read
  the pairs out of the record instead of guessing them: every capped stage the abandoned attempt ran needs its
  own entry, and the per-stage counts are one `awk` over the ledger's goal column.
- **A standing operator disposition belongs in the driver's policy, not in hand-edits at each merge.** When
  the owner relaxes a gate for a window ("use the independent review lane instead of CI until the repo can
  run CI again"), encode it as a precondition the driver re-reads, marks in the record and the PR, and that
  expires without anyone remembering: a human bypassing the gate by hand works exactly once, and by goal 7
  nobody remembers which merges took the shortcut.
- **A constant patched in an already-running driver keeps its old value.** Notification target, model and
  effort are read at process start, so editing the constant redirects the *next* launch only — say which
  notifications still route to the old surface instead of assuming the patch took effect live. This applies
  hardest to the **stop conditions**: raising a round budget in the file while the unit runs buys nothing,
  and the series stops on the old number hours later looking exactly like a real signal. Patch the file
  *and* restart the unit in the same breath whenever the new value must govern this run, then confirm the
  new value is what the live process holds — a restart that re-attaches at the current stage is seconds,
  the stall it prevents is hours. **Prove the patched value selects the branch you meant before launching,
  rather than reading the consequence out of the log a stage later:** import the harness module in a throwaway
  interpreter, replace its process-launcher and its logger with recorders, call the round dispatcher by hand
  for the round number the new value produces *and* for an ordinary round, and assert on the argv each built —
  the special round carries the extra argument and the label, the ordinary round carries neither, and the
  derived cap comes out of the module rather than out of your reading of it. Side-effect-free, seconds, and it
  is the difference between a launch you can predict and a launch you can only watch.
- **The implementer's own green gate is not evidence for an environment-dependent defect.** Re-run the gate
  yourself in *both* the environment that failed and the normal one; a fix proven only where it already
  passed has not been proven, and "it works with the shim" needs the run that fails without it as its pair.
- **Probe the lane runtime before the series leans on it, and probe it with negative controls.** An
  unattended loop cannot discover a runtime property the first time it needs it: establish invocation
  shape, event schema, session binding and failure exits on a real multi-round run before goal 1 —
  including the controls every report omits (resume from another directory, unknown session id, empty
  input). A session id bound to the directory it was recorded in is a gift, not a constraint: the CLI
  then enforces one worktree per goal without the guard having to. Recipe and the probed facts for the
  DSH lane: [`references/lane-runtime-probe.md`](references/lane-runtime-probe.md).
  The probe includes the launcher's **argument contract with the dispatcher**, because the dispatcher
  hands the stage-result schema to whichever launcher is configured: a host launcher that parses only its
  own flags dies before the first agent turn (`unknown arg '--schema'`) and leaves no run dir, events or
  answer — a stage failure that reads like a lane defect and burns a ledger row with nothing to grade.
  Accept the flag explicitly (resolve it to an absolute path, export it for the run, record it in the
  run's `state.json`; forwarding it natively is not required, results stay prompted JSON); a launcher that
  silently swallows unrecognised flags hides the same mismatch more expensively, launching a run whose
  schema contract nobody honours. Re-diff the launcher's accepted flags against the dispatcher's argument
  list whenever either side is upgraded or re-materialized, and prove it with one real dispatch — not a
  `--help` read, and not the first goal of a long run. The accepted **value grammar** is part of that
  contract: a duration flag taking a single unit token refuses a compound figure before the run starts, and
  the reasoning effort belongs to the dispatch or the stage template that pins it — a prose instruction
  inside the prompt to downshift is not honoured, so size the stage to the pinned effort instead.
- **The likeliest cause of a multi-hour stall is a budget constant, not a broken stage.** When a series has
  sat in one state for hours, read the constant block beside the state file before analyzing the stage: a
  stop condition inherited from a different repo (two review rounds, one recovery attempt) turns a verdict
  the series can repair into a question for the owner, and the driver then looks exactly like one doing long
  work. Re-derive every budget from the comparable increment's observed round count when instantiating, and
  put the number and its reason in the decisions log. An alert having fired over that stop proves the channel
  works, never that the stop was right — notification coverage is not a substitute for a correct stop
  condition. Before treating a cap stop as divergence, read the **per-round findings count**: a series that
  goes 5·4·5·6·4·3·2 with every round on a new surface and nothing re-raised is converging and needs the
  re-derived budget, while a flat or rising count with repeated surfaces is the systemic problem the
  cross-family consult is for. Record the trend beside the constant — a cap crossed deliberately with its
  reason written down is a decision, the same number crossed silently is the next session's mystery.
  When the trend says self-sustaining rather than converging, the escalation is **encoded, not remembered**:
  a systematic close-out (a frozen obligation list committed in the repo, every obligation carrying positive
  evidence and one **executed** mutation — and that list must be **data a command checks, not prose a model
  reads**: make the "rule → evidence" matrix a declaration file whose every row names the artifact that
  pins it and the command that runs it, and add a checker that *executes* each cited artifact, failing when
  it is missing or red, wired in as its own gate step carrying its own selftest; rows no command can check
  are named in the file header with their reason rather than dropped silently, and the seed rows are
  derived mechanically from the prose being replaced — ids derived from each goal's own contract where no
  frozen matrix exists, the step scoped to goals that opt in so a tree whose goals predate the mechanism does
  not go red, and the per-goal obligation enforced by the **driver** (a goal whose list is missing blocks
  instead of dispatching its audit), which is how the list becomes the acceptance surface in place of the
  prose audit) followed by **exactly one** read-only acceptance audit whose scope
  is that list — held in two constants (the extra round count and the list's path, `0` disabling it) so the
  grant is one-time and reversible, with the audit round receiving the list as an *argument* to its lane (a
  round told in prose to "audit against the matrix" re-derives the whole diff and returns the same class),
  Expect that audit's findings to land on the close-out's **own newest tests** — the rows written last and
  reviewed least, where an assertion that agrees with itself hides — so spec every assertion the close-out
  adds as failing-when-removed from the start, and report a findings verdict as the checkpoint working rather
  than as the close-out failing. The stop condition is encoded beside it: an audit finding blocks for decomposition and never starts
  another automated cycle. Record it as *N ordinary rounds + one explicitly authorized audit*, never as a
  raised standing budget. Re-issuing that grant is a one-letter, one-line edit, so the bump must be checked
  before it is launched or it silently buys the wrong stage: **move the count by exactly one, and only after
  the repair that earned it has landed and been pushed**, and **confirm the derived cap equals the next run's
  round number** — the cap is ordinary rounds + authorized rounds, while the number the loop will actually run
  comes from what the stage directory already holds, and when those two have drifted (a round consumed by a
  crash, a stage skipped) the authorized round buys an ordinary review or the audit runs twice, with a log that
  reads identically either way. Carry the authorization's date in its own constant, quoted into the brief's
  label, so the lane's artifact names the decision it ran under instead of a string someone has to remember to
  edit — the artifact is the only record that survives the session that granted it. State in the same record
  what the letter does **not** authorize (a further round, a raised `MAX_REVIEW_ROUNDS`, merging a flagged
  round): the next reader's default otherwise fills the gap with the more permissive reading. Ladder, diagnosis and evidence standard: skill `code-review-gates`, reference
  *review-budget-exhaustion*.
- **Route each stop to the actor who can clear it; an alert that wakes someone who cannot act is coverage
  theatre.** Classify before notifying: a stop the series can repair itself (harness defect, red CI, an
  exhausted per-stage budget whose number needs re-deriving) belongs to the agent that owns the series;
  only a stop whose answer changes what "done" means belongs to the owner. An owner-facing watchdog that
  fires for the machine-repairable kind covers the channel while the series stays dead for the hours the
  owner is asleep — and the alert having fired is then read as the system working. Put the classification
  in the alert, arm the owning session's waiter on the same artifact (rule 12), and treat "needs the agent"
  as unsatisfied until an agent turn has actually run: a notification is not a repair. **Close that gap with
  a condition-gated agent job, not with the owner.** A recurring agent cron whose `--script` gate reads the
  series' own block record and prints `{"wakeAgent": false}` while that record is absent, unchanged, or
  already consumed costs nothing per idle tick; on a real block it wakes an agent carrying the record's
  goal / stage / reason / log. The woken turn must end with the series running again — classify
  (machine-repairable → repair, prove with a probe, relaunch; judgement → cross-family consult, decide,
  record; neither → one question to the owner), never merely narrate. Deliver it `local`: the lane posts into
  the work thread only when the decision is genuinely the owner's. Keep the two lanes apart — the watchdog
  (rule 12) tells the owner the series is stuck, the triage lane makes it unstuck; one job grown to do both
  narrates instead of repairing. Gate contract, branch order, the fixture test that proves each branch,
  relaunch preconditions, a prompt skeleton and how to answer an owner who reports a stop:
  [`references/block-triage-lane.md`](references/block-triage-lane.md);
  starter script `templates/block-triage-gate.py`.
  **Words decide what the owner does with the block.** A post that says "waiting for the owner to decide" *is*
  a stop whoever repairs it: it sits in a durable thread, the owner reads it hours later and answers the only
  question it asks (why did it stop?) while the repair is already running. Name the class and the route —
  repairing under the delegation / consulting a cross-family model / the one thing that is his — and when the
  series gains a self-repair or triage lane, edit the block message **in the same change**: the old wording is
  the half of the defect that reaches the owner, and it keeps its old meaning until someone reads the diff
  (a patch to an already-running driver reaches the next launch only — say which notifications still carry the
  old text). A durable surface also needs its own **resolution line**: when the block is cleared, post the one
  line saying so, on that same surface, or the next glance reads a stall that ended hours ago. Answering an
  owner who reports a stop: [`references/block-triage-lane.md`](references/block-triage-lane.md#when-the-owner-reports-a-stop).
  **A session that takes the writer role must mute that lane first.** When a blocked series is finished by
  hand, the triage job is by design about to wake an agent on the very record the session is rewriting —
  two writers on one tree, and the woken turn cannot know it is the second. Pause it for the duration
  (`hermes cron pause <job-id>`; resuming is its own subcommand too, `hermes cron resume <job-id>`), and
  name the resume condition — the series relaunch — in the decisions record, so a lane left muted cannot be
  mistaken for a lane with nothing to do.
  **Muting that lane hands the series to the session, and turn-bound progress is invisible from outside.**
  With the triage lane paused and the driver unit inactive, nothing advances between turns: a gap measured in
  hours is lost time, not work in flight, and the artifacts stay silent about it unless you write the line —
  state the new driver ("single writer = this thread, the lane is paused") and the resume condition in the same
  status record the watchdog and the next reader read first. Without it, a paused lane plus an inactive unit is
  byte-for-byte the shape of a crashed series, so the next session re-derives the driver from scratch and a
  watchdog's "process died" branch fires on a deliberate stand-down — the idle window then costs a diagnosis
  on top of the idle time.
  **Assume that lane has already acted, and read what it did before your first repo write.** A triage lane is
  not merely *about to* wake: by the time a session picks the series up it may already have dispatched an
  authoring lane, committed, pushed a branch and opened the increment's pull request as a draft — and the
  shared ledger's tail is the only place that is written down. Read the tail for entries you did not author,
  `gh pr list --state all`, `git ls-remote --heads origin` and the lane's own worktrees *before* drafting a plan
  that assumes one writer. Two open pull requests on one base, where one of them renames the paths the other
  edits, conflict on whichever lands second, and the series' own open-PR guard keeps it from restarting while
  either is open: settle during the handover which increment lands first and which branch rebases onto it, and
  record that order in the decisions log — the lane's next wake reads the record, not your chat thread.
  **A hand-driven finish must leave the acceptance record the next launch reads.** A finished goal's
  contract is archived inside the *next* goal's increment, so between the hand merge and that increment the
  only thing marking the goal accepted is its ledger row: write it yourself (base, merge head, PR number,
  the gate result on that head, and one note naming any disclosed residual) before relaunching, or `--all`
  re-runs the goal you just merged from `implement` and re-pays a whole increment. Relaunch with the same
  command the driver was started with and read the first lines of the log: the finished goal skipped as
  accepted, the next goal's branch cut from the freshly pulled `origin/main`, and its first stage dispatched
  — those three lines are the proof the hand-finish landed in the driver's world, not just in the PR.
- **Attribute the wall-clock before you explain a series' pace — and before you change anything about it.**
  "It is slow" has three causes that need three different fixes, and only the timestamps separate them:
  machine-busy time (dispatch → gate → CI → round), dead wait on an owner decision, and dead wait nothing
  notified anyone about (a unit that stopped, a turn that never finished). Parse the driver's own log rather
  than sampling it — `scripts/wallclock-attribution.py <log-dir>` prints each milestone with its delta,
  totals busy against dead windows, and names the largest waits with the events that bracket them — then
  answer with hours per cause and the two biggest dead windows. Do that before proposing a fix: shortening
  a 40-minute round and removing a 19-hour wait are different changes, and the session's own unanswered
  letter is usually on the list.
- **The dry run is not instant.** It fetches and runs the gate, so give it minutes (or run it detached)
  before reading an empty result as a broken conductor.
- **An exit code is a claim; check the artifact it implies.** With codes `0 accepted / 1 findings written /
  2 infra failure` and nothing catching the runner's exceptions, an `UnicodeDecodeError`, a missing binary or
  a bad path make the runner exit **1** — indistinguishable, to the driver, from a real findings verdict. The
  driver then dispatches a fix round for a report that was never written, the next stage blocks on the missing
  file, and `BLOCKED.md` describes an event that did not happen; the tell is an **empty round artifact
  directory** sitting next to a "findings" verdict. Give the runner a crash path that exits a code no verdict
  uses, make the driver require the file the code names before acting on it, and audit the driver's own shell
  helper the same way — one misread integer stops the whole series until a human reads a log.
- **Your own tooling is served from a checkout that may not be on `main`.** When the driver's helpers
  (gate script, stage runner, marker validator) are symlinked into a git worktree — `<runtime>/skills/<name>`
  → `~/repos/<hub>/skills/<name>` — the *branch checked out there* decides which revision the loop runs,
  and that worktree is shared with other sessions. A worktree parked on an unmerged branch two commits
  behind `main` made a merge gate read a CLI field the installed CLI no longer offers, treat the non-zero
  exit as an error, and answer `merge gate errored` for a state the committed version already classified as
  a verdict — a whole series stopped at the last step before merge. Check `git -C <checkout> rev-parse
  --abbrev-ref HEAD` and `log --oneline <branch>..origin/main` before believing a helper's behaviour, ship
  the real fix as a PR to the hub, and to unblock **without** mutating the shared worktree run the committed
  revision from `git archive origin/main` through an explicit override (env var) — recorded next to the run
  as a pin, with its removal condition. The hub checkout itself is a **deployment surface, not a workspace**:
  it stays on `main` permanently and every change reaches it as a merged PR, because the live symlink decides
  what every session on the host executes — treat it as a standing rule, not a per-incident judgement.
  Redirecting one a series is running against is still a coordinated action: check the branch parked there
  out into its own worktree first (`git worktree add <path> <branch>`) so its commits keep a home, then
  `checkout main && pull --ff-only`, then prove the live path serves the committed revision (the helper's own
  `--selftest`) and drop the env pin at the **next** launch, never mid-run.
- **"Accepted" must not be a hand gesture.** If the driver gates every goal on an artifact a human moves (a
  contract file relocated by hand, a status cell edited in a ledger table), the unattended run stops at the
  first goal boundary and looks like a dependency problem (`prerequisites not accepted: <id>`) one second
  after a successful merge. Make acceptance an *evidence* predicate — the landing is in the ledger, the
  gate returned zero, the review marker is clean, no threads are open — and make the bookkeeping (file
  moves, index tables) a task some later increment performs. A human-only step in the middle of the loop is
  the expensive kind of brake.
- **Text-mode capture dies on a repo's non-UTF-8 bytes.** `subprocess.run(..., capture_output=True,
  text=True)` raises `UnicodeDecodeError` the moment what it captured is not valid UTF-8, and a repo that
  vendors or tests real formats reliably contains such bytes (binary fixtures, protobuf samples, encoded
  payloads) — usually *inside the large diff the review stage captures*, so the crash lands on whichever stage
  first captures the whole diff, never on the authoring stages, and it looks like a review failure. Capture
  bytes, decode with `errors="replace"` wherever the value becomes a prompt or a log line, and write an
  artifact that claims to be the operator's exact diff from the raw bytes so byte fidelity survives.
- **A carry-heavy increment is not a reviewable diff.** When one increment's diff is thousands of files
  because it vendors an upstream tree at a pin, the review stage has no verdict to give and no packet size
  rescues it; scope the reviewer to the project-owned delta and let the repo's byte-parity gate own the copy
  (prompt shape and the size check: skill `code-review-gates`). Settle that scope **before** the series reaches
  the stage — the driver builds the review prompt, and the goals queued behind a vendoring goal are usually
  the same shape. Two rules make the narrowed scope honest rather than a loophole: project-owned deviations
  *inside* the carried tree stay in the reviewed set (they are the risk surface), and an unreadable or
  unparsable exclusion list **fails closed** — reviewing everything "just in case" resurrects the original
  defect, while withholding paths silently hollows out the gate the owner thinks is protecting the merge.

- **A real red CI is content, not a block — and the repair must be the driver's own stage.** In strict
  mode a failing check whose causes are mechanical is repaired, not escalated; escalate only when the
  repair would change the repo's gate rules or what "passing" means (the lane then writes a
  `*-declined-*.md` and the run blocks for the owner), and keep the rounds bounded so exhaustion stays a
  signal. The trap is repairing it **from outside the loop**: a fix lane dispatched by hand from a session
  leaves its edits uncommitted in the worktree while the driver is still blocked — nothing wakes to gate,
  commit, push and re-watch, so a finished repair reads as "nothing happened" and the series idles until a
  human looks. Either make it a stage the driver runs (dispatch → local gate → commit → push → re-watch,
  bounded) or attach a waiter that performs those exact steps; a hand-dispatched lane whose prompt says
  "do not commit, wait for my verification" needs that verification scheduled before the turn ends.
  Attribute the red first: a failing verdict read from a PR-level check list can still belong to the
  previous head — a red that arrives seconds after a push, carrying a duration longer than the elapsed time
  since that push, is the previous head's run by arithmetic alone — so requiring the commit's own check runs
  to agree is what stops a stale row from consuming a repair round — and from turning exhausted budget into
  a `BLOCKED.md` for an event that never happened (rule and mechanism: skill `mechanical-gate-design` §4).
- **A relaunch must be idempotent and per-goal stage-aware, or "resume" cannot be expressed.** `--all`
  that re-runs goals already merged onto `main`, plus a single global `--start-stage`, leaves no command
  that means "skip what is done, resume goal 2 at ci, start the rest at implement" — so the operator
  restarts the whole series or nothing. Skip any goal already accepted (archived, or a `done` ledger row)
  and let `--start-stage` apply to the first goal the invocation actually runs; then a relaunch is safe,
  cheap, and useful after every kind of stop, not only a crash.
- **A queue with no driver still needs a scheduled poller — and exactly one writer.** Not every unattended run
  is a goal series: a migration's stages plus a few unrelated repo follow-ups dispatched from a chat thread is
  a *queue*, and its runs carry no completion notification (a chat thread has no turn boundaries, so a
  finished run lands in silence and the queue behind it never advances). A recurring cron that reads the run
  root each tick and advances the queue **at most one step** is the fix — and the moment it exists it is the
  queue's **sole writer**: an interactive session dispatching into the same worktree while the cron ticks is
  two writers on one tree. Keep the cron's prompt self-contained (queue order, one-heavy-job rule, the merge
  bar, "a live run ⇒ record one line and exit with no output"), have it write `BLOCKED.md` instead of
  improvising, and let it remove itself once the queue is empty.
- **A wait inside a session is polled in bounded slices, never one long sleep.** The harness caps a single
  foreground call — a code cell near five minutes, and the cell's interpreter state dies with the cap; a
  foreground command around seven — so one `sleep 600` returns nothing, reads to the operator as a stall,
  and makes the same wait be paid twice. Slice each poll to a few minutes, or hand the whole wait to a
  background watcher that returns on the completion marker
  (`terminal(background=True, notify_on_complete=True)`) and read the artifacts out once it fires. Asking for a
  *foreground* timeout above the harness's cap is the other door into the same watcher — the harness promotes
  that call to a tracked background process with `notify_on_complete` and hands back a job id, which is the
  thing you report to the owner at dispatch. Read completion from the run's own `state.json` leaving `running`,
  never from the waiter's exit code alone; the waiter is a child of your session, so its death costs the
  notification, not the detached run — a
  shell-level background wrapper (`nohup`, a trailing `&`, `setsid`) is refused by the harness outright,
  so the background flag is the mechanism, not a style choice —; a
  detached unit that owns the long run is the third option and is the right one when the run must outlive
  the session.
- **A waiter armed on a path computed once goes stale, and its false completion looks exactly like a real
  one.** Where the run root is date-stamped (`<root>/<YYYY-MM-DD>/<slug>/state.json`), a watcher that
  interpolated one path at dispatch time watches a directory that stops existing when the date rolls at
  midnight: its loop condition fails on the first tick, so it exits at once and reports the run finished
  with an exit code the run never produced — while the real run is still going in today's directory. Have
  the watcher re-resolve the run root on every poll (the launcher's `status <slug>`, or a glob over the
  date roots for that slug) rather than embedding a path, and read an immediate completion with a non-zero
  exit as a path/watcher defect before reading it as a job failure; the two notifications are otherwise
  indistinguishable. **The exit test itself produces the same false completion:** a compound shell condition
  (`A && B || C`) takes the wrong branch through precedence alone, so the watcher exits on its first tick
  and reports the *settled* branch — the healthy-looking one. Never let the loop's own boolean be the
  evidence: require the run's own terminal artifact (`exit.code`, `state.json` leaving `running`) before
  reporting completion, and treat any completion arriving sooner than the shortest plausible run as a
  watcher defect in **either** direction, exit zero included — the false green is the one that ends a
  session while the run it was waiting for is still going.
- **A review/PR helper that derives the GitHub slug from the `--repo` path's basename needs the worktree
  named after the repo.** A worktree at `<task>/wt` made the review lane ask GitHub for `owner/wt` and
  refuse the PR before reading a byte (`Could not resolve to a Repository with the name 'owner/wt'`);
  `git worktree move <old> <task>/<repo-name>` renames it in place and the lane rebuilds its prompt and
  registry on the next run. Check the slug rule before the first dispatch into a hand-made worktree, not
  after the round comes back empty.
- **A CI leg that never acquired a runner is infrastructure however long it took: `runner_name:""`, zero
  executed steps, cancelled at the job timeout (15 min on GitHub) — and `gh pr checks` reports it as
  `fail`.** Re-queue it (bounded, and recorded as an infra event) instead of spending a content repair
  round; it passes at its normal duration once a runner is assigned. This is the positive signature a
  duration-only infra rule cannot see (the same trap `code-review-gates` warns about when it says to
  attribute a red before spending a round) — read the job's `steps` count, not its elapsed time.

## Handing the running series over

A task card, forum thread or kanban item you open **is a live session**, and whoever drives it may act
before your handoff lands — including by dispatching a fix lane for the very PR you are still editing.
Read the destination's thread first, then write a state document that says: what is already done (so it is
not redone), what the receiver must do first, the owner constraints already encoded, where the live state
is, and how to resume in one command. Post it as one input among several, and correct your own record once
you see what the receiver has already done. Channel limits are real: a Discord forum comment is length-capped — 2000 characters was the historical floor and comments of ~2.7 KB post on this host, so keep a handoff under ~3.5 KB or split it at its headings and post the parts in order, with the part index visible in each. An over-long post fails outright, so read back the message id the helper prints instead of assuming the text landed.
