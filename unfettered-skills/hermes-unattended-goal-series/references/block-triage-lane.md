# The block-triage lane

A driver that halts writes `BLOCKED.md` and notifies — a message, not a repair. This is the mechanism that
turns that condition into an agent turn which classifies the block, repairs what is repairable, and puts the
series back on its feet with nobody watching. It is the machine-facing half of rule 12; the watchdog stays
owner-facing.

## Two lanes, two audiences

| Lane | Mode | Audience | Job |
|---|---|---|---|
| series watchdog (`templates/series-watchdog.py`) | `no_agent`, stdout only | owner | say the series is stuck, re-alert while it holds |
| block-triage gate (`templates/block-triage-gate.py`) | agent job with `--script` gate | the machine | wake an agent that decides and repairs |

Do not merge them. A single job that both alerts the owner and repairs the condition ends up narrating the
block in chat and leaving the series dead, which is the failure mode both lanes exist to prevent.

## The gate

Job shape: agent mode, `--script <gate>.py`, `--deliver local`, model / provider / effort pinned on the job
itself, unlimited repeat, cadence ~30 min (a block that sits 30 minutes is already the owner's problem; the
lane is for the hours-long stalls, not for seconds).

The script prints one of two things and **exits 0 on both**:

- `{"wakeAgent": false}` — idle tick, no model call.
- a compact digest: goal, stage, blocked-at, reason (truncated), record path, log path, owner-unit liveness,
  and the dedupe hash. The woken agent needs those to start without hunting; nothing else belongs in it.

Branch order (first match wins):

1. **No block record → silent.** A block that got resolved must go quiet without anyone clearing state.
2. **Owner unit *active* → silent, whatever the record says.** This is the single-writer guard, and it has to
   be conditioned on liveness **alone**: while the driver runs it owns the resource, and the record's content
   is no evidence about who is driving. Written as `active` **and** record unchanged, the guard gives back the
   one window it exists for — a live driver that has moved the record on (a new block, the next stage) stops
   matching, the lane wakes, and the turn it wakes into is the second writer the invariant forbids. A guard
   with a conjunction in it reads like a guard and behaves like a coin toss.
3. **Record present, hash unchanged, last wake inside the window → silent.** Dedupe state is
   `{"hash": <content hash>, "woken_at": <epoch>}` in a cache path.
4. **Otherwise → wake** — changed hash with the unit down, or the window elapsed with the unit down.

A driver that exits clears condition 2 by itself on the next tick, so ordering liveness before the dedupe
costs one tick in the single case it delays (the unit died between the write and the read) and buys the
invariant back everywhere else.

The re-alert window is the woken lane's retry budget: too long and a failed repair costs that much dead
wall-clock. Six hours is a working default for a series whose rounds run tens of minutes; print the hash in
the digest so a reader can tell which record a wake belonged to.

## Prove every branch, with the live record untouched

Take the record path, the state file and the unit name from env, with the live values as defaults. Then a
fixture directory can exercise all five cases:

| Fixture | Expect |
|---|---|
| no record | silent |
| fresh record | wake, digest names goal / stage / reason / log |
| same record again | silent |
| same record, window elapsed, unit **not** active | wake (re-alert) |
| changed record content, unit **active** | silent — the single-writer guard; the pre-fix conjunction woke a second writer here |
| changed record content, unit **not** active | wake |

- Assert on the **stdout text**, not on the exit code: both branches exit 0 by design.
- The liveness guard swallows **every** case while a driver is running, so the unit name must be the
  fixture's variable: point it at the real (stopped) unit to reach the wake / re-alert branches, and at any
  *unrelated* active unit (`hermes-gateway.service` will do) to reach the silent one. Test against the live
  unit alone and the branch you meant to prove is unreachable — its "failure" means nothing. Neutralise the
  gate's other suppressing knobs through their own env vars as well (the dedupe state to a scratch path, the
  peer-quiet window to `0`), or one of them eats the test before it starts.
- Prove the silence through the runtime, not by hand: `hermes cron run <id>`, then read
  `cron/output/<id>/<timestamp>.md` — the silent branch is recorded as
  `Script gate returned wakeAgent=false — agent skipped`. That line is the evidence an idle tick costs no
  model call, and it is cheap enough to run before trusting the schedule.

