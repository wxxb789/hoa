---
name: gdd-route-dsh
description: >-
  Dispatch and supervise a bounded task on a DeepSeek Harness (`dsh`) headless worker, via its
  adapter or as a `gdd` stage beside the OMP route. Use when a dsh run claims success without the
  work, must be resumed, stopped or recovered, or its launcher needs configuring. Not for the
  delivery protocol (`gdd`) or OMP runs (`gdd-route-omp`).
metadata:
  revision: "2"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "dispatch and supervise a GDD stage on dsh headless: session/worktree rules, completion judgement, recovery, harness traps (requires skill `gdd`)"
  summary_zh: "把 GDD 阶段派发给 dsh headless 并监督：会话/worktree 规则、完成判定、恢复、harness 陷阱（需要 skill `gdd`）"
  kind: "mechanism"
---

# gdd-route-dsh

A second headless route for goal-driven delivery: `dsh --profile headless` answers one task per
invocation, streams NDJSON events, and resumes a persisted session. Model tool writes are constrained by
the permission policy, not by the working directory: with the default `workspace-write` policy, on a host
whose harness enforces a sandbox, writes inside the policy's boundary succeed and writes outside it are
denied; `--cwd` only selects the run's working directory. Changing the profile or `DSH_PERMISSION_MODE`
changes that boundary, so re-confirm it before dispatching (see "Harness facts that bite"). The protocol
stays in `gdd`; see the Headless CLI row and DSH route specifics in
[`../gdd/references/transport.md`](../gdd/references/transport.md).

## When to Use

- Dispatching a stage to DSH: set `GDD_AGENT=dsh` and run `uv run ../gdd/scripts/gdd.py stage …`,
  or pass `--agent dsh` to the runner directly.
- Diagnosing a dsh stage that exited 0 but did not do the work, refused to resume, or stalled.
- Not for choosing the increment (goal contract / `define-goal`), and not for OMP/Paseo route details
  (`gdd` → `references/transport.md`).

## The runner supervises; the raw CLI is for one-offs

Supervision is the shared runner's, and only the runner's: `agent_run.py
start|status|result|answer|tail|kill` with `--agent dsh` (or `GDD_AGENT=dsh`). It creates the run
directory, detaches a runner, keeps `state.json` current, finalizes a dead run with
`stale_recovered: true`, and stops a run through its control file. A raw `dsh --profile headless …`
invocation is for one-off/manual use only: it does **not** detach, does not write `state.json`, never
sets `stale_recovered`, and watches no stop file. Every statement below about state, recovery and
stopping belongs to the runner. One goal, one worktree, one session still holds.

The runner's equivalent, which is what a GDD stage uses:

```text
uv run ../gdd/scripts/agent_run.py start --agent dsh --name example --prompt task.md --cwd .
uv run ../gdd/scripts/agent_run.py status example
uv run ../gdd/scripts/agent_run.py answer example
```

Only if a script command fails (for example `uv` is not found), read
[the runner troubleshooting reference](../gdd/references/troubleshooting.md).

## One goal, one worktree, one session

- **Launcher flags precede app flags.** `--profile`, `--patch`, `--dump-config` belong to the launcher;
  putting `--patch` after `--json` or `--session-id` fails with `unknown option '--patch'`.
- A session is anchored to the directory that recorded it. Resuming elsewhere is refused
  (`was recorded in "<A>", not "<B>"`), and dsh refuses a second concurrent writer of the *same session*
  (`already owned by an active write handle`). One worktree per session, one writer at a time.
