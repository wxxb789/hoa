# Transport — the launcher contract

The protocol assumes each stage is one **headless agent run** that outlives the session that
dispatched it. How the run is started is runtime-specific; this file defines the contract every
adapter satisfies, plus the rules that come from the delivery protocol rather than from any one CLI.

`scripts/adapters/omp-run.sh` is the reference adapter (an OMP-style `-p` CLI hosted in a detached
session). It has two backends: `setsid` (default: own session and process group, no controlling
terminal) and `tmux` (attachable session). Select with `start --backend setsid|tmux` or
`OMP_RUN_BACKEND`; the lock records `{"pid","tmux","backend","started_at"}` so liveness is decided by
the pid first and the tmux session second. For another agent CLI, adapt that script — `gdd.py` only
ever talks to the contract below.

## Launcher contract

```
<launcher> start  --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
<launcher> status SLUG
<launcher> result SLUG
<launcher> answer SLUG
<launcher> kill   SLUG
```

A launcher must:

1. run the agent **detached** from the dispatching session — a child of that session dies with it,
   and a `-p`-style CLI prints only at exit, so a kill at minute 37 costs the whole run;
2. create `<run_root>/<YYYY-MM-DD>/<SLUG>/` and write into it `prompt.md`, the invocation script, a
   live event or output log, `stderr.log`, `exit.code`, `answer.md` (final assistant text) and
   `state.json`;
3. keep `state.json` current, at minimum
   `{"name","state","exit","cwd","started","ended","duration_s"}` with `state` one of
   `running|done|killed|failed`;
4. resolve `<run_root>` from `GDD_RUN_ROOT` (default
   `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs`).

A missing `state.json` means **unknown**, never success.

A launcher that bounds its live event log must not let the bound hide the stream's size. It reports
`events_bytes` (retained), `events_bytes_total` (everything the agent emitted),
`events_truncated` and `events_dropped_bytes` in `status` and in the finalized `state.json`, and any
counter derived from a truncated stream is marked partial (the reference adapter sets
`tool_calls_partial`, `turns_partial`, `cost_partial`).

### Testing the adapter

A stage run may itself be hosted in a tmux session (the `tmux` backend), so a test never runs
`tmux kill-server` and never `kill-session`s a session it did not create: that tears down the run
executing the test, and its stdout dies with it. Use a stub `tmux` on `PATH` or an isolated socket
(`tmux -L <unique-name>`, `TMUX_TMPDIR=<temp>`), as the selftest does.

## Rules that come from delivery, not transport

1. **One run per stage.** A stage run is a fresh session with clean context; that is the point. Never
   resume a previous increment's session — stale context is what makes a later compaction look like a
   false idle, and it carries a finished goal's decisions into a new one.
2. **Waiting is free time, and still one writer per repo.** While a stage runs, write the *next*
   goal's prompt and read its contract so the branch-off is a dispatch rather than a fresh start —
   but do not dispatch it until the current goal is merged. A different repo may run concurrently
   (different tree, no write conflict); the same repo never has two writers. To sequence the second
   repo without babysitting it, arm a small poller that waits for the first run's `state.json` to leave
   `running`, starts the follow-up, and appends each step to a chain log.
3. **Resume only inside the same stage.** If an implement run dies mid-edit, resume its session with a
   continuation prompt that restates: what was interrupted, that the tree is mid-edit, that the work
   continues (not restarts), the unchanged rules (no commit / no push), and the ordered remaining
   steps. Resuming an increment that already has a report is a new stage, not a resume.
3. **Never a bare background job of the orchestrating session.** See the launcher contract, item 1.
4. **Completion is polled, not announced.** A detached run has no completion notification: check the
   launcher's `status` (or `gdd.py stage --wait`) at every turn boundary.
5. **One run per worktree.** `gdd.py` refuses a second run in the same `cwd`; parallel increments get
   `git worktree add` each. When you must override, say why in the ledger note.
6. **Human attach is a turn-boundary operation.** Attaching an interactive TUI to a live run means two
   writers on one session; stop the headless run first, and resume headless afterwards only if the
   stage is unfinished.
7. **Heavy steps are serialized in the prompt itself.** Do not start a measurement/benchmark run while
   a full suite is running on a host sized for one; the loser is killed (exit `-9`) and reads as a code
   failure, not a result.
8. **A fresh worktree has no build outputs.** Run the repo's build before any gate that reads compiled
   artifacts; a gate complaining about a missing assembly is a prerequisite failure, not a regression.

## What to read from a finished run

1. `result SLUG` — state, exit, duration, and whatever cost/turn counters the CLI provides.
2. `answer.md` — the report, treated as a CLAIM.
3. The repo's gates, re-run by you, with real exit codes.

`state=done` means the process exited 0. It does not mean the work is correct, and it does not mean the
stage finished — a report that ends "waiting for the gate result" is a turn that ended mid-gate.
