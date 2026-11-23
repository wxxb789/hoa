# Transport: the launcher contract

## Choose the route explicitly

`gdd.py` resolves the launcher from `--launcher`, then `GDD_LAUNCHER` in the
environment or [configuration](configuration.md), then `scripts/agent_run.py`.
Set it to `scripts/adapters/paseo-run.py` to opt into native Paseo. Paths here
are relative to the installed gdd skill. Both launchers use uv and stdlib
Python 3.13 or newer. A reachable daemon does not opt in; an unreachable
daemon does not fall back to a headless CLI.

The optional [GDD run observer plugin](https://github.com/wxxb789/hoa/blob/main/paseo-plugins/gdd-observer/README.md)
only reads artifacts; it runs trusted, unsandboxed daemon/client code when
installed. See its [integration notes](https://github.com/wxxb789/hoa/blob/main/paseo-plugins/gdd-observer/HOA-INTEGRATION.md).
After dispatch into the canonical run root, `gdd.py stage` adds a bounded
`lineage.json` with `goal`, `stage`, and `parentAgentId` when `PASEO_AGENT_ID`
is set. That is the initiating session, not the launched agent. A sidecar
write failure does not alter the run or its ledger entry.

## Headless platform rules

| Recorded `detach` | Dispatch session | Gateway/service restart | Logout/reboot |
|---|---|---|---|
| `systemd` | Survives | Separate user unit; not a user-manager restart | No |
| `launchd` | Survives | Separate job; not a GUI-domain restart | No |
| `setsid` | Survives | No guarantee; the double fork stays in the cgroup | No |
| `windows` | Survives | Only outside the terminating job | No |
| `tmux` (POSIX, 3.2a or newer) | Survives | Only if the server is outside the terminating cgroup/job | No |
| `herdr` (latest release) | Survives | Only if the server survives | No |

- **Auto:** Linux/WSL2 probes the user manager for at most one second and
  uses a transient unit if it reports `running` or `degraded`. macOS bootstraps
  a transient LaunchAgent in the current GUI domain; legacy submit is used
  only if bootstrap is unavailable. A failed launchctl path records
  `detach_fallback` and uses double-fork plus `setsid`, also the default on
  other POSIX hosts. Systemd and launchd preserve the dispatcher's umask.
- **Windows:** the runner uses `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`,
  trying `CREATE_BREAKAWAY_FROM_JOB` first and retrying on access denied.
  `spawn.creationflags` records the actual flags. All subprocesses, including
  shims, use `CREATE_NO_WINDOW` and hidden startup info; Python children use
  `python.exe` where available. POSIX uses no terminal emulator.
- **Opt-in only:** `GDD_RUN_DETACH=tmux|herdr` must be set in the environment.
  tmux creates a detached session; Herdr creates an unfocused tab. Missing
  executables or failed requests refuse startup. Herdr sends shell input:
  the absolute interpreter path must contain only ASCII letters, digits,
  underscores, dots, slashes, colons, and hyphens (Windows backslashes are
  converted). A private entry carries argv without shell parsing and deletes
  itself. Private environment files are removed after read; Windows creates
  them with a protected current-user DACL. The `supervisor` handle lets the
  runner or a later reader clean up the job, session or tab. Use `kill` to
  stop the agent as well.
- **WSL2:** prefer native Linux binaries and a Linux-filesystem run root.
  Both launchers warn for interop `.exe` targets and run roots on a Windows
  mount (process exit, locks and renames can fail). Map the observer
  separately.

Launchd is tested with stubs. The real systemd tests require a reachable user
manager; the WSL2 double-fork test verifies session survival, not a macOS
live run. Real agent CLI smoke is opt-in via `GDD_SMOKE_AGENTS`.

## Launcher contract

```text
<launcher> start --name SLUG --prompt FILE --schema FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
<launcher> list
<launcher> status SLUG
<launcher> result SLUG
<launcher> answer SLUG
<launcher> tail SLUG [N]
<launcher> kill SLUG
```

- Detach execution and its artifact monitor from the dispatching session.
- Use `<run_root>/<YYYY-MM-DD>/<SLUG>/` for `prompt.md`, `run.json`, live
  events/output, `stderr.log`, `exit.code`, final `answer.md` and `state.json`.
  Finish old-layout runs with their old launcher before upgrading; the
  dispatcher no longer finds or reserves those runs.
- Keep `name`, `state`, `exit`, `cwd`, `started`, `ended` and `duration_s`
  current. States: `running|done|failed|killed|unknown`. Missing state is
  unknown. `GDD_RUN_ROOT` defaults to
  `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` (under the user profile,
  not LocalAppData, on Windows).
- Accept `--schema`. If checked, report `result: valid|invalid|missing` and
  write `result.json` only when valid. If bounding logs, report retained
  `events_bytes`, total `events_bytes_total`, `events_truncated` and
  `events_dropped_bytes`; mark counters re-derived from truncated streams
  as partial (`tool_calls_partial`, `turns_partial`, `cost_partial`).

## Headless runner (`agent_run.py`)

`--agent`, then `GDD_AGENT` (env, then config), then `omp`. An
`<AGENT>_BIN` override takes precedence over PATH. A `.py` runs through the
current interpreter; a Windows batch shim uses `%COMSPEC%` and is refused for
metacharacters (`" & | < > ^ ( ) % !` or newlines).
The Omo and Copilot routes require a native executable on Windows: set
`OMO_BIN` or `COPILOT_BIN` if PATH would only find a batch shim.

The runner discovers `gdd-route-*/scripts/route.py` beside the lexical path of
the installed `gdd` skill. If the harness supplies the resolved path but a route
is copied into the host's skills root, set `GDD_SKILLS_ROOT` to that host skills
root. The environment overrides the gdd config file. Only that one root is
scanned; `start` names it and lists its routes before refusing a missing route.

Routes are optional, not part of gdd's install closure. New and upgrading
users must add the selected route. Use the same host (`-a <agent>`) and scope
as gdd. For the default route, use `npx skills add wxxb789/hoa -s gdd-route-omp`
for a project install or `npx skills add wxxb789/hoa -g -s gdd-route-omp` for a
global install. The generated index has the complete command for each route.
`GDD_AGENT=claude` selects the `gdd-route-cc` package.

Route documentation (configuration, input, and exit-0 success marker):

- [gdd-route-omp](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-omp/SKILL.md)
- [gdd-route-dsh](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-dsh/SKILL.md)
- [gdd-route-codex](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-codex/SKILL.md)
- [gdd-route-cc](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-cc/SKILL.md)
- [gdd-route-pi](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-pi/SKILL.md)
- [gdd-route-opencode](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-opencode/SKILL.md)
- [gdd-route-omo](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-omo/SKILL.md)
- [gdd-route-copilot](https://github.com/wxxb789/hoa/blob/main/skills/engineering/gdd-route-copilot/SKILL.md)

- **End states:** stop is killed/143; signal exit codes are kept
  (`130/137/143/-2/-9/-15`). Max time ends the run as failed/124 with a
  `max_time exceeded` state note. Kill writes `stop` and the runner
  terminates the agent group (TERM, wait five seconds,
  KILL; Windows `taskkill /T /F`). If the runner is gone, kill requires a
  verified process start time. A reused PID counts as gone; a live,
  unverifiable PID is never signalled. Zombie-only groups count as stopped.
- **Recovery:** once startup grace expires, a reader finalizes abandoned
  running state as failed/-1 with `stale_recovered`, or killed if stop was
  requested. Dispatcher and ledger liveness reads report stale without writing.
  New runs keep a private snapshot of the validated route for detached startup
  and event refolding even after uninstall. Keep `GDD_RUN_ROOT` in a trusted
  location: these artifacts include executable route code. For old runs
  without a snapshot, if the installed route is unavailable, the reader notes
  that events could not be refolded and preserves answer and progress. Restore
  the route to allow a later read to finish recovery.
- **Events:** rotate to `events.1.ndjson` at half the limit. The current log's
  truncation marker appears after bytes have been dropped. An observer
  reading only the active segment treats counts as partial once any
  rotated segment exists. `tail` shows type and up to 160 characters of text.
- **Results:** when a route does not use a native schema flag, the stage
  prompts for JSON. Prefer structured output, then the whole answer as
  JSON, then its last JSON fence. Validation does not change run state;
  native rejection can fail the underlying turn. Keep a preceding report
  above the JSON in `answer.md` on native schema routes.

| Setting | Default / scope |
|---|---|
| `GDD_SKILLS_ROOT` | lexical sibling skills root; environment then gdd config |
| `GDD_RUN_DETACH` | `auto`; env then gdd config; also applies to the Paseo monitor |
| `GDD_RUN_EVENTS_MAX_BYTES` | 8388608 |
| `GDD_RUN_START_GRACE_SECONDS` | 60 |
| `GDD_RUN_STOP_WAIT_SECONDS` | 20 |
| `GDD_RUN_DRAIN_TIMEOUT_SECONDS` | 30 (at most 5 on stop); expiry marks `stream_incomplete` |
| `GDD_RUN_MAX_MB` | 512 MiB; `off` or a nonpositive value disables automatic cleanup |
| `GDD_RUN_RETENTION_DAYS` | 7 days |
| `GDD_RUN_GC_MIN_INTERVAL_SECONDS` | 60 seconds between scans; `0` disables cooldown |
Retired runner environment keys warn.

After a successful headless or native Paseo start, a detached worker checks the run root.
The cleanup settings resolve from the environment, then `gdd/config.yaml`, then the defaults above.
Only when the total regular-file size exceeds the budget does it remove finalized runs, oldest first,
until the root fits or no eligible runs remain. Both the `finalized` marker and the recorded `ended`
time (or `started` when `ended` is unavailable) must be strictly older than retention. Unfinalized,
live, and ledger-referenced runs are retained, and symlinks are not followed. The worker serializes
scans with `.gc.lock` and skips busy `.start.lock` or Paseo `refresh` claims.

## Native Paseo adapter

`PASEO_BIN` defaults to `paseo` on PATH. An executable path or JSON argv
array overrides it; only the executable is resolved, not the remaining
literal arguments. `--model`/`GDD_MODEL` select `--provider`, and
`--thinking`/`GDD_THINKING` select thinking. Flags win; unset uses daemon
defaults. `--max-time` is refused: a wait timeout is not an execution deadline.

Windows batch shims handle ordinary single-line prompts; newlines and shell
metacharacters are refused before dispatch. For multiline stages configure
native argv. Example for the bundled Paseo 0.15.4 CLI; verify other layouts:

```powershell
$install = Join-Path $env:LOCALAPPDATA 'Programs\Paseo'
$resources = Join-Path $install 'resources'
$env:ELECTRON_RUN_AS_NODE = '1'
$env:PASEO_NODE_ENV = 'production'
$env:PASEO_BIN = ConvertTo-Json -Compress -InputObject @(
  (Join-Path $install 'Paseo.exe'),
  '--disable-warning=DEP0040',
  (Join-Path $resources 'app.asar.unpacked\dist\daemon\node-entrypoint-runner.js'),
  'node-script',
  (Join-Path $resources 'app.asar\node_modules\@getpaseo\cli\dist\index.js')
)
$env:GDD_LAUNCHER = Join-Path (Get-Location) 'skills\gdd\scripts\adapters\paseo-run.py'
```

- **Dispatch:** the daemon owns execution; the detached monitor owns local
  observations. `run --no-wait --json` records `agentId` as `agent_id` and
  `session_id`. Dispatch drops `PASEO_AGENT_ID` and `PASEO_WORKSPACE_ID` because
  they override `--cwd`. A mismatched cwd preserves identity but stays unknown
  until inspect verifies the requested directory. Do not retry blindly.
- **Lifecycle:** initializing/running or idle with pending permissions map
  to running; settled idle to done; error to failed; closed to killed.
  Missing identity, unknown status, or unreachable daemon is unknown, not
  success. Running/unknown reserves the worktree until terminal evidence,
  even without a monitor. An idle agent may merely have been interrupted.
- **Claim:** a persistent `refresh` kernel lock serializes observations and
  releases on process exit. Do not mix with old unlinking monitors. A CLI
  call times out in 60 seconds; one claim attempt waits 30. Contention does
  not update state; the monitor waits one second and retries until terminal
  state or marker, not merely until the CLI becomes reachable.
- **Delete:** `kill` uses `paseo delete ID --json`, not `stop`. The receipt
  must say `deletedCount: 1` with exactly that ID. A pre-delete answer is
  provisional until confirmed. Active runs finalize killed/143 with a
  partial-answer flag if captured; already-finalized runs retain outcome,
  timing and marker. Raw receipts are in `cli.ndjson`.
- **Answer:** inspect has no answer field. Use text from
  `paseo logs ID --filter assistant_message --tail 1`, not JSON logs.
  Unavailable text yields a nonzero answer command with the logs argv;
  retry later. Native events are lifecycle transitions, not token/tool
  telemetry. The live Windows 0.15.4 smoke verified one configured path;
  it did not verify native daemons on WSL2, Linux or macOS.

## Rules that come from delivery, not transport

One fresh run per stage; an interrupted turn is not resumed through the launcher. Reconcile the
run's partial work first (phase 7), and a further attempt is a new `gdd.py stage` dispatch that
spends a round; a delegated ce-work run is never resumed. Poll at turn boundaries. Never attach a
second writer to a live turn. Use a separate worktree for concurrent increments; serialize heavy
gates on constrained hosts and build artifacts before checking them.

## What to read from a finished run

Read `result SLUG` and `answer.md`, then run the repository's gates yourself.
`done` means a successful CLI turn or observed native idle without pending
permissions, not proof of stage success. Native exit codes classify observed
state; an idle native agent remains resumable until explicitly deleted.
