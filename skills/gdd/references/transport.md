# Transport — the launcher contract

The protocol assumes each stage is one **agent run** that outlives the session that dispatched it.
How the run is started is runtime-specific; this file defines the contract every adapter satisfies,
plus the rules that come from the delivery protocol rather than from any one CLI.

## Choose the route explicitly

`gdd.py` calls the launcher selected by `--launcher`, `GDD_LAUNCHER`, or the configured
`GDD_LAUNCHER`, in that order. With none set it uses the bundled `scripts/adapters/omp-run.py`.
Paths below are relative to the installed `gdd` skill directory.

| Route | Launcher | Runtime requirement |
|---|---|---|
| Headless CLI (default) | `scripts/adapters/omp-run.py` | An OMP-style `-p` CLI hosted in a detached process; stdlib Python 3, no bash, `setsid`, or `tmux` dependency |
| Native Paseo (opt-in) | Set `GDD_LAUNCHER` to `scripts/adapters/paseo-run.py` | An installed Paseo CLI and a reachable Paseo daemon; each stage is a native Paseo agent |

Select the route as configuration, never from a daemon reachability probe. An unreachable daemon
does not substitute the headless launcher, and a reachable daemon does not opt a default install into
native agents. Both Python adapters use the existing launcher contract and add no Python dependencies.
`scripts/adapters/omp-run.sh` remains the POSIX reference adapter with the attachable `tmux` backend;
`scripts/tests/test-omp-run-setsid.sh` and `test-omp-run-stale.sh` pin its behaviour.

The optional [GDD run observer plugin](../../../paseo-plugins/gdd-run-observer/README.md) reads run
artifacts; it is **not a launcher**, selects neither route, and is not installed with the skill.
Its README covers clean-checkout installation and typecheck/tests, trust, disable, and removal;
[HOA-INTEGRATION.md](../../../paseo-plugins/gdd-run-observer/HOA-INTEGRATION.md) explains the two
routes and the shared `GDD_RUN_ROOT`. Installing it executes trusted, unsandboxed daemon/client code.

## Headless platform matrix — inherited evidence

This matrix records existing `omp-run.py` / `omp-run.sh` evidence only. None of its test or smoke
results demonstrates that the native Paseo route works on the same platform.

| Platform | Adapter | How the run is detached | Evidence |
|---|---|---|---|
| Windows 11 x64, CPython 3.12.10 | `omp-run.py` (executed through `sys.executable`) | `CREATE_NO_WINDOW \| CREATE_NEW_PROCESS_GROUP`: one hidden console the whole descendant tree inherits | **executed** — `python3 -B skills/gdd/scripts/tests/test_omp_run_python.py` → 34 tests, `OK (skipped=1)`; one real `omp -p` run through the adapter → `state=done exit=0`, `answer.md = SMOKE OK`, 7.3 s, one turn; `test_19` dispatches `gdd.py stage --wait` through the bundled launcher |
| Linux (Ubuntu 24.04 inside WSL2, distro python3 3.12.3) | `omp-run.py`, and `omp-run.sh` where bash is wanted | `start_new_session=True` in the child (setsid): own session and process group, no controlling terminal | **executed** — the same suite inside the distro (`OK`, two skips: no tmux, Windows-only cases), `tests/test-omp-run-stale.sh` 7/7, `tests/run-gdd-selftest.sh` 90/91 (the one failure needs `jq`, absent there, and fails identically on a pristine `origin/main`), and every pushed head on GitHub Actions ubuntu-latest |
| macOS | `omp-run.py` | same POSIX path as Linux | **documented, unverified** — no macOS host here, so the POSIX path is executed only on Linux. `omp-run.sh` cannot be the default there: macOS ships no `setsid`, so it would need `--backend tmux` |
| WSL2 (Windows host, run *inside* the distro) | `omp-run.py` with the distro's own python3 | same POSIX path as Linux | **executed** for one distro (the row above); the rule below is what a Windows-side launcher gets wrong |

What the console evidence is, precisely: Windows tests observe the *runner's* own console
(`detach`: attached console, no window) and compare a hidden-console spawn against `DETACHED_PROCESS`
in a controlled probe (grandchild joins the hidden console vs. allocates a visible one). They do not
trace a full launch through a `.cmd` shim into a real agent's tool commands; that chain is the reason
the rule exists, and a Windows-side operator sees it directly (no window appears at dispatch).