## What the woken agent must do (prompt skeleton)

The prompt is self-contained and its first line sets the contract: **triage the block, do not report it.**
Then, in this order:

1. Read the record, the log/report it names, and the series state file.
2. Classify, and act on the class:
   - **machine-repairable** — red CI, a harness or guard defect, a crash path, a constant that needs
     re-deriving from the observed rounds, a missing artifact, two writers on one tree: repair it. Back up →
     surgical edit → prove with a probe that reproduces the original failure → relaunch. Do not ask.
   - **judgement** — decompose a goal, accept a disclosed residual, a semantic trade-off, raise a budget:
     consult a cross-family model first (the reviewer model via `pi`, medium effort) with the trace, the
     reproduction, the options already excluded and 2–3 candidates; write the decision and its reasoning into
     the     series' numbered decisions log; then proceed on it — one carve-out: a block whose reason is the
     **convergence breaker** does not turn a surface-class reading into an unbounded run of residual merges;
     it splits on whether the residue changes what "done" means, and the merge side is capped (series skill,
     *Review-loop convergence*). "Be safe and ask the owner" is not a classification.
   - **neither can decide** — one message to the owner work thread: one conclusion plus the single thing to
     decide. Then stop. Never idle-spin, never re-ask next tick.
3. Relaunch only on proven preconditions: worktree clean, `HEAD == origin == PR head` (pushed), and
   `--start-stage` taken from the record's stage — never guessed from where the log line ends.
4. Write boundary, stated in the prompt: the lane may edit the harness, the scripts and the task root; it
   does not touch the runtime contract files (identity / operating contract / config — those need the owner's
   approval), and it does not edit the repo tree while a lane or a gate is running (one writer).
5. Every decision becomes a numbered entry in the decisions log: what, evidence path, backup, verification
   command. The next session reads that file instead of re-deriving the reasoning.
6. If the record is gone or the driver is already running, do nothing and print nothing.

## When the owner reports a stop

"The series stopped, why?" is a report about a **surface he is reading**, not a fact about the driver — the
block post sits in a durable thread for hours and keeps its old wording after the block is repaired. Answer in
this order, and never lead with the history:

1. **Find the surface.** Enumerate what the owner can actually see: the work thread's block / start / merge
   posts and its status tag, the watchdog's DM, the last stage notification. Match his wording to one of them;
   it is usually the block post, which is why that post's wording is a defect surface rather than decoration.
2. **Verify liveness from artifacts, not from the state file.** The state file reads `running` for a process
   that has already exited, and says nothing at all about a wedged lane:

   ```bash
   systemctl --user is-active <unit>                # the driver
   ls <task-root>/BLOCKED.md                        # absent = nothing is blocked right now
   stat -c '%y' <run-root>/<slug>/events.ndjson     # mtime advancing = the lane is alive
   date                                             # compare in seconds, not minutes
   ```

   A lane streaming thinking deltas grows that event file continuously, so a stale mtime is a dead or wedged
   lane while the state file still says `running`. Silence from the cron lanes is a fourth signal — read their
   last `cron/output/<id>/*.md` rather than assuming a quiet job means a quiet series.
3. **Answer with the live state first**, then the surface and the event it names, then what repaired it and by
   whom, then what is still his. Say plainly which it is — "it did stop, here, for 40 minutes; it is running
   now" — instead of explaining a run that is in fact alive, and do not make the owner ask twice.
4. **Treat the impression as a finding.** A self-healing block that read as a stop means the notification
   surface is defective (wording, missing route, no resolution line): fix it in the same pass and report it.

## Caveats

- **The job record snapshots the prompt at create time.** Keep the prompt file in the task root so the next
  session and the operator can read intent, but an edit there reaches the job only through `cron edit` —
  check the live prompt in the job store before believing the file is what runs.
- **The lane is task-scoped machinery.** Retire it (remove, not pause) in the same pass that retires the
  series' watchdogs and thread-scoped watchers, or it keeps waking on a record nobody owns.
- **A repair that cannot prove itself buys the whole re-alert window.** The probe plus relaunch belongs in
  the same turn as the diagnosis; leaving it to the next wake turns a 20-minute fix into a 12-hour stall.
