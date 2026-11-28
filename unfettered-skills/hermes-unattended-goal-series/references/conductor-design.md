# Conductor design — the machine that loops a goal series

Layout that works: `<task root>/<date>/<series>/` holds `conductor.py`, the review lane script, an addendum,
`templates/`, `logs/`, `goals/<NNNN>/*.md` (per-stage reports), `artifacts/pr<N>/review-<round>/`, a state
file, `BLOCKED.md`, `README.md` (start/resume) and `HANDOFF.md`. Stage reports are operator artifacts and
stay outside the repo.

Instantiate a series by copying a finished series' directory and patching its constant block (`REPO`, task
root, gate command, model/effort env, template root, notification channel + thread, the goal table with
prerequisites and slugs). A conductor rewritten from scratch loses the guards and interlocks that a series
took to learn; a diff of the constant block is also the review artifact you hand over.

## Per-goal sequence

```
implement → gate → simplify(report) → apply → gate → review(report) → fix → gate
          → commit → push → PR → CI → machine review → merge → ledger → reset
```

- Render every prompt through the protocol's own renderer (`gdd.py stage --wait` for skill `gdd`) so the
template, run name, ledger row and round caps come from one place; pass the project's gate command in.
Never retype a stage prompt by hand — that is how a project-specific rule silently disappears.
- Build the stage templates once as *upstream template + project addendum*, with the addendum the single
  source of project-specific text (regenerate with a script so it is reproducible).
- The script runs the gate itself and reads the **verdict line**, not just the exit code. Pin the
  interpreter by absolute path inside the gate command: a PATH that prepends toolchain shims (so agents find
  managed runtimes) changes what a bare `python3` resolves to, the repo's checks then run on an interpreter
  without their dependencies, and the result reads as a red gate instead of a wrong interpreter.
- A stage that ends `state=done` with trailing "waiting for the gate" language is an unfinished turn: send a
  continuation run naming the remaining steps, not a fresh restart.
- Commit each stage's output before dispatching the next stage, and re-derive every number from the tree.
- Merge only through the merge gate on the head the script itself verified; then write the ledger row — the
  operator writes it, so no row may come from an agent.

## The addendum is where the owner's standing constraints live

Every stage prompt gets the same tail: read order (instruction file → core design → the active goal →
conventions / harness / decisions), the decided stack the increment must not replace, the exact gate
command, the model and effort policy, the escalation channel with its one-per-stage bound (recorded
verbatim in the report, treated as advice and not as evidence), the rule that the repo's instruction file
must either be updated or explicitly justified, the bookkeeping the increment owes (archiving the
previously accepted goal), the uncertainty protocol (most reversible default + a decisions-log entry), and
what simplify/review mean in this repo. Conflicting rules resolve in favour of the upstream stage template.

## Guards

```python
def lane_record_is_live(state):   # the record is not the process — ask the process
    ...                           # os.kill(pid, 0); require the cmdline to still name the run's own dir

def live_runs(cwd):        # <task root>/*/omp-runs/*/state.json, or the launcher's own run root
    ...                    # state == "running" AND lane_record_is_live(state) AND recorded cwd == this repo
def open_prs(repo):        # gh pr list --state open
    ...
def guard_single_writer(): # block with the reason; refuse to start
    ...
```

Run the guard at the start of a goal only; an in-flight goal resumes with `--start-stage`, which has its own
preflight (`HEAD` must not be `main`, and the tree must be clean).