Two rules carry that headless matrix:

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

### Native Paseo evidence boundary

| Platform | Native validation status |
|---|---|
| Windows | Executed: `python3 -B -m unittest discover -s skills/gdd/scripts/tests` → 77 tests, `OK (skipped=3)`, exit 0. Native stub cases cover argv/state/answer/deletion. Live CLI 0.15.4 native-argv multiline smoke returned the exact requested answer; real inspect verified the stage cwd despite inherited caller/workspace identities; deletion receipt and both list formats confirmed agent removal. |
| WSL2 (Ubuntu 24.04, inside the distro) | Executed: the same 77-test command with a fresh native-filesystem `TMPDIR` → `OK (skipped=4)`, exit 0; includes the native stub cases and the inherited tmux case. No real-daemon native smoke claimed. |
| Linux / macOS | No native live-test evidence claimed; the headless POSIX evidence above is not transferable |

The Windows daemon smoke used the explicit native executable/entrypoint argv described below;
the `.cmd` multiline attempt was refused before dispatch. It proves one configured daemon/provider
path, not macOS, a Linux daemon, every provider, or successful completion of an arbitrary stage.
Plugin typecheck and synthetic tests also executed on Windows: 34 passed, one opt-in live test
skipped; plugin installation into the daemon and desktop rendering remain unverified.

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

1. keep the agent and its artifact monitor **detached** from the dispatching session — a child of
   that session dies with it; for the headless route, a `-p`-style CLI prints only at exit;
2. create `<run_root>/<YYYY-MM-DD>/<SLUG>/` and write into it `prompt.md`, the invocation record (`run.json`,
   plus platform replay scripts for headless transport), a
   live event or output log, `stderr.log`, `exit.code`, `answer.md` (final assistant text) and
   `state.json`;
3. keep `state.json` current, at minimum
   `{"name","state","exit","cwd","started","ended","duration_s"}` with `state` one of
   `running|done|killed|failed|unknown`;
4. resolve `<run_root>` from `GDD_RUN_ROOT` (default
   `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs`).

A missing `state.json` means **unknown**, never success. On the native route, a missing agent,
unreachable daemon, or unrecognized daemon state also means unknown, never successful completion.

A launcher that bounds its live event log must not let the bound hide the stream's size. It reports
`events_bytes` (retained), `events_bytes_total` (everything the agent emitted),
`events_truncated` and `events_dropped_bytes` in `status` and in the finalized `state.json`, and any
counter derived from a truncated stream is marked partial (the OMP adapters set
`tool_calls_partial`, `turns_partial`, `cost_partial`).

Stopping a headless run is the launcher's business, and it has to work where signals do not: `omp-run.py`
writes a `stop` control file the run polls, waits for the run's own finalizer, and only then escalates
to a process-group TERM/KILL (POSIX) or `taskkill /T /F` (Windows). A run stopped this way ends as
`killed` with exit `143`; a run that died without finalizing is finalized as `failed` with exit `-1`
by the next `status`/`result`/`list`/`answer`, which sets `stale_recovered: true` — and only while no
`finalized` marker exists, so recovery stays idempotent.

## Headless adapter configuration

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
| `OMP_RUN_STOP_WAIT_SECONDS` | how long `kill` waits for a run to finalize itself before forcing its tree | `20` |
| `OMP_RUN_DRAIN_TIMEOUT_SECONDS` | how long the runner waits for the agent's stdout to reach EOF after the agent exits | `30` |

Two transient claims live in the run directory: `start.lock` (held from before the run's artifacts until
the runner owns the run, so a second `start` refuses instead of moving a starting run aside) and
`finalize.lock` (held around finalization, so two readers seeing the same dead run write one final state
and one ledger row). The `finalized` marker is the authority either way; a run whose finalizer died
between publishing `state.json` and writing the marker is finalized again from its recorded exit code
and marked `finalize_repaired`.

## Native Paseo adapter

