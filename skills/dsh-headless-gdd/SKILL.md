---
name: dsh-headless-gdd
description: >-
  Run one GDD stage on a DeepSeek Harness (`dsh`) headless worker instead of, or beside, the OMP route:
  one goal, one worktree, one session, NDJSON events, and completion decided from the process exit code
  plus the final turn event rather than from the worker's own report. Use when a stage is dispatched to
  dsh headless, when a dsh run reports success without doing the work, when a run must be resumed,
  stopped or recovered, or when the DSH launcher route needs configuring. Not for deciding what to build
  (that is the goal contract) and not for the delivery protocol itself (that is `gdd`).
metadata:
  version: "0.1.62"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "dispatch and supervise a GDD stage on dsh headless: session/worktree rules, completion judgement, recovery, harness traps"
  summary_zh: "把 GDD 阶段派发给 dsh headless 并监督：会话/worktree 规则、完成判定、恢复、harness 陷阱"
  kind: "mechanism"
---

# DSH headless as a GDD worker

A second headless route for goal-driven delivery: `dsh --profile headless` answers one task per
invocation, streams NDJSON events, and resumes a persisted session. Model tool writes are constrained by
the permission policy, not by the working directory: with the default `workspace-write` policy, on a host
whose harness enforces a sandbox, writes inside the policy's boundary succeed and writes outside it are
denied; `--cwd` only selects the run's working directory. Changing the profile or `DSH_PERMISSION_MODE`
changes that boundary, so re-confirm it before dispatching (see "Harness facts that bite"). The protocol
stays in `gdd`; this skill is the operating method for that route, invoked from the DSH route row of
[`../gdd/references/transport.md`](../gdd/references/transport.md).

## When to Use

- Dispatching a stage to DSH: `GDD_LAUNCHER=<repo>/skills/gdd/scripts/adapters/dsh-run.py python3
  skills/gdd/scripts/gdd.py stage …`, or the same adapter by hand.
- Diagnosing a dsh stage that exited 0 but did not do the work, refused to resume, or stalled.
- Not for choosing the increment (goal contract / `define-goal`), and not for OMP/Paseo route details
  (`gdd` → `references/transport.md`).

## The adapter supervises; the raw CLI is for one-offs

Supervision is the adapter's, and only the adapter's: `dsh-run.py start|status|result|answer|tail|kill`
(it creates the run directory, detaches a runner, keeps `state.json` current, finalizes a dead run with
`stale_recovered: true`, and stops a run through its control file). A raw
`dsh --profile headless …` invocation is for one-off/manual use only: it does **not** detach, does not
write `state.json`, never sets `stale_recovered`, and watches no stop file. Every statement below about
state, recovery and stopping belongs to the adapter. One goal, one worktree, one session still holds; the
raw form is:

```bash
git worktree add -b goal/<slug> <worktree> <base-ref>
cd <worktree>
dsh --profile headless --json --permission-mode workspace-write --approval-policy never \
    - < <task.md>          # stdout is the NDJSON stream; the raw CLI writes no run artifacts
```

The adapter's equivalent, which is what a GDD stage uses:

```bash
dsh-run.py start --name <slug> --prompt <task.md> --cwd <worktree> [--session-id <id>|--resume <id>]
dsh-run.py status <slug>     # until state != running
dsh-run.py answer <slug>     # the final assistant text
```

## One goal, one worktree, one session

- **Launcher flags precede app flags.** `--profile`, `--patch`, `--dump-config` belong to the launcher;
  putting `--patch` after `--json` or `--session-id` fails with `unknown option '--patch'`.
- A session is anchored to the directory that recorded it. Resuming elsewhere is refused
  (`was recorded in "<A>", not "<B>"`), and a second concurrent writer is refused
  (`already owned by an active write handle`). One worktree per session, one writer at a time.