- **A killed lane keeps the writer lock forever, and the guard then reads as a lie.** The state file is
  written by the runner, so a round killed with its session (or by the host) leaves `state: "running"` for
  good; a guard that trusts it refuses to start the next goal with `another OMP run is live in <repo>: <slug>`
  naming a lane that has been dead for a day. Ask the *process*: `os.kill(pid, 0)` for existence, then require
  the command line to still name that run's own directory, so a recycled pid cannot resurrect a dead lane. A
  record with no pid, or a process this user cannot inspect, counts as **live** — the guard fails closed,
  because a guard that loses a writer's work is worse than one that asks a human. Sweep the whole run root
  once you fix it: stale `running` records accumulate silently in every repo a killed lane ever held (three
  surfaced on one host in a single probe, two of them holding other repos' locks).

### Entering a goal mid-flight

- **`--start-stage` belongs to the invocation, not to the goal.** To enter one already-implemented goal at
  `simplify` and then run the rest from their first stage, chain two conductor invocations in one detached
  unit; do not add a per-goal flag for it.
- **The preflight reads the branch in the repo's main checkout.** A branch that lives in a scratch worktree
  cannot be checked out a second time: `git worktree remove --force <worktree>` (the branch survives), move
  the lane's untracked notes out first, then `git fetch` and `git checkout -B <goal-branch> <lane-branch>`
  in the main checkout.
- **Hand a dispatched implement lane over with a one-shot unit**: the released-evaluation loop lives in a
  script that polls the *run directory* of the lane, and two details decide whether it ever returns.
  Resolve that directory by glob (`<task root>/*/omp-runs/<slug>-*/state.json`, newest by mtime) rather
  than a dated path — the run root rolls over and a hard-coded one then waits on a stale run. Require
  `state == "done"` **plus** a finalize marker, and accept **either** marker: the host launcher writes
  `exit.code`, the in-repo adapter writes `finalized`, so a loop keyed on one of them alone waits to its
  own time limit with a finished run sitting beside it. Then verify the branch yourself, do the worktree
  handover and chain the runs. Verify under every condition the increment's defect class depends on — one
  green run is how a branch whose defect only shows under another temp root gets merged (mechanism and the
  runner-side rule: skill `mechanical-gate-design`).
- **Verify from an environment the implementer did not use**: a minimal `env -i` with the operator's real
  `HOME`, a fresh `TMPDIR`, the repo's pinned interpreter and the toolchain's state directory, then keep
  stderr in the gate log — a summary-line-only capture turns a real failure into a bare exit code, and an
  environment identical to the author's reproduces nothing (isolation the runner imposes on suites —
  task-local `HOME`/`XDG_*`, temp roots, prepended shims — is itself a defect surface: skill
  `toolchain-provisioning`, acceptance rule in `delegated-work-acceptance`).
- Write `BLOCKED.md` and stop if the lane ended in a failure state, if its worktree is dirty after the
  notes are moved, or if either verification run is red. Never retry the lane.

## Interlocks that turn a mistake into a refusal

- `--dry-run` requires `HEAD == main`, a clean tree and a green gate, so it cannot report `OK` while the
  harness PR is still open — the interlock that stops a series starting on an unlanded harness.
- Prerequisites are checked from the archive or ledger, not from the plan text: a goal whose predecessor is
  not accepted blocks with `WAIT(<ids>)` instead of branching.
- Bookkeeping follow-ups (instruction file untouched and unjustified, accepted goal not archived) dispatch
  **one** bounded run each and then re-gate; they do not loop.

## Resume

```bash
systemctl --user status <series>-conductor            # is the driver alive?
<launcher> list                                       # live/dead agent runs, resume ids
python3 <task>/conductor.py --dry-run --all           # environment + plan, dispatches nothing
cd <repo> && git status --short && git log --oneline origin/main..HEAD
python3 <task>/conductor.py --goals <goal> --start-stage <stage>   # resume mid-flight
```