`paseo-run.py` implements the same `start`, `list`, `status`, `result`, `answer`, `tail`, and `kill`
commands through Paseo rather than starting an OMP-style CLI. Start requires the selected daemon to
be reachable. The adapter owns a detached monitor that keeps `state.json` current for `gdd.py`
polling (including `stage --wait`) and materializes run artifacts, including `answer.md`. State
records `backend: paseo` and the native identity in `session_id` / `agent_id`, so an operator can
inspect the same agent in Paseo. The optional observer plugin only reads those artifacts.

### Native configuration

| Key / flag | Resolves | Default |
|---|---|---|
| `PASEO_BIN` | Executable path or JSON argv array (executable plus fixed CLI entrypoint arguments) | `paseo`, resolved through `PATH`; native argv runs without a shell |
| `GDD_MODEL` / `--model` | Paseo `--provider` selector, not a fabricated daemon model field | Unset: keep the daemon's default provider/model |
| `GDD_THINKING` / `--thinking` | Paseo `--thinking` | Unset: keep the daemon's default thinking setting |
| `GDD_RUN_ROOT` | Run/artifact root shared with `gdd.py` and, optionally, the observer | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs`, the same default as the headless route |

CLI flags override the corresponding model/thinking environment values. `gdd.py` resolves the run
root through its existing config resolver and exports it to the launcher. `PASEO_BIN` is an adapter
environment setting; selecting native transport adds no package dependency or automatic plugin install.

### Windows prompt transport: native argv, not batch expansion

The default Windows `paseo` installation exposes a `.cmd` shim. Batch transport cannot preserve
multiline prompts: a measured CLI invocation silently lost everything after the first newline.
The adapter therefore **refuses newlines and shell metacharacters** (`" & | < > ^ ( ) % !`) on
that route before dispatch. Ordinary single-line prompts still work through the default `paseo`.
Ambiguous input fails closed; it is never shortened into a quieter substitute.

For real stage prompts, set `PASEO_BIN` to a JSON argv array naming the real executable and CLI
entrypoint. The adapter resolves only argv[0] through PATH and preserves every other element
literally; this is not a shell command string and does not expand environment references. The
following PowerShell configuration reproduces the native argv discovered in the installed
**Paseo 0.15.4** `resources/bin/paseo.cmd`, without hard-coding a user's home directory:

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

Adjust the install directory explicitly if Paseo was installed elsewhere; future package layouts
must be checked rather than guessed. The launcher never parses a shim to select another target.
`ELECTRON_RUN_AS_NODE=1` selects Electron's Node runtime and `PASEO_NODE_ENV=production` matches
the bundled wrapper. These are native-CLI environment requirements, not launcher-selection rules.
On POSIX a normal executable `paseo` works directly, including multiline prompts.

`--max-time` is explicitly unsupported: Paseo's `--wait-timeout` limits a foreground wait, not
agent execution, so silently forwarding it would claim a deadline the adapter cannot enforce.

For `run` only, the adapter removes inherited `PASEO_AGENT_ID` and `PASEO_WORKSPACE_ID` from the
subprocess environment: CLI 0.15.4's `utils/caller-agent.js` and `commands/agent/run.js` give those
identities precedence over `--cwd`. An audit of that CLI's caller/session environment readers
found these two routing inputs. Other configuration (including daemon targeting and native-runtime
variables) is preserved. Future CLI identity inputs require rechecking this boundary. The returned
run `cwd` must match the stage's explicit directory; otherwise start refuses with agent identity
preserved and state `unknown`, rather than falsely reporting which repository ran the stage.

### Completion and answer evidence

CLI 0.15.4's lifecycle states map as follows. An idle agent is successful only **after the dispatched
turn has settled**; an agent that is merely idle before dispatch is not a completed stage.

| Daemon state / observation | Launcher state |
|---|---|
| `initializing`, `running` | `running` |
| `idle`, after the dispatched turn settles | `done` |
| `idle` with pending permissions | `running`, not completed |
| `error` | `failed` |
| `closed` | `killed`, never successful completion |
| Missing agent, unreachable daemon, or unrecognized state | `unknown`, never success |

`kill` maps to **`paseo delete <id> --json`**, not `paseo stop`. CLI 0.15.4's `stop` only interrupts
a turn; it leaves a resumable idle agent and is not termination evidence. The installed `delete.js`
awaits cancellation when running, then hard-deletes the agent. Its receipt must contain
`deletedCount: 1` and exactly this run's id in `agentIds`; exit zero with an empty/mismatched receipt
records no termination and makes the adapter exit nonzero. Raw command/receipt evidence stays in
`cli.ndjson`.

