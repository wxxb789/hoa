# Evidence — a second headless route: DSH as a GDD launcher

Contract: [`docs/goals/archive/2026-11-15-dsh-headless-launcher.md`](../goals/archive/2026-11-15-dsh-headless-launcher.md)
Date: 2026-11-15 · Host: Linux (this worktree's session sandbox, `workspace-write`)
Deliverables: `skills/gdd/scripts/adapters/dsh-run.py`,
`skills/gdd/scripts/tests/test_dsh_run_python.py`, `skills/dsh-headless-gdd/SKILL.md`, the DSH route in
`skills/gdd/references/transport.md`, the goal row in `docs/goals/README.md`, the regenerated catalog rows
`index.md` / `index.zh-CN.md`, this record; the closeout round added `VERSION` 0.1.62, its `CHANGELOG.md`
entry and the mirrored `metadata.version` fields of every skill.

Every command below ran from the worktree root. Exit codes are process exit codes. The adapter never
reads, logs or stores a key, and no credential value appears in this record. The scratch profile the
smoke used is a copy of the operator's own profile patch (it carries the local provider's
`Authorization` header); it was copied unread and never printed. The facts the adapter encodes come
from the measured handoff note given to the implementer (`dsh-headless-facts.md`, outside this
repository; `@deepseek-ai/dsh` 0.2.2-rc.1).

Four correction rounds ran on this increment, plus a closeout round for the repository's own gates:
round 1 (adapter and tests), round 2 (documentation), round 3 (the adapter review findings A1–A8 and
their tests), the closeout round (`VERSION` 0.1.62, its `CHANGELOG.md` entry and the regenerated
mirrors), and round 4 (the start-handshake race round 3 introduced, plus this record's re-derived
numbers). §7 lists each round's files and what it changed; the scope claim in §1 is re-derived from
`git status --porcelain` on the final tree.

## 1. Contract clause audit