Launch the driver detached (a systemd user unit, or the launcher's own detached backend) so a gateway or
session restart cannot kill a multi-hour stage; report the unit name and the log path when you start it.

- **Re-establish the resume preconditions from the repo itself before relaunching.** The resume path asserts
them anyway and every failed assertion burns a cycle: the goal branch checked out in the main checkout,
`HEAD` equal to the open PR's head sha, a clean tree, the PR open (not draft, mergeable), the base freshly
fetched. Read them in one command and put the numbers in the handoff.
- **Chain the resume and the remainder of the series into one unit with `&&`.** `--start-stage` belongs to
the invocation, so the unit runs `<conductor> --goals <in-flight> --start-stage <stage> && <conductor>
--goals <the rest>`: a block in the first stops the chain — that is block-not-retry working — and the unit
then going inactive while the series is unfinished is exactly what the watchdog reports.
- **Reusing a unit name after a failed run needs `systemctl --user reset-failed <unit>`**; even with
`--collect`, a unit left in `failed` refuses `systemd-run --unit=<same name>`.
- **Confirm the resume from the log, not from a notification.** The first lines name the stage it re-entered
and the branch/PR it verified; a driver that resumed and then died emits no per-goal notification to miss.

## The stage runner's exit-code contract

The driver decides what happened from the runner's exit code plus the artifacts it finds, so the codes are a
protocol — and the driver may not trust one on its own.

- Reserve a code that **no verdict uses** for runner failure — `0` accepted / `1` findings report written /
  `2` infra or validation failure — and have the runner's `__main__` catch every unexpected exception, print
  the traceback to stderr and return `2`. Without that path the runner exits `1` on any crash (an encoding
  error, a missing binary, a bad path), which the driver reads as **findings**: it looks for a report that was
  never written, then blocks with a reason naming the wrong event, and the true cause survives as a single
  log line (`UnicodeDecodeError ... in position <n>`).
- The driver verifies the artifact a code implies before acting on it. A "findings" verdict next to an
  **empty round artifact directory** is a crashed runner, not a verdict, and blocks as infrastructure.
- Keep the runner's text capture safe: `subprocess.run(..., capture_output=True, text=True)` raises on
  non-UTF-8 bytes, and a repo carrying binary fixtures puts exactly those bytes inside the big diff the
  review stage captures. Capture bytes, decode with `errors="replace"` for anything that becomes a prompt or
  a log line, and write an artifact claiming byte fidelity (the reviewed diff) from the raw bytes.
- Size what a stage hands to a lane before dispatching it, and decide the review scope instead of chunking
  when the bulk of the diff is a vendored tree (skill `code-review-gates`).

## Notification

One post per goal: `wip` on start (goal, title, model and effort), `review` when the PR opens (number, what
it waits on), `done` on merge (merged head, gate verdict, PR), `blocked` with the reason and the path to
`BLOCKED.md`. Anything longer belongs in the reports.

## Liveness — cover the silence, not just the failures

Notifications are emitted by the driver, so they only exist while it is alive: a driver that is killed,
that hangs inside a stage, or that exits without writing `BLOCKED.md` sends **nothing**, and the series
looks exactly like one that is working. A series nobody watches needs a check that does not depend on the
driver running.

- **Start from [`templates/series-watchdog.py`](../templates/series-watchdog.py)**: copy it beside the
  series' conductor, patch its constant block (task dir, state file, ledger, unit name, goal count,
  stall/repeat windows, snapshot path) and install it as the cron job. The three conditions, the dedupe
  snapshot and the fail-closed readings are already in it — a hand-rolled replacement loses one of them.
- **A zero-token cron script that prints nothing unless a human must act.** Schedule it every 30 minutes as
  a `no_agent` job: stdout is delivered verbatim and empty stdout sends nothing, so the job costs no model
  turn and is silent by default. Alert on exactly three conditions: `BLOCKED.md` exists (carry its
  goal/stage/reason and the one decision the owner owes), the unit is not active while the series is
  unfinished, and the state file has sat in the same `running` stage for hours (a hung stage). Decide
  "unfinished" from the driver's own ledger/log tail — counting merged rows against the series' goal count
  — never from the mere absence of an error.
- **Dedupe through a snapshot file, with a window per alert class.** Keep the alert's hash, its first-seen
  time and its send time under the runtime cache, and re-send only after that class's repeat window.
  Otherwise one stuck series pings on every tick, and a stream of identical pings is how the alert that
  matters gets ignored. The window is a policy knob and the short side is the safe side for the actionable
  conditions: a blocked or dead driver re-alerts within the hour while it stays that way, a hung stage can
  wait several. **One long window across all three classes is a mute button** — the series that most needs a
  human sends exactly one notice and is then silent, which reads to the operator like work in progress.
  Carry the elapsed time since first seen in a repeated alert, so a persisting condition does not arrive as
  byte-identical text that the owner's eye skips.
- **Deliver to a durable human-facing surface** (the owner's DM, the board), never to the driver's log,
  and not to the chat thread the work was discussed in when that thread archives.
- **Launch the driver detached, and keep the failure record readable.** A `systemd --user` unit (or the
  launcher's own detached backend) is what keeps a gateway or session restart from killing a multi-hour
  stage; report the unit name and the log path when you start it. `systemd-run --collect` unloads a unit
  once it finishes or fails, so `systemctl --user status` can no longer show you the exit status of a
  failed run — omit `--collect` when you will want to inspect a dead series, and treat the log file as the
  record either way. The watchdog reads the unit's *active* state, so it reports a collected unit and a
  killed one the same way; that is the intended fail-closed reading.
- **Verify liveness once after launching**, before you trust the silence: unit active, log advancing, the
  first goal's lane directory created, state file naming the goal and stage. Then hand the watchdog's job
  id, the unit name and the log path to whoever resumes.