Before deletion, the adapter captures the last addressable assistant text into `answer.md`, so
`answer` still works after the agent's daemon history is removed. For an active stage that text is
marked partial, and a confirmed deletion finalizes the stage as `killed` with exit `143`. For an
already-finalized stage, deletion appends only `agent_deleted`, `termination_verb`, and
`terminated_at`; the original outcome, exit, timing, finalized marker, and ledger row remain
unchanged. A merely-interrupted idle agent is never labelled `killed` by the adapter; lifecycle
`idle` does not identify why a turn ended, and never proves the stage's goal was met.

In CLI 0.15.4, `paseo inspect <id> --json` uses capitalized keys such as `Id` and `Status` and has
**no answer field**. `paseo logs <id> --json` currently emits rendered text, not JSON. Native answer
retrieval therefore deliberately omits `--json` and uses the verified text command:

```text
paseo logs <id> --filter assistant_message --tail 1
```

Use the recorded `agent_id` / `session_id` in place of `<id>`. The adapter persists the returned
last-assistant text in `answer.md` and exposes it through `answer`; it does not invent an inspect
answer field or parse rendered logs as JSON. This is report evidence, not proof that the stage met
its goal; `answer.md` remains a claim to verify.
If the CLI cannot address text yet, `answer` exits nonzero and prints the exact logs argv; no
placeholder answer is written. Calling `answer` again can retrieve subsequently published text.
Native `events.ndjson` records observed lifecycle transitions, not a fabricated OMP event stream;
native tool/turn/cost counters are not inferred from those transitions.

## Testing the headless adapter

A stage run may itself be hosted in a tmux session (the `tmux` backend), so a test never runs
`tmux kill-server` and never `kill-session`s a session it did not create: that tears down the run
executing the test, and its stdout dies with it. Use a stub `tmux` on `PATH` or an isolated socket
(`tmux -L <unique-name>`, `TMUX_TMPDIR=<temp>`), as the selftest does.

The default headless adapter's suite is stdlib `unittest` (`scripts/tests/test_omp_run_python.py`) so it runs on
every platform, with a stub agent CLI that emits OMP-style NDJSON — no network, no model, no real
agent. It covers start → settled run, the exit-code mapping, stale recovery, `kill` through the stop
file, the event-bound accounting with a non-zero `events_dropped_bytes`, the argument passthrough, and
the detachment evidence above. The real `omp -p` smoke is an operator step, not a CI step: CI has no
agent credentials.

On WSL over DrvFS, the tmux-backed test needs `TMPDIR` on a **native Linux filesystem** (for example,
a fresh directory under `/tmp`). The fixture derives `TMUX_TMPDIR` from it. On this host DrvFS temp
directories failed with `directory .../tmux-tmp/tmux-0 has unsafe permissions`, even at a short
99-byte socket path; shortening the path does not repair Linux permission semantics. Keep each
test's socket isolated and remove its owned temporary directory afterward.

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
6. **Human attach is a turn-boundary operation.** Attaching an interactive TUI or sending a native
   Paseo message to a live run means two writers on one session; settle or stop the dispatched turn
   first, and resume the same stage only if it is unfinished. Read-only observation is not a writer.
7. **Heavy steps are serialized in the prompt itself.** Do not start a measurement/benchmark run while
   a full suite is running on a host sized for one; the loser is killed (exit `-9`) and reads as a code
   failure, not a result.
8. **A fresh worktree has no build outputs.** Run the repo's build before any gate that reads compiled
   artifacts; a gate complaining about a missing assembly is a prerequisite failure, not a regression.

## What to read from a finished run

1. `result SLUG` — state, exit, duration, and whatever cost/turn counters the CLI provides.
2. `answer.md` — the report, treated as a CLAIM.
3. The repo's gates, re-run by you, with real exit codes.

`state=done` means process exit 0 for headless transport, or an observed idle native turn without
pending permissions. Native `exit` values are adapter classifications, not provider-process exit
codes; the native agent remains resumable until explicitly deleted. It does not mean the work is correct or the
stage finished — a report that ends "waiting for the gate result" is a turn that ended mid-gate.