| Contract clause | Result | Where |
|---|---|---|
| 1. stdlib-only adapter, `start/list/status/result/answer/tail/kill`, fixed argument shapes | met | `dsh-run.py` imports the standard library only; `build_parser()` declares all seven commands plus the internal `_run`; `start` takes `--name --prompt [--cwd] [--session-id] [--model] [--thinking] [--max-time] [--resume] [--replace]` |
| 2. `<run root>/<YYYY-MM-DD>/<SLUG>/` with prompt.md, run.json, events log, stderr.log, exit.code, answer.md, state.json; `state.json` current with the contract fields and the five states | met | `_start_run_claimed()` creates the directory and the first `state.json`; `runner_main()` republishes counters every `STATE_REFRESH_SECONDS`; the real run's directory lists all thirteen artifacts (§5); `state` ∈ `running\|done\|killed\|failed\|unknown` |
| 3. `start` exits 0 only once the run started; a second `start` for a live slug is refused | met | `wait_for_start()` + `agent_recorded()` and the terminal-startup refusal in `_start_run_claimed()`; `test_28`/`test_29` (an agent that writes `error` and exits at once is a started run: exit 0, finalized `failed` with the error recorded); `test_16` (refusal when the agent cannot spawn, exit 127 recorded); `test_start_fails_when_only_the_runner_recorded_a_pid` (a live runner alone is not a started run); `test_12` (exit 1, `still running`, recorded pid unchanged) |
| 4. completion = exit 0 **and** last `final` `reason.kind == completed`; otherwise `failed`, `-1` when it died without finalizing, `killed`/143 after a kill; recovery idempotent behind the `finalized` marker | met | verdict ladder in `_finalize_locked()`; `effective_state()` recovery; `test_05` (exit 0 + `aborted` → `failed`), `test_04`, `test_07`, `test_22` (round 1: the **last** of several `final` events decides), and `test_completion_mapping_is_exhaustive` (the real finalizer, eight cases) |
| 5. `kill` without signals: control file the monitor observes, the run's own finalizer, then escalation | met | `request_stop()`/`wait_for_agent()`/`stop_run()`; `test_08` pins `stopped_by: control-file` from the runner's own finalizer; `test_09` pins the forced escalation when nothing observes the file; the real kill run in §5 shows `stopped_by: control-file` against real `dsh` |
| 6. bounded event log reporting `events_bytes`, `events_bytes_total`, `events_truncated`, `events_dropped_bytes`, counters marked `*_partial` | met | `EventLog` reuses `adapters/events-writer.py` with the bound resolved from `DSH_RUN_EVENTS_MAX_BYTES`; `summarize()`/`events_view()` expose the four fields; `turns_partial`, `tool_calls_partial`, `usage_partial`; `test_10` drives a non-zero `events_dropped_bytes` |
| 7. stub-`dsh` unittest suite covering settled run + exit mapping, stale recovery, control-file kill, event accounting, argv passthrough, second-start refusal | met — green in every round-4 run (twelve runs, six under four-way CPU load), §2 | `test_dsh_run_python.py`, **57 tests**, `OK` (§2): `test_01`/`test_04`, `test_07`, `test_08`, `test_10`, `test_11`, `test_12`, plus round 1's `test_21` (recovery triggered by `result`/`list`/`answer`), `test_22` (last `final` decides), `test_23`, the reserved-identity property tests, and round 4's `test_28`/`test_29` (a fast-failing agent is a started run) |
| 8. transport.md gains the DSH row, the configuration table and the two DSH-specific rules | met | `transport.md` route table row (which also names `dsh-headless-gdd` as this route's operating method); `## DSH headless adapter` + `### DSH configuration`; the cwd rule and `--approval-policy never` rule are the numbered pair in that section; the config table names `DSH_RUN_PROFILE` and states the run-root precedence and the reserved names |
| 9. goal README row + one real end-to-end dispatch with exit code and artifact paths | met | `docs/goals/README.md` lists this goal as `archived 2026-11-15` with a link to the archived contract; §5 records the author's real `start` → `status` → `answer` (exit 0, `ADAPTER_SMOKE_OK`), and the appendix records the operator's canonical dispatch (`exit.code` 0, `OPERATOR_DISPATCH_OK`) |
| 10. `skills/dsh-headless-gdd/SKILL.md` exists, declares `kind: mechanism`, and is referenced by the DSH route documentation | met | the skill's frontmatter carries `kind: "mechanism"`; `transport.md`'s DSH route row and the paragraph below the invocation call it this route's operating method; `check_contract_graph.py` passes on the final tree (60 skills, `ok` — a mechanism that no trigger case `must_pick`s), §2 |
| Out of scope: no change to gdd.py/delivery-state.py/templates/merge gate, no PTC/preset selection, no PR, no credential handling | met | the final-tree change list in §7 is this increment's own files plus the closeout round's `VERSION`/`CHANGELOG.md`/`metadata.version`-mirror bookkeeping; `--model`/`--thinking` are refused because headless composes no presets; the adapter passes the environment through and never reads a key |

## 2. Gates

Run on the final tree, sequentially, with real exit codes. The first row is the increment's own suite; the
rest are the repository gates.

| Command | Output | Exit |
|---|---|---|
| `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_dsh_run_python.py'` | `Ran 57 tests in 51.230s` → `OK` (tail below; all twelve round-4 runs below) | 0 |
| `python3 -B -m unittest discover -s scripts -p 'test_*.py'` (repo harness suite) | `Ran 189 tests in 9.537s` → `OK` | 0 |
| `python3 scripts/check_frontmatter.py` | `check_frontmatter: 60 skills OK` | 0 |
| `python3 scripts/check_contract_graph.py` | `contract graph: 60 skills, 11 artifacts, ok` | 0 |
| `python3 scripts/generate_index.py --check` | index current (no output) | 0 |
| `python3 scripts/check_changelog.py` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `cat VERSION` + `python3 scripts/version.py check` | `0.1.62`; check silent (every mirror agrees) | 0 |
| `python3 -m compileall -q skills/gdd/scripts/adapters/dsh-run.py` | no output | 0 |
| `python3 skills/gdd/scripts/adapters/dsh-run.py --help` | usage + the contract/config/completion epilog | 0 |

Every subcommand's help also ran clean — `start`, `list`, `status`, `result`, `answer`, `tail`,
`kill`: `--help` → exit 0 each, e.g.
`usage: dsh-run.py start [-h] --name NAME --prompt PROMPT [--cwd CWD]` and
`usage: dsh-run.py tail [-h] name [lines]`.

```text
----------------------------------------------------------------------
Ran 57 tests in 51.230s

OK
```

The suite drives a stub `dsh` on `PATH` that emits canned headless NDJSON (`session`, `status`,
`tool_call`, `tool_result`, `text`, `final`, `error`): no network, no model, no real `dsh` run. Modes
cover settle, a non-zero exit, a wrong `final.reason`, a runner-level `error`, a bare signal, a long
run for kill/deadline, and a 660 KB flood for the event bound. `setUpClass` prepends a temp `bin/` to
`PATH` and points `DSH_RUN_ROOT` at a temp tree, so no installed `dsh` and no real run root is touched.
Suite sha256: `f2c37b5eede0b49789382cb2fe926f37bcc60d62e5bb335c2122b70383b1c04b`.

**Stability, re-derived on the final tree.** The suite was run twelve times on this revision (the sha256
above): six times alone and six times with four busy-loop processes saturating this host's four CPUs.
All twelve exited 0 with `Ran 57 tests` and `OK`. Every run's summary line:

```text
plain-1  exit 0  Ran 57 tests in 51.230s  OK
plain-2  exit 0  Ran 57 tests in 50.987s  OK
plain-3  exit 0  Ran 57 tests in 50.695s  OK
plain-4  exit 0  Ran 57 tests in 50.927s  OK
plain-5  exit 0  Ran 57 tests in 50.817s  OK
plain-6  exit 0  Ran 57 tests in 50.489s  OK
load-1   exit 0  Ran 57 tests in 63.687s  OK
load-2   exit 0  Ran 57 tests in 92.431s  OK
load-3   exit 0  Ran 57 tests in 66.723s  OK
load-4   exit 0  Ran 57 tests in 62.514s  OK
load-5   exit 0  Ran 57 tests in 62.820s  OK
load-6   exit 0  Ran 57 tests in 66.194s  OK
```

The round-2 note recorded one unidentified failure in fifteen runs. Round 4 identified it as the `start`
handshake refusing a run whose agent emitted `error` and exited before the confirmation read
(`test_05`'s `MISSING_CREDENTIAL` case), fixed it, and pinned it with `test_28`/`test_29`; the suite is
green in every run above, not intermittent.

One pull-request CI step that is **not** in this table cannot go green on this host — the frozen OMP
launcher suite; §6 records the command and the failure.

## 3. What the suite pins, verified by mutation

Each mutant was applied to a **copy** of `skills/gdd/scripts` under `/tmp` (the worktree adapter was never
written), the full suite was run from that copy, and the copy was removed. The worktree adapter's sha256
on the final tree is `67beb532118d5a0d66eda477bc63a13584da6ac7a543b1980f22a1aaf8a69339`. A mutant that
survived would mean the suite does not pin the clause.

| Removed behaviour | Suite result (57 tests) |
|---|---|
| completion no longer checks `final_reason` (`exit 0` alone is `done`) | `FAILED (failures=5)` |
| the runner no longer records `stopped_by` | `FAILED (failures=1, errors=1)` |
| the resolved `DSH_RUN_EVENTS_MAX_BYTES` is not handed to the bounded writer | `FAILED (failures=1)` |
| stale recovery finalizes nothing | `FAILED (failures=7)` |
| unmutated tree | `Ran 57 tests ... OK` (§2) |

## 4. Stub-suite coverage map

| Clause | Tests |
|---|---|
| settled run, artifacts, answer, views, ledger-free state | `test_01`, `test_02`, `test_03`, `test_17` |
| exit-code and completion mapping | `test_04`, `test_05`, `test_06`, `test_22`, `test_completion_mapping_is_exhaustive`, `test_a_final_with_a_null_reason_is_not_completion`, `test_killed_exit_codes_are_the_documented_set`, `test_the_killed_mapping_documents_both_routes` |
| `start` dispatch confirmation: the recorded agent is the proof, alive or gone | `test_28`, `test_29`, `test_16`, `test_start_fails_when_only_the_runner_recorded_a_pid` |
| stale recovery, idempotence, marker repair, claim exclusivity | `test_07`, `test_21`, `test_stale_recovery_is_the_only_path_to_exit_minus_one`, `test_a_terminal_state_without_a_marker_is_repaired_from_its_exit_code`, `test_the_tracker_stops_publishing_before_the_verdict_is_committed`, `test_a_held_finalize_claim_stops_a_reader_from_finalizing`, `test_write_json_temp_names_are_unique_per_call` |
| kill through the control file + forced escalation, identity-gated signals | `test_08`, `test_09`, `test_12b`, `test_19`, `test_a_recycled_pid_is_not_alive_for_this_run`, `test_signal_group_refuses_a_pid_it_cannot_prove`, `test_kill_tree_leaves_an_unverified_pid_alone` |
| event-bound accounting | `test_10`, `test_events_bound_is_configuration_with_a_honest_default`, `test_the_adapter_reuses_the_shared_bounded_writer` |
| argv/stdin passthrough, `--session-id`/`--resume`, `gdd.py` launch shape, Windows dispatch spelling | `test_11`, `test_summarize_reads_the_dsh_session_and_usage_shape`, `test_option_like_values_survive_argparse`, `test_gdd_launch_shape_is_accepted`, `test_cmd_arguments_that_cmd_would_split_are_refused`, `test_a_generated_replay_script_quotes_what_cmd_would_parse` |
| second-`start` refusal, `--replace`, refusals, parser edges, cross-date occupancy | `test_12`, `test_12b`, `test_14`, `test_25`, `test_26`, `test_27`, `test_parser_edge_cases`, `test_sanitize_matches_the_reference_slug_rule` |
| `--max-time` deadline, PID-less/unknown runs, detachment | `test_15`, `test_13`, `test_18`, `test_max_time_parsing` |
| run root, run-dir bucketing, replay of a finished invocation | `test_20`, `test_24`, `test_run_root_follows_the_documented_chain` |
| reserved harness identity | `test_23`, `test_the_profile_key_is_the_adapters_own_not_the_harness_identity`, `test_the_child_environment_drops_the_reserved_harness_identity`, `test_the_reserved_keys_are_documented_where_the_adapter_documents_itself` |

## 5. Real dispatch through the adapter

Scratch directory `/tmp/dsh-adapter-smoke/` with `work/` (the run's cwd), `home/` (a scratch
`DSH_HOME`) and `runs/` (`GDD_RUN_ROOT`). Setup and environment for every command:

```bash
mkdir -p /tmp/dsh-adapter-smoke/{work,home,runs}
cp -a <HOME>/.dsh/profiles /tmp/dsh-adapter-smoke/home/profiles   # scratch DSH_HOME; never the live one
# then point the scratch copy's headless/cordis.patch.yml at a provider route reachable from this
# sandbox (see the deviation note below)
cd <worktree>
export DSH_HOME=/tmp/dsh-adapter-smoke/home
export DSH_BIN=$(command -v dsh)          # resolved on this host to <HOME>/.npm-global/bin/dsh, 0.2.2-rc.1
export GDD_RUN_ROOT=/tmp/dsh-adapter-smoke/runs
unset DSH_PROFILE DSH_PROFILE_DIR DSH_SESSION_ID   # the harness's own identity; reserved names, never the adapter's
printf 'Reply with exactly: ADAPTER_SMOKE_OK\n' > /tmp/dsh-adapter-smoke/prompt.md
```

Then, in this order:

```bash
python3 skills/gdd/scripts/adapters/dsh-run.py start --name adapter-smoke \
    --prompt /tmp/dsh-adapter-smoke/prompt.md --cwd /tmp/dsh-adapter-smoke/work --max-time 240
python3 skills/gdd/scripts/adapters/dsh-run.py status adapter-smoke
python3 skills/gdd/scripts/adapters/dsh-run.py answer adapter-smoke
```

This dispatch ran before round 1 renamed the adapter's profile key: the environment above unsets the
three harness-reserved names, so the same block selects profile `headless` under the final adapter; it
was not re-run in rounds 2–4.

`start` exited **0**:

```text
started: adapter-smoke
  backend   : dsh
  pid       : 3312126
  run dir   : /tmp/dsh-adapter-smoke/runs/2026-11-15/adapter-smoke
  session id: (pending)
  events    : /tmp/dsh-adapter-smoke/runs/2026-11-15/adapter-smoke/events.ndjson
  summary   : /tmp/dsh-adapter-smoke/runs/2026-11-15/adapter-smoke/run.json (replay argv) + state.json
```

`status` exited **0**; the run settled in 13.1 s. Run directory
`/tmp/dsh-adapter-smoke/runs/2026-11-15/adapter-smoke/` (artifacts: `answer.md`, `events.ndjson`,
`events.stats.json`, `exit.code`, `finalized`, `lock`, `prompt.md`, `run.json`, `runner.log`,
`run.sh`, `session.id`, `state.json`, `stderr.log`). Key `state.json` fields, verbatim:

```json
{
  "name": "adapter-smoke",
  "state": "done",
  "exit": 0,
  "cwd": "/tmp/dsh-adapter-smoke/work",
  "started": "2026-11-14T17:57:04.603440+00:00",
  "ended": "2026-11-14T17:57:17.704434+00:00",
  "duration_s": 13.1,
  "session_id": "session-155db525-e442-4336-9fff-44126123ea83",
  "final_reason": "completed",
  "turns": 1,
  "tool_calls": 0,
  "usage": {"input_tokens": 3573, "output_tokens": 11, "total_tokens": 8632, "cache_read_tokens": 5048},
  "answer_chars": 16,
  "answer_source": "final",
  "events_bytes": 613,
  "events_bytes_total": 613,
  "events_truncated": false,
  "events_dropped_bytes": 0,
  "backend": "dsh",
  "profile": "headless",
  "permission_mode": "workspace-write",
  "approval_policy": "never",
  "pid": 3312126,
  "agent_pid": 3312127
}
```

`detach` (what the runner observed about itself):
`{"mode": "new-session", "session_leader": true, "process_group_leader": true, "controlling_terminal": false}`.
`exit.code` = `0`, `finalized` = `0`. The retained event stream is exactly the real DSH stream:

```text
{"type":"session","sessionId":"session-155db525-e442-4336-9fff-44126123ea83","cwd":"/tmp/dsh-adapter-smoke/work"}
{"type":"status","phase":"turn_start","turn":1}
{"type":"status","phase":"step_start","turn":1,"step":1}
{"type":"text","text":"ADAPTER_SMOKE_OK"}
{"type":"status","phase":"step_end","turn":1,"step":1,"usage":{"inputTokens":3573,"outputTokens":11,"totalTokens":8632,"cacheReadTokens":5048}}
{"type":"status","phase":"turn_end","turn":1,"reason":{"kind":"completed"}}
{"type":"final","sessionId":"session-155db525-e442-4336-9fff-44126123ea83","reason":{"kind":"completed"},"text":"ADAPTER_SMOKE_OK"}
```

`answer` exited **0**; the first (and only) line of `answer.md` (16 bytes, no trailing newline):

```text
ADAPTER_SMOKE_OK
```

A second real run exercised the stop path. `start --name adapter-smoke-kill …` exited 0, then
`kill adapter-smoke-kill` exited 0 and printed
`killed: adapter-smoke-kill (pid 3312487/3312488) state=killed exit=143`; its `state.json` records
`"state": "killed"`, `"exit": 143`, `"stopped_by": "control-file"`, `"final_reason": null`, note
`stopped on request: the runner observed the stop control file and ended the agent tree`, and
`exit.code`/`finalized` = `143`.

### The `gdd.py` dispatch path

The intended outcome is `GDD_LAUNCHER=…/dsh-run.py gdd.py stage …`, so the dispatcher's own
`launch()` was exercised against this adapter with a stub `dsh` (no model): `gdd.launch(launcher,
prompt, repo, "goal-x", "implement", None, None, None)` from the loaded `skills/gdd/scripts/gdd.py`,
with `GDD_RUN_ROOT` pointed at a temp tree. It returned

```json
{
  "name": "repo-goal-x-implement",
  "run_dir": "/tmp/gdd-dsh-launch.n909hxh4/runs/2026-11-15/repo-goal-x-implement",
  "run_root": "/tmp/gdd-dsh-launch.n909hxh4/runs"
}
```

and the run settled `state=done exit=0 final_reason=completed session_id=session-gdd-launch`, `cwd` =
the repo it was given (the worktree), `answer.md = GDD_LAUNCH_OK`. The stub means this checks the
dispatcher↔adapter protocol (argument shape, `started:`/`run dir` parsing, `state.json` polling), not
a model run.

### Environment deviation, stated plainly

This authoring session runs inside a `workspace-write` file sandbox. `dsh` writes
`$DSH_HOME/profiles/headless/cordis.yml` on every boot, and the default `$DSH_HOME` (`<HOME>/.dsh`) is
outside that sandbox, so a direct `dsh --profile headless …` from here fails with
`EACCES: permission denied, open '<HOME>/.dsh/profiles/headless/cordis.yml'`. The smoke
therefore used a scratch `DSH_HOME` (a copy of `<HOME>/.dsh/profiles`, 2 MB of symlinks into the installed
CLI) with the model route of its `cordis.patch.yml` pointed at this host's local provider
(`<PROVIDER>` → `<PROVIDER_ENDPOINT>`, model `<MODEL>`, `reasoningEffort: low`), because the
default route resolves its key through the launch environment
(`<PROVIDER_API_KEY>`, the profile's `apiKeyEnv`) and this sandbox does not expose it. The CLI,
the profile composition, the model call, the NDJSON stream and the exit codes are real; only the
scratch home and the provider route differ from a canonical dispatch.

`dsh`'s own stderr in the run is diagnostics, as the facts note says, and carried one sandbox
artifact — the `spill-local` plugin could not create its scratch directory outside the workspace:
`spill-local (@deepseek-ai/dsh-spill-local): Error: EACCES: permission denied, mkdtemp
'<HOME>/.hermes/cache/scratch/dsh-spill-XXXXXX'`. The run completed regardless, and the
adapter reads nothing from stderr.

## 6. Limits

- The unit suite runs a stub, not a model; it proves the supervisor's accounting and state machine,
  not that any stage's answer is correct. The intermittent red run the round-2 note recorded is
  identified and fixed in round 4: the `start` handshake refused a run whose agent emitted `error` and
  exited before the confirmation read, and `test_28`/`test_29` pin the fixed behaviour. The suite was
  green in all twelve round-4 runs, six of them under four-way CPU load (§2).
- The author's real dispatch used the scratch profile described above; rounds 2–4 did not re-run it. No
  run was made here against the operator's live `<HOME>/.dsh`, and no credential was read or stored.
- The operator's canonical dispatch (§ appendix) is the run on the default profile route; its numbers
  come from the run directory itself.
- The Windows branch (hidden console, `taskkill /T /F`, `%COMSPEC%` shim handling) is implemented by
  analogy with the OMP adapter and is **not** executed here; the DSH facts were measured on Linux.
  `spawn`/`detach` record what the process observed, so a Windows operator can check the claim.
- Long stages, `--resume` and `--add-dir` are covered by the stub suite only; no real run exercised
  them.
- `--max-time` is the adapter's own deadline (DSH has no task-deadline flag); no real long-deadline run
  was exercised.
- The adapter writes no ledger row and no `ledger.tsv`; `state.json` plus the `finalized` marker are
  the authority, as `references/transport.md` records.
- `usage` is the last `status` event's token accounting as DSH reported it (`total_tokens` includes
  cache reads); the adapter neither sums nor re-derives it, and marks it `usage_partial` when the
  event log was truncated.
- **Environment note — the one pull-request CI step that cannot go green here.** CI runs the frozen OMP
  launcher suite, `python3 skills/gdd/scripts/tests/test_omp_run_python.py` (both of its files are
  untouched by this increment). On this host it reports `Ran 45 tests in 85.129s` →
  `FAILED (failures=1, skipped=3)`; the one failure is `test_18_tmux_backend_owns_its_session`, whose
  `start --backend tmux` cannot create a session: `omp-run: start: tmux new-session failed for
  omp-tmux-18`, and a direct probe gives the reason — `create window failed: fork failed: Permission
  denied`. This sandbox cannot fork for tmux; CI's `ubuntu-latest` can, so the step passes there. Nothing
  was edited to make it pass.

## 7. Correction rounds and the final-tree scope

Round 1 (`fix-1-code-and-tests.md`) changed only `skills/gdd/scripts/adapters/dsh-run.py` and
`skills/gdd/scripts/tests/test_dsh_run_python.py`: it renamed the adapter's profile key to
`DSH_RUN_PROFILE` and removed `DSH_PROFILE`, `DSH_PROFILE_DIR` and `DSH_SESSION_ID` from every child
environment (finding F1 of the documentation review), and it applied nine test findings (Windows path
and `SIGKILL` handling, the `test_07` race, the `wait_for_state` TOCTOU, recovery through every reader,
multi-`final` streams, cwd assertions, three claims tests did not establish, date/path assumptions,
parser edges) — the suite grew from 34 to 42 tests.

Round 2 (`fix-2-docs.md`) changed the five documentation files of this increment: `transport.md`
(operating-method reference to the skill, `DSH_RUN_PROFILE` and the reserved names, run-root precedence
and the `gdd.py` export, the `--resume`/`--session-id` mapping, the `--model`/`--thinking` refusal),
`skills/dsh-headless-gdd/SKILL.md` (raw CLI separated from the adapter's supervision, the adapter's
settings with literal defaults, the sandbox boundary, the named stop path), this record (scope, gates,
scrubbed literals, the smoke's setup, the operator appendix), and the goal contract restructured to this
repository's six-clause shape with the skill as clause 10, moved to `docs/goals/archive/`, with the
`docs/goals/README.md` row updated to `archived 2026-11-15`.

Round 3 (`fix-3-adapter.md`) changed the adapter and its tests in answer to seven accepted review
findings (A1–A6, A8): `start` requires an explicit agent-start confirmation instead of
accepting the detached runner's own pid (A1); a root-level OS lock plus an occupancy check across every
date bucket stops one slug starting twice across midnight (A2); tracker publication stops before the
terminal state is committed and every per-call temp name is unique (A3); the Windows `cmd` route prefers
the real executable behind a `.cmd` shim and refuses an argument cmd would re-parse (A4); every spawned
pid is recorded beside a spawn-time identity token and no signal is sent without a match (A5); the
finalize claim is a stable OS lock a competitor cannot delete (A6); a non-`never` `DSH_APPROVAL_POLICY`
is refused before a run directory exists (A8). The reviewer's contrary termination mapping (A7) was
rejected against the sibling adapter and only the comment was made exact. The suite grew from 42 to 55
tests.

The closeout round (`closeout.md`) made the branch pass the repository's own pull-request gates:
`scripts/version.py bump` set `VERSION` to 0.1.62, one `CHANGELOG.md` entry was added for it, and the
tool regenerated every `skills/*/SKILL.md` `metadata.version` mirror and both indexes. It ran every CI
step locally (finding the frozen OMP tmux step red on this host, §6) and found this record's counts
stale; the adapter, its tests and the docs were left frozen.

Round 4 (`fix-4-race-and-numbers.md`) fixed the race round 3 introduced and re-derived this record.
`start` now confirms the dispatch on the runner's recorded agent pid — or its identity token — whether
the agent is still alive or already gone: an agent that writes an `error` event and exits at once yields
`start` exit 0 and a run that finalizes `failed` with that error recorded, while a runner that never
spawned an agent still fails `start` and an occupied slug is still refused. `test_28` pins that
deterministically (the runner is driven to completion before confirmation, so no sleep or timeout is
involved) and `test_29` pins the same through the real detached CLI; the suite grew from 55 to 57 tests.

The contract file was moved with a plain filesystem move (`mv`): it was untracked, and this session's
sandbox cannot write the git index (`.git/worktrees/hoa-wt/index.lock` resolves outside the workspace),
so `git mv` was not available. The worktree is left dirty for the operator to commit; no commit, push or
branch switch was made.

Final-tree scope, `git status --porcelain` re-derived on the final tree. The increment's own files are the
five untracked entries and `docs/goals/README.md` / `index.md` / `index.zh-CN.md` /
`skills/gdd/references/transport.md`; the other sixty-one modified entries are the closeout round's
mechanical bookkeeping (`VERSION`, `CHANGELOG.md` and the `metadata.version` mirror in every existing
`SKILL.md`):

```text
 M CHANGELOG.md
 M VERSION
 M docs/goals/README.md
 M index.md
 M index.zh-CN.md
 M skills/agent-harness-settings-parity/SKILL.md
 M skills/agent-operating-contract-evolution/SKILL.md
 M skills/ai-coding-agent-delegation/SKILL.md
 M skills/arch-improvement-plan/SKILL.md
 M skills/contract-bound-deliverables/SKILL.md
 M skills/cross-agent-repair-routing/SKILL.md
 M skills/define-goal/SKILL.md
 M skills/delegated-work-acceptance/SKILL.md
 M skills/design-an-interface/SKILL.md
 M skills/design-md/SKILL.md
 M skills/discord-rich-message/SKILL.md
 M skills/dotnet-repo-workflow/SKILL.md
 M skills/evidence-backed-analytical-writing/SKILL.md
 M skills/evidence-boundary-discipline/SKILL.md
 M skills/find-nearby/SKILL.md
 M skills/gdd/SKILL.md
 M skills/gdd/references/transport.md
 M skills/generated-runtime-repairs/SKILL.md
 M skills/ghc-search/SKILL.md
 M skills/git-auto-sync-pipelines/SKILL.md
 M skills/github-code-review/SKILL.md
 M skills/github-repo-management/SKILL.md
 M skills/grounded-citations/SKILL.md
 M skills/harness-engineering/SKILL.md
 M skills/hermes-context-file-loading/SKILL.md
 M skills/hermes-models/SKILL.md
 M skills/hermes-updates/SKILL.md
 M skills/hoa-introspect-distill/SKILL.md
 M skills/hoa-introspect/SKILL.md
 M skills/hoa-skill-review/SKILL.md
 M skills/hoa-skill-work/SKILL.md
 M skills/html-artifact/SKILL.md
 M skills/jupyter-live-kernel/SKILL.md
 M skills/kanban-workflows/SKILL.md
 M skills/m365-copilot-cdp/SKILL.md
 M skills/measurement-campaign-evidence/SKILL.md
 M skills/microsoft-office/SKILL.md
 M skills/notes-to-prd/SKILL.md
 M skills/ocr-and-documents/SKILL.md
 M skills/official-document-verification/SKILL.md
 M skills/omp-headless-orchestration/SKILL.md
 M skills/ops-claim-verification/SKILL.md
 M skills/package-release-verification/SKILL.md
 M skills/plan-to-issues/SKILL.md
 M skills/project-phase-closeout/SKILL.md
 M skills/report-claim-audit/SKILL.md
 M skills/research-stream-consolidation/SKILL.md
 M skills/review-revision-candidates/SKILL.md
 M skills/rss-feeds/SKILL.md
 M skills/skill-library-curation/SKILL.md
 M skills/skill-porting-and-publishing/SKILL.md
 M skills/spec-convergence/SKILL.md
 M skills/structural-validity-gates/SKILL.md
 M skills/subagent-driven-development/SKILL.md
 M skills/systematic-debugging/SKILL.md
 M skills/teams-cdp/SKILL.md
 M skills/tmux-agent-control/SKILL.md
 M skills/whisper/SKILL.md
 M skills/writing-plans/SKILL.md
 M skills/writing/SKILL.md
?? docs/evidence/2026-11-15-dsh-headless-launcher.md
?? docs/goals/archive/2026-11-15-dsh-headless-launcher.md
?? skills/dsh-headless-gdd/
?? skills/gdd/scripts/adapters/dsh-run.py
?? skills/gdd/scripts/tests/test_dsh_run_python.py
```

## Appendix — the operator's canonical dispatch

The author's dispatch had to use a scratch `DSH_HOME` and a substitute provider route. The operator
repeated it outside the nested sandbox on the default profile route, with the credential in the launch
environment, against the same adapter. `<SMOKE_DIR>` is that scratch smoke directory (its `prompt.md`,
`work/` and `runs/`; `<RUN_ROOT>` below is `<SMOKE_DIR>/runs`); `<PROVIDER>` / `<MODEL>` are the profile's
own route, which this repository does not carry.

```bash
export GDD_RUN_ROOT=<SMOKE_DIR>/runs
python3 skills/gdd/scripts/adapters/dsh-run.py start --name operator-smoke \
    --prompt <SMOKE_DIR>/prompt.md --cwd <SMOKE_DIR>/work --max-time 300     # exit 0
python3 skills/gdd/scripts/adapters/dsh-run.py status operator-smoke         # exit 0
python3 skills/gdd/scripts/adapters/dsh-run.py answer operator-smoke         # prints OPERATOR_DISPATCH_OK
```

Real numbers from that run directory. `prompt.md` = `Reply with exactly: OPERATOR_DISPATCH_OK`;
`exit.code` = `0`; `stderr.log` empty; `answer.md` first line `OPERATOR_DISPATCH_OK` (20 bytes,
`answer_source: final`). Key `state.json` fields verbatim, host paths replaced by placeholders:

```json
{
  "name": "operator-smoke",
  "state": "done",
  "exit": 0,
  "cwd": "<SMOKE_DIR>/work",
  "started": "2026-11-14T18:22:16.553062+00:00",
  "ended": "2026-11-14T18:22:20.372249+00:00",
  "duration_s": 3.8,
  "model": null,
  "thinking": null,
  "max_time": 300.0,
  "backend": "dsh",
  "profile": "headless",
  "permission_mode": "workspace-write",
  "approval_policy": "never",
  "run_dir": "<RUN_ROOT>/2026-11-15/operator-smoke",
  "session_id": "session-476c8610-26b3-407e-9fde-5a978d9bc0aa",
  "resumed_from": null,
  "events_bytes": 941,
  "events_bytes_total": 941,
  "events_truncated": false,
  "events_dropped_bytes": 0,
  "turns": 1,
  "tool_calls": 0,
  "usage": {"input_tokens": 3575, "output_tokens": 55, "total_tokens": 8942, "cache_read_tokens": 5312},
  "final_reason": "completed",
  "error": "",
  "answer_chars": 20,
  "answer_source": "final",
  "turns_partial": false,
  "tool_calls_partial": false,
  "usage_partial": false,
  "pid": 3335781,
  "agent_pid": 3335782,
  "detach": {"mode": "new-session", "session_leader": true, "process_group_leader": true, "controlling_terminal": false},
  "agent_argv": ["<HOME>/.npm-global/bin/dsh", "--profile", "headless", "--json", "--permission-mode", "workspace-write", "--approval-policy", "never", "-"]
}
```

`events.ndjson` retained 7 events / 941 bytes, the last being
`{"type":"final","sessionId":"session-476c8610-26b3-407e-9fde-5a978d9bc0aa","reason":{"kind":"completed"},"text":"OPERATOR_DISPATCH_OK"}`.
Host-path fields (`launcher`, `agent`, `interpreter`, `spawn`) are omitted from this excerpt as
host-specific; `model`/`thinking` are `null` because no override was passed — the profile owns the route.
The operator's own acceptance record for this run reports no degraded-load lines, matching the empty
`stderr.log`.