- **New increment → new session.** An unrelated increment resumed into an old session works but re-sends
  the accumulated context (measured ≈8× a fresh session's first-step input) for no benefit.
- Next round of the *same* increment (revise, verify) → resume the same session in the same cwd. Through
  the adapter that is `start --resume <session-id>` (alias `--session-id <session-id>`), which re-sends
  `--permission-mode` / `--approval-policy` itself; by raw CLI it is `--session-id <session-id>` with
  `--permission-mode` / `--approval-policy` repeated and `--add-dir` for extra writable paths. The prompt
  must say the run was interrupted, that the tree is mid-flight, and that this continues rather than
  restarts.
- Parallel goals: different worktrees, different sessions. **The isolation unit is the worktree/session,
  not the repository**: several goals of one repository run in parallel in their own worktrees, while the
  *same* worktree (and the same session) never has two writers — a second concurrent writer to one
  worktree is refused (`already owned by an active write handle`). Two writers in one worktree would
  interleave edits, gates and `git status` in exactly the tree a reviewer is inspecting.

A task prompt that keeps a worker inside its lane: repository context **by file path** (never re-narrated),
an observable done-when, the rules (no commits/pushes, which paths are writable, tests are
orchestrator-owned), and a report format of command + exit code + count line + changed files + unmet
criteria. A resumed round adds the interruption point.

## Completion is two conditions, then your own gates

```
success = exit_code == 0, and the last `final` event carries reason.kind == "completed"
```

The adapter's exit→state mapping, which is also what `gdd.py` and the observer plugin read:

- `done` — `exit 0` **and** the last `final` event's `reason.kind == "completed"`.
- `killed` — the adapter stopped the run (its own stop path records exit `143`), **or** the process exited
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
heartbeat event, so poll the adapter's `state.json` (`dsh-run.py status`), which the runner keeps current —
a detached run never notifies.

## Stopping and recovering

- Stop through the adapter: `dsh-run.py kill <slug>`. It writes the `stop` control file inside the run
  directory (`<run_dir>/stop`), the runner polls it, the run's own finalizer settles it, and only then does
  the adapter escalate — through a validated process handle, never a bare pid or group id (see the
  capability bullet below). A stopped run is `killed` with exit 143; a run that
  died unfinalized is finalized `failed` with exit −1 and `stale_recovered: true` by the next
  `status`/`result`/`list`/`answer` — idempotently, behind a `finalized` marker. Starting a replacement
  (`start --replace`) stops the live run first and then waits that last moment out: once the verdict is
  committed it re-checks — bounded, and holding no lock — that no recorded process is live and nothing is
  left to enumerate, before it moves the old run aside; only a stop still unresolved at that bound is
  refused. The raw CLI has none of
  this: there is no control file to write and no finalizer of yours to wait for.
- The recovery substrate is only: the worktree, the harness's session log
  (`$DSH_HOME/sessions/<cwd-slug>/session-<id>/session.v4.jsonl.zstd`, append-only zstd frames), and the
  run artifacts. No task database, no checkpoint framework, no WAL.
- **Cooperative stop is the main path; escalation exists only where a process instance can be proven.**
  Before any destructive call the adapter opens a `pidfd` handle on the recorded process, re-reads the
  process identity and signals through that same handle; group breadth comes from enumerating the group
  under a continuously verified member. Where that primitive is missing — Linux without
  `pidfd_open`/`pidfd_send_signal`, macOS, Windows — **no destructive call is made at all**: the stop
  stays a request, the run stays `running`/`stopping` with its survivors named, and `kill` exits **1**
  saying it cannot confirm the stop. That is not a bug to work around: the operator then ends the
  process tree by hand and runs `kill` (or `status`) again — once every recorded process is conclusively
  gone the run settles `killed`/`143`. Residual limits, stated as limits and not as guarantees: the
  macOS/Windows strong-identity and tree-termination capability is unconfirmed here; `os.replace` is
  atomic but not durable across power loss; a descendant that deliberately leaves the recorded process
  groups may not be found; and nothing arbitrates atomically against an external starter that does not
  follow this protocol.
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

Resolution order per setting: environment variable → documented default. The adapter's CLI flags are the
contract's (`start --name --prompt --cwd --session-id --model --thinking --max-time --resume --replace`,
plus the other subcommand arguments); nothing else is a flag, so the keys below are environment-only. No
environment-specific value belongs in the adapter, the skill body, or the goal contract.

| Key | Resolves | Default |
|---|---|---|
| `DSH_BIN` | the harness CLI the adapter spawns | `dsh` resolved through `PATH` |
| `DSH_RUN_ROOT` | run/artifact root; wins over `GDD_RUN_ROOT` | unset → `GDD_RUN_ROOT` |
| `GDD_RUN_ROOT` | run/artifact root when `DSH_RUN_ROOT` is unset; the one `gdd.py` exports | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` |
| `DSH_RUN_PROFILE` | launcher `--profile` | `headless` |
| `DSH_PERMISSION_MODE` | app `--permission-mode` | `workspace-write` |
| `DSH_APPROVAL_POLICY` | app `--approval-policy` | `never` |
| `DSH_RUN_EVENTS_MAX_BYTES` | retained event-log bound, handed to the shared bounded writer | `8388608` |
| `DSH_RUN_START_GRACE_SECONDS` | how long a run with no recorded pid is still starting | `60` |
| `DSH_RUN_STOP_WAIT_SECONDS` | how long `kill` waits for the run to finalize itself | `20` |
| `DSH_RUN_DRAIN_TIMEOUT_SECONDS` | how long the runner waits for dsh's stdout to reach EOF after dsh exits | `30` |

`DSH_PROFILE`, `DSH_PROFILE_DIR` and `DSH_SESSION_ID` are DeepSeek Harness's own session identity, exported
into every model shell call. The adapter never reads them and removes all three from every child it spawns,
so a stage dispatched from inside a live `dsh` session cannot inherit its caller's profile or session; the
profile key is `DSH_RUN_PROFILE` and the adopted session id travels on `argv`.

Leave `--model` / `--thinking` — and `GDD_MODEL` / `GDD_THINKING`, which `gdd.py` turns into those flags
only when set — unset for this route. The adapter refuses both because headless composes no agent preset
and has no such flags: `start` exits 1 with `start: --model is not supported on the DSH route: …` (or the
`--thinking` form) before it creates a run directory, so a config that works for another route must be
changed for this one rather than silently overridden.

The reference adapter is `../gdd/scripts/adapters/dsh-run.py`; its `--help` is authoritative for the
exact flag set, and its unittest suite (stub CLI, no network) is the acceptance gate for the adapter.

## Cost notes (measured, one host)

- A small increment: 20–90 s, 7–10 steps, 6–20 tool calls, 3–17 k output tokens.
- A one-file scanner/audit task: 6 shell calls (native executor) vs 1 `run_code` call (PTC) for the same
  correct answer — PTC halves the round trips but roughly doubles non-cached input.
- A large increment in a single turn (adapter + tests + docs) ran 23 min / 122 tool calls; splitting the
  increment into two invocations keeps it observable.