- **New increment → new session.** An unrelated increment resumed into an old session works but re-sends
  the accumulated context (measured ≈8× a fresh session's first-step input) for no benefit.
- Next round of the *same* increment (revise, verify) → resume the same session in the same cwd. Through
  the runner that is `start --resume <session-id>` (`--session-id` is a compatibility alias), which re-sends
  `--permission-mode` / `--approval-policy` itself; by raw CLI it is `--session-id <session-id>` with
  `--permission-mode` / `--approval-policy` repeated and `--add-dir` for extra writable paths. The prompt
  must say the run was interrupted, that the tree is mid-flight, and that this continues rather than
  restarts.
- Parallel goals: different worktrees, different sessions. **The isolation unit is the worktree/session,
  not the repository**: several goals of one repository run in parallel in their own worktrees, while the
  *same* worktree (and the same session) never has two writers. The mechanical refusals are dsh's
  per-*session* write handle (`already owned by an active write handle`) and the runner's refusal of a
  second `start` on a live slug; for a worktree, one-session-per-worktree is the discipline those mechanisms assume —
  two sessions pointed at one worktree are not mechanically refused by dsh, and their writers would
  interleave edits, gates and `git status` in exactly the tree a reviewer is inspecting.

A task prompt that keeps a worker inside its lane: repository context **by file path** (never re-narrated),
an observable done-when, the rules (no commits/pushes, which paths are writable, tests are
orchestrator-owned), and a report format of command + exit code + count line + changed files + unmet
criteria. A resumed round adds the interruption point.

## Completion is two conditions, then your own gates

```
success = exit_code == 0, and the last `final` event carries reason.kind == "completed"
```

The runner's exit→state mapping, which is also what `gdd.py` and the observer plugin read:

- `done` — `exit 0` **and** the last `final` event's `reason.kind == "completed"`.
- `killed` — the runner stopped the run (its own stop path records exit `143`), **or** the process exited
  on a signal convention: `130`/`137`/`143` and their raw POSIX forms `-2`/`-9`/`-15`. A signal-convention
  exit keeps its raw code.
- `failed` — every other settled outcome: an `exit 0` whose last `final` is missing or not `completed`,
  any other non-signal, non-zero exit, and the stale-recovery case below.
- `failed` with exit `-1` and `stale_recovered: true` — the process disappeared without finalizing.

- A runner-level failure emits an `error` event **instead of** `final`; a killed run has no `final`.
- `tool_result.status == "completed"` means the tool returned — a shell command inside it can exit non-zero.
- Then verify independently: `git status --porcelain` (only the contract's files changed), re-run the
  repository's gates on the final tree, and read `stderr.log` for `did not activate` /
  `pending (waiting for service: …)`. A composition row that fails to load degrades the run **while the
  process still exits 0**, so a green exit code alone is not a gate result.

Events worth folding into a progress summary: `session.sessionId`, `status.phase/turn/step/usage`,
`tool_call`, `tool_result`, `final`, `error`. Tool-call count is not a completion percentage; there is no
heartbeat event, so poll `state.json` (`agent_run.py status`), which the runner keeps current —
a detached run never notifies.

## Stopping and recovering

- Stop through the runner: `uv run ../gdd/scripts/agent_run.py kill <slug>`. It writes `<run_dir>/stop`; the runner ends dsh
  (POSIX group TERM, 5 s, KILL; Windows `taskkill /T /F`) and finalizes `killed`/143. If the runner is
  gone, `kill` signals a recorded pid only when its live start time equals the one recorded at spawn;
  when that cannot be proven it signals nothing and exits **1** naming each pid and why — end the
  process tree by hand, then run `kill` (or `status`) again. A run that died unfinalized is finalized
  `failed` with exit −1 and `stale_recovered: true` by the next `status`/`result`/`list`/`answer`,
  idempotently, while no `finalized` marker exists. `start --replace` stops the live run first and moves
  it aside. The raw CLI has none of this: there is no control file to write and no finalizer to wait for.
- The recovery substrate is only: the worktree, the harness's session log
  (`$DSH_HOME/sessions/<cwd-slug>/session-<id>/session.v4.jsonl.zstd`, append-only zstd frames), and the
  run artifacts. No task database, no checkpoint framework, no WAL.
- A corrupt session log is refused loudly with the byte offset; restore from a copy, or truncate to the
  last complete frame.
- Budget: two corrective rounds per stage, then stop and escalate (different model, narrower contract,
  abandoning).

## Harness facts that bite

- **Agent presets do not exist in headless.** `standard`/`ptc`/`minimal` are profile patch fragments that
  need the agent-preset registry, which the headless profile does not compose: applying one logs
  `pending (waiting for service: agentPresets)` and the tool set is unchanged. Programmatic tool calling
  needs an explicit overlay (`tool-executor-native` disabled, `tool-executor-ptc` enabled); while it is
  active a direct call to any other tool resolves to `UNKNOWN_TOOL`.
- **Credentials:** launch environment → `<cwd>/.env` → `$DSH_HOME/.env`; the managed store is disabled in
  this profile, so credentials saved through a UI are ignored. A missing key fails loudly with
  `MISSING_CREDENTIAL`. Never place a key in a prompt, a repository file, or a run artifact.
- **Compaction:** `retainRatio` must stay below `thresholdRatio` or the plugin is rejected at load (and
  the run then exits 0 with no compaction service); too small a `maxTokens` produces
  `summarization truncated at the token cap (incomplete checkpoint)` in `compaction/end`. Read both.
- **The sandbox is real** where the harness provides one: with the default `workspace-write` policy,
  writes inside the policy's boundary (the run's workspace, selected by `--cwd`) succeed and writes
  outside it are denied even where Unix modes allow them; reads outside are permitted. `--cwd` selects
  the workspace, the permission mode sets the boundary — a profile or `DSH_PERMISSION_MODE` that widens
  it widens what the worker can write, so re-confirm the boundary rather than assume the working
  directory alone confines it. Do not reach for a full-access mode to "unblock" a task.
- **A plugin can exist twice** (a globally installed copy and the profile's copy) and the loader
  validates the version it resolves. After upgrading the harness runtime, upgrade both, or the profile
  silently drops the bundle with an incompatibility warning.
- Keep experiments call-level: `--patch <overlay>.yml` instead of editing the harness's global
  configuration, so one experiment cannot change every later run.

## Configuration

For `GDD_AGENT` and `GDD_RUN_ROOT`, the shared runner checks the environment, then the
[GDD config file](../gdd/references/configuration.md), then the default. `start --agent` takes
precedence over `GDD_AGENT`. The remaining keys resolve from the environment, then the default.

| Key | Resolves | Default |
|---|---|---|
| `GDD_AGENT` | the agent CLI (`--agent` wins) | `omp`; set `dsh` for this route |
| `DSH_BIN` | the harness CLI the runner spawns | `dsh` resolved through `PATH` |
| `GDD_RUN_ROOT` | run/artifact root, the one `gdd.py` exports | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` |
| `GDD_RUN_DETACH` | shared runner detach mode; see [platform rules](../gdd/references/transport.md#headless-platform-rules) | `auto` |
| `DSH_RUN_PROFILE` | launcher `--profile` | `headless` |
| `DSH_PERMISSION_MODE` | app `--permission-mode` | `workspace-write` |
| `DSH_APPROVAL_POLICY` | app `--approval-policy`; any other value is refused | `never` |
| `GDD_RUN_EVENTS_MAX_BYTES` | retained event-log bound | `8388608` |
| `GDD_RUN_START_GRACE_SECONDS` | how long a run with no recorded pid is still starting | `60` |
| `GDD_RUN_STOP_WAIT_SECONDS` | how long `kill` waits for the run to finalize itself | `20` |
| `GDD_RUN_DRAIN_TIMEOUT_SECONDS` | how long the runner waits for dsh's stdout to reach EOF after dsh exits | `30` |

`DSH_PROFILE`, `DSH_PROFILE_DIR` and `DSH_SESSION_ID` are DeepSeek Harness's own session identity, exported
into every model shell call. The runner never reads them and removes all three from every child it spawns,
so a stage dispatched from inside a live `dsh` session cannot inherit its caller's profile or session; the
profile key is `DSH_RUN_PROFILE` and the adopted session id travels on `argv`.

Leave `--model` / `--thinking` — and `GDD_MODEL` / `GDD_THINKING`, which `gdd.py` turns into those flags
only when set — unset for this route. The runner refuses both because headless composes no agent preset
and has no such flags: `start` exits 1 with `start: --model is not supported on the DSH route` (or the
`--thinking` form) before it creates a run directory, so a config that works for another route must be
changed for this one rather than silently overridden. `--max-time` is the runner's own deadline (exit
124, `failed`).

The runner is `../gdd/scripts/agent_run.py`; its `--help` is authoritative for the exact flag set, and
`../gdd/scripts/tests/test_agent_run.py` (stub CLI, no network; the dsh rows) is its acceptance gate.

## Cost notes (measured, one host)

- A small increment: 20–90 s, 7–10 steps, 6–20 tool calls, 3–17 k output tokens.
- A one-file scanner/audit task: 6 shell calls (native executor) vs 1 `run_code` call (PTC) for the same
  correct answer — PTC halves the round trips but roughly doubles non-cached input.
- A large increment in a single turn (adapter + tests + docs) ran 23 min / 122 tool calls; splitting the
  increment into two invocations keeps it observable.
