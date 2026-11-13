# Transport — the launcher contract

The protocol assumes each stage is one **headless agent run** that outlives the session that
dispatched it. How the run is started is runtime-specific; this file defines the contract every
adapter satisfies, plus the rules that come from the delivery protocol rather than from any one CLI.

`scripts/adapters/omp-run.py` is the bundled adapter: stdlib Python 3, an OMP-style `-p` CLI hosted in
a detached process, no bash, no `setsid`, no `tmux`. `scripts/adapters/omp-run.sh` stays as the POSIX
reference adapter — it is the one with the attachable `tmux` backend, and
`scripts/tests/test-omp-run-setsid.sh` plus `test-omp-run-stale.sh` pin its behaviour. `gdd.py` calls
whichever command `GDD_LAUNCHER` names (default: the `.py` adapter); for another agent CLI, adapt that
file — `gdd.py` only ever talks to the contract below.

## Platform matrix

| Platform | Adapter | How the run is detached | Evidence |
|---|---|---|---|
| Windows 11 x64, CPython 3.12.10 | `omp-run.py` (executed through `sys.executable`) | `CREATE_NO_WINDOW \| CREATE_NEW_PROCESS_GROUP`: one hidden console the whole descendant tree inherits | **executed** — `python3 -B skills/gdd/scripts/tests/test_omp_run_python.py` on a Windows host, plus one real `omp -p` run through the adapter |
| Linux (Ubuntu 24.04 inside WSL2, distro python3) | `omp-run.py`, and `omp-run.sh` where bash is wanted | `start_new_session=True` in the child (setsid): own session and process group, no controlling terminal | **executed** — the same suite inside the distro, and in CI (ubuntu-latest) |
| macOS | `omp-run.py` | same POSIX path as Linux | **documented, unverified** — no macOS host here. `omp-run.sh` cannot be the default there: macOS ships no `setsid`, so it would need `--backend tmux` |
| WSL2 (Windows host, run *inside* the distro) | `omp-run.py` with the distro's own python3 | same POSIX path as Linux | **executed** for one distro (the row above); the rule below is what a Windows-side launcher gets wrong |

Two rules carry that matrix:

1. **One hidden console, inherited by the run (Windows).** A `.cmd` shim runs through `cmd.exe`, a
   console-subsystem program, so Windows allocates a visible console on every dispatch. The run and
   everything it starts are therefore spawned with `CREATE_NO_WINDOW` (plus
   `CREATE_NEW_PROCESS_GROUP`), never with `DETACHED_PROCESS`: detached means *no* console, and then
   the first console-subsystem process the agent runs allocates one of its own. Measured on Windows 11
   with the same launcher and only the flags differing — `CREATE_NO_WINDOW`: the run and a grandchild
   share one console, no window anywhere; `DETACHED_PROCESS`: the run has no console and the grandchild
   opens a visible window. `omp-run.py --help` states the rule; `state.json` records both halves —
   `spawn` (the flags that were requested) and `detach` (what the run observed about its own console
   or session) — and the test suite asserts the two against each other.
2. **A Windows launcher must not be driven from inside a WSL distro, or the reverse.** WSL2 interop is
   asymmetric: Windows environment variables do not reach the distro, and a detached Windows `.exe`
   started from a distro has been observed to record its session and then never exit, so the run never
   finalizes. Run the adapter *inside* the distro with the distro's own python3, and point
   `GDD_RUN_ROOT` at one root both halves can see. `omp-run.py` warns on `start` when a WSL distro is
   about to launch a `/mnt/<drive>/…` or `.exe`/`.cmd` agent.

## Launcher contract

```
<launcher> start  --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
<launcher> list
<launcher> status SLUG
<launcher> result SLUG
<launcher> answer SLUG
<launcher> tail   SLUG [N]
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
counter derived from a truncated stream is marked partial (both adapters set
`tool_calls_partial`, `turns_partial`, `cost_partial`).

Stopping a run is the launcher's business, and it has to work where signals do not: `omp-run.py`
writes a `stop` control file the run polls, waits for the run's own finalizer, and only then escalates
to a process-group TERM/KILL (POSIX) or `taskkill /T /F` (Windows). A run stopped this way ends as
`killed` with exit `143`; a run that died without finalizing is finalized as `failed` with exit `-1`
by the next `status`/`result`/`list`/`answer`, which sets `stale_recovered: true` — and only while no
`finalized` marker exists, so recovery stays idempotent.

## Configuration the adapter adds

Resolution order for all of these: the operator's environment (the launcher reads no config file —
`gdd.py` resolves the config file and exports `GDD_RUN_ROOT` to it).

| Key | Resolves | Default |
|---|---|---|
| `OMP_BIN` | agent CLI | `omp`, resolved through `PATH`; a Windows `.cmd`/`.bat` shim is run through `%COMSPEC%` |
| `GDD_RUN_ROOT`, `OMP_RUN_ROOT` | run root | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` — on Windows that resolves under `%USERPROFILE%`, deliberately not `%LOCALAPPDATA%`, so both platforms and every script see one tree |
| `OMP_RUN_BACKEND` | default for `start --backend` | `setsid` (`omp-run.sh`: `setsid|tmux`) |
| `OMP_LEDGER` | finished-run ledger | `<run_root>/ledger.tsv` |
| `OMP_RUN_EVENTS_MAX_BYTES` | bound for the retained event log, read by `adapters/events-writer.py` | `8388608` |
| `OMP_RUN_START_GRACE_SECONDS` | how long a run that has recorded no pid is still *starting*, not dead | `60` |

## Testing the adapter

A stage run may itself be hosted in a tmux session (the `tmux` backend), so a test never runs
`tmux kill-server` and never `kill-session`s a session it did not create: that tears down the run
executing the test, and its stdout dies with it. Use a stub `tmux` on `PATH` or an isolated socket
(`tmux -L <unique-name>`, `TMUX_TMPDIR=<temp>`), as the selftest does.

The bundled adapter's suite is stdlib `unittest` (`scripts/tests/test_omp_run_python.py`) so it runs on
every platform, with a stub agent CLI that emits OMP-style NDJSON — no network, no model, no real
agent. It covers start → settled run, the exit-code mapping, stale recovery, `kill` through the stop
file, the event-bound accounting with a non-zero `events_dropped_bytes`, the argument passthrough, and
the detachment evidence above. The real `omp -p` smoke is an operator step, not a CI step: CI has no
agent credentials.

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
