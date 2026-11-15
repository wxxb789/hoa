# Evidence — a second headless route: DSH as a GDD launcher

Contract: [`docs/goals/archive/2026-11-15-dsh-headless-launcher.md`](../goals/archive/2026-11-15-dsh-headless-launcher.md)
Date: 2026-11-15 · Host: Linux (this worktree's session sandbox, `workspace-write`)
Deliverables: `skills/gdd/scripts/adapters/dsh-run.py`,
`skills/gdd/scripts/tests/test_dsh_run_python.py`, `skills/dsh-headless-gdd/SKILL.md`, the DSH route in
`skills/gdd/references/transport.md`, the goal row in `docs/goals/README.md`, the regenerated catalog rows
`index.md` / `index.zh-CN.md`, this record; the closeout round added `VERSION` 0.1.62, its `CHANGELOG.md`
entry and the mirrored `metadata.version` fields of every skill.

Every command below ran from the worktree root. Exit codes are process exit codes. The **adapter** never
reads, logs or stores a key: apart from removing the three harness-reserved identity names it passes the
launch environment through to the runner and to the agent, and no credential value appears in this record.
A dispatch is therefore environment-only — the profile's own configuration (`apiKeyEnv`) supplies the
provider key from the launch environment, so no credential has to be copied anywhere. That is how the
operator's canonical dispatch ran (§ appendix), and it is what the author's smoke ran too: a copy of the
live `<HOME>/.dsh/profiles` tree under a scratch `DSH_HOME`, created with the exact command in §5, because
`dsh` writes `$DSH_HOME/profiles/headless/cordis.yml` on boot and the live `$DSH_HOME` is outside this
session's nested `workspace-write` sandbox. The copy matched the live tree outside the installed
`node_modules` — including the profile's patch layer, which is the empty list `[]` in both — so the copied
profile's own configuration supplied the provider route and the launch environment supplied the key; no
provider route was substituted. The scratch copy existed only under `/tmp/dsh-adapter-smoke`
(a scratch directory owned by the operator's user, outside this repository, the run root and every skill),
was never the live `$DSH_HOME`, and was never printed or read back into this record. Its cleanup is
`rm -rf /tmp/dsh-adapter-smoke`, not yet run: on the authoring host the directory is still present at the
time of this round, as scratch data outside the repository. The
facts the adapter encodes come from the measured handoff note given to the implementer
(`dsh-headless-facts.md`, outside this repository; `@deepseek-ai/dsh` 0.2.2-rc.1).

Six correction rounds ran on this increment, plus a closeout round for the repository's own gates:
round 1 (adapter and tests), round 2 (documentation), round 3 (the adapter review findings A1–A8 and
their tests), the closeout round (`VERSION` 0.1.62, its `CHANGELOG.md` entry and the regenerated
mirrors), round 4 (the start-handshake race round 3 introduced), round 5 (the second independent
machine-review cycle: the adapter findings A1–A7, the test findings B1–B2, the documentation findings
C1–C4, and this record's numbers re-derived once more on the round-5 tree), and round 6 (the third
machine-review cycle, a cross-family diff-only review, whose run-lifecycle class is fixed once by the
six rules R1–R6 in §7). §7 lists each round's files
and what it changed; the scope claim in §1 is re-derived from `git status --porcelain` on the final tree.

## 1. Contract clause audit

| Contract clause | Result | Where |
|---|---|---|
| 1. stdlib-only adapter, `start/list/status/result/answer/tail/kill`, fixed argument shapes | met | `dsh-run.py` imports the standard library only; `build_parser()` declares all seven commands plus the internal `_run`; `start` takes `--name --prompt [--cwd] [--session-id] [--model] [--thinking] [--max-time] [--resume] [--replace]` |
| 2. `<run root>/<YYYY-MM-DD>/<SLUG>/` with prompt.md, run.json, events log, stderr.log, exit.code, answer.md, state.json; `state.json` current with the contract fields and the five states | met | `_start_run_claimed()` creates the directory and the first `state.json`; `runner_main()` republishes counters every `STATE_REFRESH_SECONDS`; the real run's directory lists all thirteen artifacts (§5); `state` ∈ `running\|done\|killed\|failed\|unknown` |
| 3. `start` exits 0 only once the run started; a second `start` for a live slug is refused | met | `wait_for_start()` + `agent_recorded()` and the terminal-startup refusal in `_start_run_claimed()`; `test_28`/`test_29` (an agent that writes `error` and exits at once is a started run: exit 0, finalized `failed` with the error recorded); `test_16` (refusal when the agent cannot spawn, exit 127 recorded); `test_start_fails_when_only_the_runner_recorded_a_pid` (a live runner alone is not a started run); `test_12` (exit 1, `still running`, recorded pid unchanged); round 5's `test_30` (a `.`/`..` name — or a slug directory that resolves out of its date bucket — is refused before any write) and `test_31` (the recorded `run.sh` refuses a live run rather than starting a second agent on the same cwd) |
| 4. completion = exit 0 **and** last `final` `reason.kind == completed`; the exit→state mapping is the one the contract's §3 states | met | verdict ladder in `_publish_terminal_locked()`; `effective_state()` recovery; `test_05` (exit 0 + `aborted` → `failed`), `test_04`, `test_07`, `test_22` (round 1: the **last** of several `final` events decides), `test_completion_mapping_is_exhaustive` (the real finalizer, eight cases), `test_01` (the committed `terminal_record` and its fields), and round 7's `test_t1_death_at_each_publication_boundary_leaves_one_verdict` (the `exit-zero-without-final` boundary). The mapping: `killed` is this adapter's own stop path (`143`) **or** a signal-convention exit (`130`/`137`/`143` and their raw POSIX forms `-2`/`-9`/`-15`, the `KILLED_EXITS` set shared with `omp-run.py`), which keeps its raw code — it is not rewritten to `143`; an `exit 0` whose last `final` event is missing or does not carry `reason.kind == "completed"`, and any other non-signal, non-zero exit, are `failed` with the exit code recorded unchanged; an unfinalized death is `failed` with `-1` and `stale_recovered: true`. Every reader decides "finished" from the committed `terminal_record` in `state.json` — the `finalized` marker is written after the commit and is never an authority. Round 5's `test_32` shows recovery leaves a run another backend recorded untouched, and only runs whose state records `backend: dsh` are finalized |
| 5. `kill` without signals: control file the monitor observes, the run's own finalizer, then escalation | met | `request_stop()`/`wait_for_agent()`/`stop_run()`; `test_08` pins `stopped_by: control-file` from the runner's own finalizer; `test_09` pins the forced escalation when nothing observes the file; the real kill run in §5 shows `stopped_by: control-file` against real `dsh`; round 5's `test_a_vanished_leader_is_never_signalled` / `test_a_verified_member_names_the_group_of_a_gone_leader` pin the identity gate on group signals, and `test_33` / `test_a_failed_stop_records_survivors_without_finalizing` pin that a stop which cannot end every process stays `running`/`stopping` instead of publishing `killed`. Round 6 splits that outcome three ways (proven gone / survivors known / enumeration failed) and keeps the slug occupied until a later attempt proves the stop complete: `test_34`–`test_38`, §7 |
| 6. bounded event log reporting `events_bytes`, `events_bytes_total`, `events_truncated`, `events_dropped_bytes`, counters marked `*_partial` | met | `EventLog` reuses `adapters/events-writer.py` with the bound resolved from `DSH_RUN_EVENTS_MAX_BYTES`; `summarize()`/`events_view()` expose the four fields; `turns_partial`, `tool_calls_partial`, `usage_partial`; `test_10` drives a non-zero `events_dropped_bytes` |
| 7. stub-`dsh` unittest suite covering settled run + exit mapping, stale recovery, control-file kill, event accounting, argv passthrough, second-start refusal | met — green in every round-6 run (§2) | `test_dsh_run_python.py`, **89 tests**, `OK` (§2): `test_01`/`test_04`, `test_07`, `test_08`, `test_10`, `test_11`, `test_12`, plus round 1's `test_21` (recovery triggered by `result`/`list`/`answer`), `test_22` (last `final` decides), `test_23`, the reserved-identity property tests, round 4's `test_28`/`test_29` (a fast-failing agent is a started run), round 5's `test_30`–`test_33` (bucket escape, live replay, foreign-run recovery, failed stop), and round 6's `test_34`–`test_46` plus the lifecycle/generation/handshake/doc unit pins (§7) |
| 8. transport.md gains the DSH row, the configuration table and the two DSH-specific rules | met | `transport.md` route table row (which also names `dsh-headless-gdd` as this route's operating method); `## DSH headless adapter` + `### DSH configuration`; the cwd rule and `--approval-policy never` rule are the numbered pair in that section; the config table names `DSH_RUN_PROFILE` and states the run-root precedence and the reserved names |
| 9. goal README row + one real end-to-end dispatch with exit code and artifact paths | met | `docs/goals/README.md` lists this goal as `archived 2026-11-15` with a link to the archived contract; §5 records the author's real `start` → `status` → `answer` (exit 0, `ADAPTER_SMOKE_OK`), and the appendix records the operator's canonical dispatch (`exit.code` 0, `OPERATOR_DISPATCH_OK`) |
| 10. `skills/dsh-headless-gdd/SKILL.md` exists, declares `kind: mechanism`, and is referenced by the DSH route documentation | met | the skill's frontmatter carries `kind: "mechanism"`; `transport.md`'s DSH route row and the paragraph below the invocation call it this route's operating method; `check_contract_graph.py` passes on the final tree (60 skills, `ok` — a mechanism that no trigger case `must_pick`s), §2 |
| Out of scope: no change to gdd.py/delivery-state.py/templates/merge gate, no PTC/preset selection, no PR, no credential handling | met | the final-tree change list in §7 is this increment's own files plus the closeout round's `VERSION`/`CHANGELOG.md`/`metadata.version`-mirror bookkeeping; `--model`/`--thinking` are refused because headless composes no presets; the adapter passes the environment through and never reads a key |

### The exit→state mapping, stated once

The same three entries, with the same conditions, are stated in the archived goal's failure clause
(§3), in `skills/gdd/references/transport.md` and in `skills/dsh-headless-gdd/SKILL.md`; the round-7
suite checks the *associations* between each state and its own conditions, not keyword presence:

- `done` — `exit 0` **and** the last `final` event's `reason.kind == "completed"`.
- `killed` — this adapter stopped the run (its own stop path records exit `143`), **or** the process
  exited on a signal convention: `130`/`137`/`143` and their raw POSIX forms `-2`/`-9`/`-15`. A
  signal-convention exit keeps its raw code — it is not rewritten to `143`.
- `failed` — every other settled outcome: an `exit 0` whose last `final` event is missing or does not
  carry `reason.kind == "completed"` (the exit code is recorded unchanged), any other non-signal,
  non-zero exit, and the disappeared-process case below.
- `failed` with exit `-1` and `stale_recovered: true` — the process disappeared without finalizing,
  written by the next `status`/`result`/`list`/`answer`, idempotently, only while no terminal record is
  committed.

## 2. Gates
Run on the final tree, sequentially, with real exit codes (re-measured on the closeout-round-2 tree). The
first row is the increment's own suite; the rest are the repository gates. The PyYAML steps — the
`scripts/` suite, `check_frontmatter`, `check_contract_graph`, `generate_index`, `check_changelog` and
`version.py` — ran with `/usr/bin/python3` (3.12, PyYAML 6.0.1), because this host's mise `python3`
(3.15.2) has no PyYAML; the `dsh` suite, `compileall` and the help runs used the mise interpreter.

| Command | Output | Exit |
|---|---|---|
| `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_dsh_run_python.py'` | `Ran 120 tests in 98.712s` → `OK` (the fifteen-run series and this confirmation run on the final tree; the pre-fix revision of this row failed once here — §7's second closeout round) | 0 |
| `python3 -B -m unittest discover -s scripts -p 'test_*.py'` (repo harness suite) | `Ran 189 tests in 9.272s` → `OK` | 0 |
| `python3 scripts/check_frontmatter.py` | `check_frontmatter: 60 skills OK` | 0 |
| `python3 scripts/check_contract_graph.py` | `contract graph: 60 skills, 11 artifacts, ok` | 0 |
| `python3 scripts/generate_index.py --check` | index current (no output) | 0 |
| `python3 scripts/check_changelog.py --base origin/main` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `cat VERSION` + `python3 scripts/version.py check` | `0.1.62`; check silent (every mirror agrees) | 0 |
| `python3 -m compileall -q skills/gdd/scripts/adapters/dsh-run.py` | no output | 0 |
| `python3 skills/gdd/scripts/adapters/dsh-run.py --help` | `usage: dsh-run.py [-h] {start,_run,status,result,answer,tail,kill,list} ...` + the contract/config/completion epilog | 0 |

Every subcommand's help also ran clean — `start`, `list`, `status`, `result`, `answer`, `tail`,
`kill`: `--help` → exit 0 each, e.g.
`usage: dsh-run.py start [-h] --name NAME --prompt PROMPT [--cwd CWD]` and
`usage: dsh-run.py tail [-h] name [lines]`.

```text
----------------------------------------------------------------------
Ran 89 tests in 71.961s

OK
```

The suite drives a stub `dsh` on `PATH` that emits canned headless NDJSON (`session`, `status`,
`tool_call`, `tool_result`, `text`, `final`, `error`): no network, no model, no real `dsh` run. Modes
cover settle, a non-zero exit, a wrong `final.reason`, a runner-level `error`, a bare signal, a long
run for kill/deadline, a quiet run for the generation pin, and a 660 KB flood for the event bound.
`setUpClass` prepends a temp `bin/` to
`PATH` and points `DSH_RUN_ROOT` at a temp tree, so no installed `dsh` and no real run root is touched.
Suite sha256 on the round-6 tree: `ac33af98752fd913c37de42097d1d3b2696cf12e8a62f405239e35622edc6d95` (adapter sha256: `e77f5b7f4868eca6e4707e6a18d4ca2b173611ed3c7cdb9662dd4598ec64ee6f`).

**Stability, re-derived on the round-6 tree.** The suite was run twelve times on this revision (the sha256
above): six times alone and six times with four busy-loop processes saturating this host's four CPUs
(`nproc` = 4). All twelve exited 0 with `Ran 89 tests` and `OK` — no failure, no error, no skip on this
Linux host. Every run's summary line:

```text
plain-1  exit 0  Ran 89 tests in 71.911s  OK
plain-2  exit 0  Ran 89 tests in 70.383s  OK
plain-3  exit 0  Ran 89 tests in 71.281s  OK
plain-4  exit 0  Ran 89 tests in 72.111s  OK
plain-5  exit 0  Ran 89 tests in 81.812s  OK
plain-6  exit 0  Ran 89 tests in 74.857s  OK
load-1   exit 0  Ran 89 tests in 87.465s  OK
load-2   exit 0  Ran 89 tests in 86.740s  OK
load-3   exit 0  Ran 89 tests in 87.107s  OK
load-4   exit 0  Ran 89 tests in 86.315s  OK
load-5   exit 0  Ran 89 tests in 85.987s  OK
load-6   exit 0  Ran 89 tests in 86.768s  OK
```

A thirteenth run confirmed the frozen files after the series (`Ran 89 tests in 71.961s` → `OK`, the gate
table's first row above); a fourteenth run, made after the twelve summary lines above were written into
this record, ran `Ran 89 tests in 72.053s` → `OK` (exit 0). The adapter and test files were byte-identical
across all fourteen runs (sha256 `e77f5b7f…` / `ac33af98…`).

The round-2 note recorded one unidentified failure in fifteen runs. Round 4 identified it as the `start`
handshake refusing a run whose agent emitted `error` and exited before the confirmation read
(`test_05`'s `MISSING_CREDENTIAL` case), fixed it, and pinned it with `test_28`/`test_29`; the suite is
green in every run above, not intermittent.

One pull-request CI step that is **not** in this table cannot go green on this host — the frozen OMP
launcher suite; §6 records the command and the failure.

### Round-7 gates and stability, re-derived on the hardened tree

Same commands, run sequentially on the round-7 tree (the suite first). `python3` is this host's mise
CPython 3.15.2 for the suite and the adapter; the gates that import PyYAML (`version.py check`,
`check_frontmatter.py`, `check_contract_graph.py`, `generate_index.py`, `check_changelog.py`, the
`scripts/` suite) were run with `/usr/bin/python3` (3.12, PyYAML 6.0.1) because the mise interpreter has
no PyYAML — a step run with the wrong interpreter is a false alarm, not a finding.

| Command | Output | Exit |
|---|---|---|
| `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_dsh_run_python.py'` | `Ran 120 tests in 98.712s` → `OK` (re-measured on the closeout-round-2 tree; the round-7 run of this row was `Ran 117 tests` → `OK`) | 0 |
| `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_*.py'` (every gdd module) | `Ran 247 tests in 228.172s` → `OK (skipped=4)` (re-measured on the closeout-round-2 tree) | 0 |
| `python3 -B -m unittest discover -s scripts -p 'test_*.py'` (`/usr/bin/python3`) | `Ran 189 tests in 9.272s` → `OK` | 0 |
| `python3 scripts/check_frontmatter.py` (`/usr/bin/python3`) | `check_frontmatter: 60 skills OK` | 0 |
| `python3 scripts/check_contract_graph.py` (`/usr/bin/python3`) | `contract graph: 60 skills, 11 artifacts, ok` | 0 |
| `python3 scripts/generate_index.py --check` (`/usr/bin/python3`) | index current (no output) | 0 |
| `python3 scripts/check_changelog.py --base origin/main` (`/usr/bin/python3`) | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `python3 scripts/version.py check` (`/usr/bin/python3`) | check silent (every mirror agrees); the mise interpreter reports `ModuleNotFoundError: No module named 'yaml'` — wrong interpreter, not a finding | 0 |
| `python3 -m compileall -q skills/gdd/scripts/adapters/dsh-run.py` | no output | 0 |
| `dsh-run.py <cmd> --help` for all seven subcommands | `usage:` line each (`start … --name NAME --prompt PROMPT [--cwd CWD]`, `list [-h]`, `status [-h] [name]`, `result [-h] name`, `answer [-h] name`, `tail [-h] name [lines]`, `kill [-h] name`) | 0 each |

**Stability, re-derived on the round-7 tree.** Fifteen runs: ten alone, five with four busy-loop
processes saturating this host's four CPUs (`nproc` = 4). Every run's summary line, verbatim:

```text
plain-1  exit=0  Ran 118 tests in 95.272s OK  OK  [wall=96s]
plain-2  exit=0  Ran 118 tests in 95.902s OK  OK  [wall=96s]
plain-3  exit=0  Ran 118 tests in 95.749s OK  OK  [wall=96s]
plain-4  exit=0  Ran 118 tests in 95.238s OK  OK  [wall=95s]
plain-5  exit=0  Ran 118 tests in 95.368s OK  OK  [wall=96s]
plain-6  exit=0  Ran 118 tests in 94.552s OK  OK  [wall=95s]
plain-7  exit=1  Ran 118 tests in 92.205s FAILED (failures=1)  FAILED  [wall=92s]
plain-8  exit=0  Ran 118 tests in 94.749s OK  OK  [wall=95s]
plain-9  exit=0  Ran 118 tests in 96.824s OK  OK  [wall=97s]
plain-10 exit=0  Ran 118 tests in 96.611s OK  OK  [wall=97s]
load-1   exit=0  Ran 118 tests in 109.683s OK  OK  [wall=110s]
load-2   exit=0  Ran 118 tests in 112.309s OK  OK  [wall=113s]
load-3   exit=0  Ran 118 tests in 121.066s OK  OK  [wall=121s]
load-4   exit=0  Ran 118 tests in 117.991s OK  OK  [wall=119s]
load-5   exit=0  Ran 118 tests in 140.119s OK  OK  [wall=140s]
```

**Stability, re-derived on the closeout-round-2 tree.** The series above is the round-7 revision — the one
that exposed the momentary-hold and committed-stop regressions (§7; its `plain-7` line is the flake). The
same script (`evidence/goal8-hardening/stability-series.sh`, `STABILITY_OUT` pointed at a fresh file) was
then re-run on the fixed tree: fifteen runs, ten alone and five with four busy-loop processes saturating
the same four CPUs (`nproc` = 4). Every run exited 0 with `Ran 120 tests` and `OK`; every run's summary
line, verbatim:

```text
plain-1  exit=0  Ran 120 tests in 98.982s OK  [wall=99s]
plain-2  exit=0  Ran 120 tests in 98.751s OK  [wall=99s]
plain-3  exit=0  Ran 120 tests in 99.570s OK  [wall=100s]
plain-4  exit=0  Ran 120 tests in 102.780s OK  [wall=102s]
plain-5  exit=0  Ran 120 tests in 100.353s OK  [wall=101s]
plain-6  exit=0  Ran 120 tests in 99.666s OK  [wall=100s]
plain-7  exit=0  Ran 120 tests in 100.344s OK  [wall=100s]
plain-8  exit=0  Ran 120 tests in 98.429s OK  [wall=99s]
plain-9  exit=0  Ran 120 tests in 99.847s OK  [wall=100s]
plain-10  exit=0  Ran 120 tests in 98.248s OK  [wall=99s]
load-1  exit=0  Ran 120 tests in 113.369s OK  [wall=113s]
load-2  exit=0  Ran 120 tests in 120.137s OK  [wall=121s]
load-3  exit=0  Ran 120 tests in 140.306s OK  [wall=140s]
load-4  exit=0  Ran 120 tests in 121.954s OK  [wall=123s]
load-5  exit=0  Ran 120 tests in 115.212s OK  [wall=115s]
```

The fifteen runs measured exactly the files the confirmation run in §2's first gate row measured next
(no edit was made in between): `Ran 120 tests in 98.712s` → `OK`, exit 0. The adapter and its test file
were byte-identical across all sixteen runs (adapter sha256
`5b01fd9a40b9ec4b7cc331e1691f6819d28de647e48b5532e239e6b7b820b241`, test sha256
`3fcf5bc61c3495c2ff8c5e709d247f4fc5fd26973e1ffec4c17ec67b07699fe9`). A final run, made after the
fifteen summary lines and the gate rows above were written into this record, ran
`Ran 120 tests in 98.004s` → `OK` (exit 0); after it, this record's own text is the only thing that
changed.


## 3. What the suite pins, verified by mutation

Each mutant was applied to a **copy** of `skills/gdd/scripts` under `/tmp` (the worktree adapter was never
written), the full suite was run from that copy, and the copy was removed. The worktree adapter's sha256
on the round-5 tree is `92e5fe60deed04d60563147ed49a7c2509f98f94b36376aad99e1d7cfe5dc9c0`. A mutant that
survived would mean the suite does not pin the clause. The four mutants below were re-run on the round-5
tree (68 tests each, ~62 s each, all measured):

| Removed behaviour | Suite result (68 tests) |
|---|---|
| completion no longer checks `final_reason` (`exit 0` alone is `done`) | `FAILED (failures=5)` |
| the runner no longer records `stopped_by` | `FAILED (failures=1, errors=1)` |
| the resolved `DSH_RUN_EVENTS_MAX_BYTES` is not handed to the bounded writer | `FAILED (failures=1)` |
| stale recovery finalizes nothing | `FAILED (failures=6)` |
| unmutated tree | `Ran 68 tests in 62.734s` → `OK` (§2) |

**Round 5's own pins, verified the same way.** Thirteen further mutants were applied one at a time to a
copy, each reverting exactly one round-5 fix, and only that fix's new test(s) were run against the copy
(a pinned test must fail there). All thirteen were pinned: the `.`/`..` guard in `sanitize`; the date-bucket
proof in `checked_run_dir`; the leader-gone refusal in `signal_group`; the identity gate in
`signal_member_group`; the survivors branch in the runner and the survivors in `recorded_processes`; the
live-run refusal in `_run`; the `backend: dsh` gate in `effective_state`, in `cmd_kill` and in
`start --replace`; the `TZ`/`LC_ALL` view of the `ps` identity probe; the platform branch in
`stop_signal`; and the `taskkill` failure check. Each mutant's targeted run reported `FAILED`/`ERROR`
(the `signal.SIGKILL`-on-Windows mutant errors with `AttributeError`); the copy was restored from the
worktree adapter before each mutant, so every mutation started from the pristine file.

**Round 6's own pins, one mutation per rule, verified the same way.** Each mutant was applied to a fresh
copy of `skills/gdd/scripts` under `/tmp` (`.tmp-artifacts/round6-tests/r6-mutate.py`, reused for both
sub-mutations of a rule), only the rule's new test(s) were run against the copy, and the copy was removed;
the three documentation mutations were applied to the worktree files for the duration of one test run and
restored byte-for-byte (`sha256sum -c`). Every mutant was caught:

| Rule | Mutation applied | Targeted run |
|---|---|---|
| R1 | `terminate_agent` returns `[]` instead of `None` for a failed enumeration, and for a Windows stop with no `taskkill` receipt | `FAILED (failures=2)` — `test_34`, `test_the_stop_outcome_has_three_distinct_values` |
| R2 | `report_incomplete_stop` records no survivors and `survivors_complete: true` | `FAILED (failures=3)` — `test_34`, `test_35`, `test_45` |
| R2 | `occupying_run` drops the unresolved-stop check | `FAILED (failures=1)` — `test_34` |
| R3 | both generation checks in `finalize` are disabled | `FAILED (failures=2)` — `test_39`, `test_a_terminal_write_is_bound_to_the_run_generation` |
| R4 | `start_run` runs `_start_run_claimed` without taking the slug claim | `FAILED (failures=1)` — `test_40` |
| R4 | `runner_main` runs the replay/takeover path without taking the slug claim | `FAILED (failures=1)` — `test_41` |
| R5 | the `lifecycle` field is removed from `status` and `result` | `FAILED (errors=5)` — `test_42`–`test_46` |
| R6 | `transport.md` loses the raw signal codes `-2`/`-9`/`-15` | `FAILED (failures=1)` — `test_the_documents_state_the_same_exit_mapping` |
| R6 | `transport.md` loses the "host's harness enforces a sandbox" precondition | `FAILED (failures=1)` — `test_transport_and_the_skill_state_the_same_isolation_precondition` |
| R6 | this record re-grows a sentence describing a different provider route for the author's smoke | `FAILED (failures=1)` — `test_the_record_does_not_claim_a_substituted_provider_route` |
| — | unmutated tree | `Ran 89 tests` → `OK` (§2) |

### Round-7 mutations, per rule

Each mutant reverts exactly one rule in a **copy** of the tree (`docs/`, `skills/gdd`,
`skills/dsh-headless-gdd`), and the increment's suite is run from that copy; the worktree is never
written. The mutants were applied with string replacements against the round-7 adapter and documents, so
a patch that no longer matches reports itself as skipped rather than passing silently.

| Mutation | Rule | Suite (`Ran …`) | Verdict | Tests that failed |
|---|---|---|---|---|
| `finalize()` releases M after the guard and publishes without it | L1 | `Ran 118 tests in 87.487s` | `FAILED (failures=3)` | `test_33_a_failed_stop_keeps_the_run_live_and_stoppable`, `test_a_failed_stop_records_survivors_without_finalizing`, `test_l1_a_finalization_cannot_be_interleaved_with_a_replacement` |
| a failed lock acquisition proceeds (the deadline branch sets `locked = True`) | L2 | `Ran 118 tests in 84.179s` | `FAILED (failures=9)` | `test_27_the_slug_claim_is_a_root_level_os_lock`, `test_40_two_concurrent_starts_produce_exactly_one_agent`, `test_41_a_start_concurrent_with_a_replay_produces_exactly_one_agent`, `test_a_held_finalize_claim_stops_a_reader_from_finalizing`, `test_l1_a_finalization_cannot_be_interleaved_with_a_replacement`, `test_l2_a_held_lock_is_never_taken_by_age` … (9 failures in total) |
| `lock_handle_for()` unlinks the lock file before opening it | L2 | `Ran 118 tests in 85.073s` | `FAILED (failures=8)` | `test_27_the_slug_claim_is_a_root_level_os_lock`, `test_40_two_concurrent_starts_produce_exactly_one_agent`, `test_41_a_start_concurrent_with_a_replay_produces_exactly_one_agent`, `test_a_held_finalize_claim_stops_a_reader_from_finalizing`, `test_l1_a_finalization_cannot_be_interleaved_with_a_replacement`, `test_l2_a_held_lock_is_never_taken_by_age` … (8 failures in total) |
| `finalize()` takes S as well as M (the reverse of the lock order) | L3 | `Ran 118 tests in 149.523s` | `FAILED (failures=1)` | `test_l1_a_finalization_cannot_be_interleaved_with_a_replacement` |
| `lifecycle_lock_path()` ignores the slug (one mutex for every run) | L4 | `Ran 118 tests in 89.638s` | `FAILED (failures=1)` | `test_l4_locks_are_keyed_by_slug_not_by_date_or_root` |
| `_start_run_claimed()` skips the phase-3 target comparison | G1 | `Ran 118 tests in 134.748s` | `FAILED (failures=2)` | `test_g1_a_target_that_changed_between_capture_and_commit_is_refused` … (2 failures in total) |
| `request_stop()` writes its request without the guard | G2 | `Ran 118 tests in 94.496s` | `FAILED (failures=1)` | `test_g2_a_stale_kill_cannot_request_or_wait_against_the_new_run` |
| `stop_request_for()` accepts any payload (existence is a request) | G3 | `Ran 118 tests in 95.800s` | `FAILED (failures=1)` | `test_g3_only_the_runs_own_wellformed_stop_request_is_actionable` |
| `terminate_agent()` authorizes once and caches it across steps | G4 | `Ran 118 tests in 107.508s` | `FAILED (failures=1)` | `test_g4_every_escalation_step_reauthorizes_the_generation` |
| the tracker publishes without its guard | G5 | `Ran 118 tests in 94.005s` | `FAILED (failures=1)` | `test_g5_every_publisher_is_generation_bound` |
| `_effective_state_locked()` skips the live-owner check | G7 | `Ran 118 tests in 199.461s` | `FAILED (failures=12)` | `test_03_live_run_reports_running_then_settles`, `test_08_kill_stops_a_live_run_through_the_stop_file`, `test_09_kill_escalates_when_nothing_observes_the_control_file`, `test_12_second_start_is_refused_and_replace_restarts`, `test_12b_replace_stops_a_live_run_before_restarting_it`, `test_18_detachment_is_measured_not_asserted` … (12 failures in total) |
| `report_incomplete_stop()` writes without the state/generation re-check | G8 | `Ran 118 tests in 94.434s` | `FAILED (failures=3)` | `test_g8_a_late_stop_report_cannot_revive_a_committed_verdict`, `test_g9_a_legacy_record_is_readable_and_can_mutate_nothing`, `test_l4_a_foreign_run_is_never_mutated` |
| `strict_generation()` falls back to the `name|started` token | G9 | `Ran 118 tests in 96.990s` | `FAILED (failures=1)` | `test_g9_a_legacy_record_is_readable_and_can_mutate_nothing` |
| the `finalized` marker is written before the `state.json` commit | T1 | `Ran 118 tests in 95.577s` | `FAILED (failures=3)` | `test_t1_death_at_each_publication_boundary_leaves_one_verdict` … (3 failures in total) |
| `write_text_atomic()` truncates the destination when `os.replace` fails | T2 | `Ran 118 tests in 91.674s` | `FAILED (failures=2)` | `test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop`, `test_t2_an_atomic_write_failure_never_truncates_the_destination` |
| `commit_terminal()` ignores the stop evidence (`blocked = ""`) | T3 | `Ran 118 tests in 90.620s` | `FAILED (failures=2)` | `test_33_a_failed_stop_keeps_the_run_live_and_stoppable`, `test_a_failed_stop_records_survivors_without_finalizing` |
| `stop_run()` declares the stop complete and ignores the survivor evidence | T4 | `Ran 118 tests in 90.662s` | `FAILED (failures=2)` | `test_33_a_failed_stop_keeps_the_run_live_and_stoppable`, `test_a_failed_stop_records_survivors_without_finalizing` |
| the Linux token drops boot id/namespace and falls back to `ps:` | P1 | `Ran 118 tests in 95.715s` | `FAILED (failures=2)` | `test_p1_the_linux_identity_binds_boot_and_namespace`, `test_the_ps_identity_probe_fixes_its_own_view` |
| `identity_is_strong()` admits the `ps:` display timestamp | P2 | `Ran 118 tests in 91.899s` | `FAILED (failures=2)` | `test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop`, `test_the_ps_identity_probe_fixes_its_own_view` |
| `signal_instance()` signals by bare pid instead of the validated handle | P3 | `Ran 118 tests in 95.384s` | `FAILED (failures=3)` | `test_a_verified_member_names_the_group_of_a_gone_leader`, `test_p3_delivery_stays_on_the_handle_that_was_validated`, `test_signal_group_refuses_a_pid_it_cannot_prove` |
| `stop_survivors()` returns `[]` when no anchor is left | P4 | `Ran 118 tests in 94.550s` | `FAILED (failures=1)` | `test_a_vanished_leader_is_never_signalled` |
| `signal_member_group()` falls back to the recorded group id | P5 | `Ran 118 tests in 94.807s` | `FAILED (failures=1)` | `test_p5_membership_must_be_readable_and_matching` |
| `anchored_members()` drops the post-enumeration anchor check | P6 | `Ran 118 tests in 95.091s` | `FAILED (failures=1)` | `test_p6_an_anchor_that_leaves_the_enumeration_discards_it` |
| `signal_member_group()` requires a live group leader | P7 | `Ran 118 tests in 95.740s` | `FAILED (failures=1)` | `test_a_verified_member_names_the_group_of_a_gone_leader` |
| an inspection failure is read as `GONE` and skipped as a survivor | P8 | `Ran 118 tests in 95.222s` | `FAILED (failures=1)` | `test_p8_an_unreadable_process_table_stays_conservative` |
| `env_seconds()` drops `math.isfinite()` | B1 | `Ran 118 tests in 95.816s` | `FAILED (failures=9)` | `test_b1_every_configured_wait_is_finite` … (9 failures in total) |
| a momentary hold of M fails `start --replace` / `kill` (wait reverted to 0) | M1 | `Ran 118 tests in 100.497s` | `FAILED (failures=1)` | `test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop` |
| a committed stop is sampled once instead of waited out (`await_settled_stop` removed) | M2 | `Ran 120 tests in 96.751s` | `FAILED (failures=1)` | `test_l3_a_replace_waits_out_a_stop_that_is_not_settled_yet` |
| the settle wait ignores its bound (the deadline check removed, so an unproven tree is waited on forever) | M3 | `Ran 120 tests in 117.249s` | `FAILED (failures=1)` | `test_l3_the_settle_wait_is_bounded_and_the_refusal_stands_at_the_bound` |
| `transport.md` loses the raw signal codes from the `killed` entry | Q3/R6 | `Ran 118 tests in 95.138s` | `FAILED (failures=2)` | `test_q3_the_document_mapping_check_catches_a_swapped_mapping`, `test_the_documents_state_the_same_exit_mapping` |
| `SKILL.md` restores the repository-wide writer sentence | Q3/R6 | `Ran 118 tests in 96.045s` | `FAILED (failures=1)` | `test_the_docs_state_the_write_isolation_unit` |

All 31 mutants made the suite fail (`31/31`); none survived. The 28 rule rows are the driver's own earlier
measurements on the round-7 revision; `M1`–`M3` were measured in the closeout passes described in §7
(`M1` on the 118-test revision, `M2`/`M3` on the final 120-test revision). `M1` and `M2` revert,
respectively, the bounded wait for the lifecycle mutex and the settle wait for a committed stop; `M3`
removes that settle wait's bound, so a tree that stays unproven is waited on forever. Each revert fails
exactly the test added with the rule it reverts. The three rows whose targets live in files this round
touched (`M1`, `R6-transport`, `R6-skill`) were also re-run on the final revision and still fail exactly
their rules' tests; being a re-check, their rows are kept beside the table
(`evidence/goal8-hardening/mutation-results-recheck-closeout2.tsv`) rather than rewriting the measured
pass. Each row's `Ran … in Xs` line and failure list are that mutant's own output; the driver (kept at `evidence/goal8-hardening/mutation-drive.py`, its raw rows at `mutation-results-final.tsv`) refuses to pass silently when a mutation no longer matches its target — the one row that did (`R6-transport-loses-the-raw-signal-codes`, reported as `SKIPPED-patch-not-found` in the earlier partial pass) was re-derived from the entry's current text and is measured here. Rows whose failing line is not their own rule's test (`L1`, `L2`, `G7`, `B1`, `G8`) report more than one failure because the reverted code path is shared; each rule's own pin is named in §7 and in §4's coverage map.

A mutant that survives would mean the suite does not pin the rule; the rows above are the measured
result, and the "unmutated tree" row is the same revision without any revert (`Ran 116 tests` → `OK`).

## 4. Stub-suite coverage map

| Clause | Tests |
|---|---|
| settled run, artifacts, answer, views, ledger-free state | `test_01`, `test_02`, `test_03`, `test_17` |
| exit-code and completion mapping | `test_04`, `test_05`, `test_06`, `test_22`, `test_completion_mapping_is_exhaustive`, `test_a_final_with_a_null_reason_is_not_completion`, `test_killed_exit_codes_are_the_documented_set`, `test_the_killed_mapping_documents_both_routes` |
| `start` dispatch confirmation: the recorded agent is the proof, alive or gone | `test_28`, `test_29`, `test_16`, `test_start_fails_when_only_the_runner_recorded_a_pid` |
| stale recovery, idempotence, marker repair, claim exclusivity | `test_07`, `test_21`, `test_stale_recovery_is_the_only_path_to_exit_minus_one`, `test_a_terminal_state_without_a_marker_is_repaired_from_its_commit`, `test_the_tracker_stops_publishing_before_the_verdict_is_committed`, `test_a_held_finalize_claim_stops_a_reader_from_finalizing`, `test_write_json_temp_names_are_unique_per_call` |
| kill through the control file + forced escalation, identity-gated signals | `test_08`, `test_09`, `test_12b`, `test_19`, `test_a_recycled_pid_is_not_alive_for_this_run`, `test_signal_group_refuses_a_pid_it_cannot_prove`, `test_kill_tree_leaves_an_unverified_pid_alone`, `test_a_vanished_leader_is_never_signalled`, `test_a_verified_member_names_the_group_of_a_gone_leader`, `test_the_stop_escalation_branches_on_the_platform`, `test_a_failing_taskkill_is_reported_not_assumed` |
| a stop that cannot end every process stays live/stopping until a later attempt | `test_33`, `test_a_failed_stop_records_survivors_without_finalizing`, `test_a_recycled_pid_is_not_alive_for_this_run` |
| slug/date-bucket escape and live-run replay refused before any write | `test_30`, `test_31`, `test_a_run_dir_must_be_a_direct_child_of_a_date_bucket` |
| route-scoped discovery, recovery and signalling (`backend: dsh` only) | `test_32` |
| stop outcomes: proven gone / survivors known / enumeration failed | `test_34`, `test_the_stop_outcome_has_three_distinct_values`, `test_a_run_that_stopped_without_enumeration_is_never_recovered_as_failed` |
| a failed stop stays non-terminal, reported live, occupying its slug and killable | `test_35`, `test_36`, `test_37`, `test_38` |
| a terminal write bound to the run generation | `test_39`, `test_a_terminal_write_is_bound_to_the_run_generation` |
| one agent per run: two starts, and a start against a replay | `test_40`, `test_41`, `test_the_runner_handshake_is_single_use` |
| the lifecycle vocabulary in `status`/`result`/`answer`/`list` | `test_42`–`test_46`, `test_the_lifecycle_words_are_the_documented_five` |
| one statement of the contract across the documents | `test_the_documents_state_the_same_exit_mapping`, `test_transport_and_the_skill_state_the_same_isolation_precondition`, `test_the_record_does_not_claim_a_substituted_provider_route`, and round 7's `test_q3_the_document_mapping_check_catches_a_swapped_mapping` / `test_the_docs_state_the_write_isolation_unit` (association checks, each mutation-checked on a copy) |
| round 7: the mutex covers a whole publication and a preparation re-checks its target | `test_l1_a_finalization_cannot_be_interleaved_with_a_replacement`, `test_g1_a_target_that_changed_between_capture_and_commit_is_refused` |
| round 7 closeout: a momentary hold and a committed stop are waited out, never refused — and the wait is bounded | `test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop`, `test_l3_a_replace_waits_out_a_stop_that_is_not_settled_yet`, `test_l3_the_settle_wait_is_bounded_and_the_refusal_stands_at_the_bound` |
| round 7: kernel ownership, lock namespace, no reversed lock order | `test_l2_a_held_lock_is_never_taken_by_age`, `test_l2_a_lock_io_failure_denies_every_mutation`, `test_l3_waits_hold_no_mutex_and_finalization_takes_no_start_claim`, `test_l3_same_process_writers_are_serialized`, `test_l4_locks_are_keyed_by_slug_not_by_date_or_root`, `test_l4_a_foreign_run_is_never_mutated` |
| round 7: generation binding of stops, escalations, publishers and late reports | `test_g2_a_stale_kill_cannot_request_or_wait_against_the_new_run`, `test_g3_only_the_runs_own_wellformed_stop_request_is_actionable`, `test_g4_every_escalation_step_reauthorizes_the_generation`, `test_g5_every_publisher_is_generation_bound`, `test_g5_a_merge_never_republishes_a_stale_snapshot`, `test_g8_a_late_stop_report_cannot_revive_a_committed_verdict` |
| round 7: recovery repeats its predicate; a legacy record authorizes nothing | `test_g7_recovery_repeats_its_liveness_predicate_under_the_mutex`, `test_g7_a_committed_recovery_is_never_rewritten`, `test_g9_a_legacy_record_is_readable_and_can_mutate_nothing` |
| round 7: one terminal commit, atomic writes that never truncate, no unproven stop | `test_t1_death_at_each_publication_boundary_leaves_one_verdict` (three boundaries, including `exit 0` without a completed `final` → `failed`), `test_t2_an_atomic_write_failure_never_truncates_the_destination` |
| round 7: process instance, membership and capability fail closed | `test_p1_the_linux_identity_binds_boot_and_namespace`, `test_p3_delivery_stays_on_the_handle_that_was_validated`, `test_p5_membership_must_be_readable_and_matching`, `test_p6_an_anchor_that_leaves_the_enumeration_discards_it`, `test_p8_an_unreadable_process_table_stays_conservative` |
| round 7: every configured wait is finite | `test_b1_every_configured_wait_is_finite` |
| identity probe's own view (`TZ`/locale fixed) | `test_the_ps_identity_probe_fixes_its_own_view` |
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
# the profile is used as it is: the route resolves its provider key from the launch environment
# (the profile's apiKeyEnv), which is the recommended shape; see the deviation note below
cd <worktree>
export DSH_HOME=/tmp/dsh-adapter-smoke/home
export DSH_BIN=$(command -v dsh)          # resolved on this host to <HOME>/.npm-global/bin/dsh, 0.2.2-rc.1
export GDD_RUN_ROOT=/tmp/dsh-adapter-smoke/runs
unset DSH_PROFILE DSH_PROFILE_DIR DSH_SESSION_ID   # the harness's own identity; reserved names, never the adapter's
printf 'Reply with exactly: ADAPTER_SMOKE_OK\n' > /tmp/dsh-adapter-smoke/prompt.md
```

The scratch copy's cleanup is `rm -rf /tmp/dsh-adapter-smoke` (not yet run: it is still present on the
authoring host, owned by the operator's user). Nothing in it was printed, read back into this record or
committed, and it is not the live `$DSH_HOME`.

Then, in this order:

```bash
python3 skills/gdd/scripts/adapters/dsh-run.py start --name adapter-smoke \
    --prompt /tmp/dsh-adapter-smoke/prompt.md --cwd /tmp/dsh-adapter-smoke/work --max-time 240
python3 skills/gdd/scripts/adapters/dsh-run.py status adapter-smoke
python3 skills/gdd/scripts/adapters/dsh-run.py answer adapter-smoke
```

This dispatch ran before round 1 renamed the adapter's profile key: the environment above unsets the
three harness-reserved names, so the same block selects profile `headless` under the final adapter; it
was not re-run in rounds 2–5.

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
`EACCES: permission denied, open '<HOME>/.dsh/profiles/headless/cordis.yml'`. The smoke therefore used a
scratch `DSH_HOME`: exactly the `mkdir -p` + `cp -a` block above, a copy of `<HOME>/.dsh/profiles`
(2 MB of `node_modules` symlinks into the installed CLI plus the per-profile trees; the profile this route
composes, `headless/`, is 24 KB of configuration). That copy matched the live tree with no differences
outside the installed `node_modules` — including the profile's patch layer, which is the empty list `[]`
in both — so the route this smoke reached came from the profile copy plus the launch environment. Whether
that route was the live default route or the local `ghc` route is **not verified here**: the orchestrator's
acceptance record states the author's run used the local `ghc` route
([`ORCHESTRATOR-ACCEPTANCE.md`](../goal8-pilot/ORCHESTRATOR-ACCEPTANCE.md), "Canonical real dispatch"), and
nothing retained in this repository — no `dsh` config dump, no route field in `state.json`, no log line —
can confirm or refute which route the profile copy composed. The canonical evidence for the route question is
the operator's own dispatch, which ran on the **default** route with the real credential in the launch
environment (§ appendix); the author's smoke is evidence for the adapter, not for the route.
The recommended shape, and the one the operator's canonical dispatch used (§ appendix), is exactly that
environment-only form with the live `$DSH_HOME`, so no profile file is ever copied; the author's nested
sandbox could not write the live profile directory and took the scratch route instead. The copy lived only
under `/tmp/dsh-adapter-smoke/home` (a scratch directory owned by the operator's user, outside this
repository), was never printed, and its cleanup is `rm -rf /tmp/dsh-adapter-smoke`. The CLI, the profile
composition, the model call, the NDJSON stream and the exit codes are real; only the scratch home differs
from a canonical dispatch.

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
  green in every round-5 and round-6 run (§2).
- The author's real dispatch used the scratch `DSH_HOME` described in §5; rounds 2–6 did not re-run it. No
  run was made here against the operator's live `<HOME>/.dsh`. The adapter neither reads nor stores a
  credential: it passes the launch environment through, and the scratch copy — described in §5 with its
  exact `mkdir -p`/`cp -a` command and its `rm -rf` cleanup — was never printed or committed. Rounds 2–6
  re-ran the stub suite, not a real model dispatch.
- The operator's canonical dispatch (§ appendix) is the run on the default profile route; its numbers
  come from the run directory itself.
- The Windows branch (hidden console, `taskkill /T /F`, `%COMSPEC%` shim handling) is implemented by
  analogy with the OMP adapter and is **not** executed here; the DSH facts were measured on Linux.
  `spawn`/`detach` record what the process observed, so a Windows operator can check the claim.
- Long stages, `--resume` and `--add-dir` are covered by the stub suite only; no real run exercised
  them.
- `--max-time` is the adapter's own deadline (DSH has no task-deadline flag); no real long-deadline run
  was exercised.
- The adapter writes no ledger row and no `ledger.tsv`; the authority is the committed terminal record
  inside `state.json` (`terminal_record{version, generation, commit_id, answer, session_id, exit}`),
  written last by one atomic replacement. The `finalized` marker keeps its historical exit-code-text form
  and is written *after* that commit, for the observer plugin and older readers only — no adapter
  decision reads it, as `references/transport.md` records.
- **Round-7 residual limits, stated as limits.** Destructive escalation exists only where a process
  instance can be proven through a `pidfd` handle plus a continuously verified group anchor; the
  macOS/Windows strong-identity and tree-termination capability is **UNCONFIRMED** here (those platforms
  refuse, and the code path is not executed on this host); Linux without `pidfd_open`/`pidfd_send_signal`
  refuses too, and `kill` then exits 1 with the run left `running`/`stopping` for the operator to finish
  by hand; `os.replace` is atomic, **not durable** across power loss or across filesystems; a descendant
  that deliberately leaves the recorded process groups is not guaranteed to be found; and nothing here
  arbitrates atomically against an external starter that does not follow this protocol.
- `usage` is the last `status` event's token accounting as DSH reported it (`total_tokens` includes
  cache reads); the adapter neither sums nor re-derives it, and marks it `usage_partial` when the
  event log was truncated.
- **The GDD consumer integration is a recorded operator step, not a stub-suite test.** The stub suite
  deliberately does not shell out to `gdd.py`: §5 checks the dispatcher↔adapter protocol with a stub
  `dsh`, and the operator's real stage dispatch through this adapter is recorded in the increment's
  acceptance record. No fake integration test was added; the limit stands as recorded rather than being
  papered over.
- **Environment note — the one CI step that cannot go green *on this host*.** CI runs the frozen OMP
  launcher suite, `python3 skills/gdd/scripts/tests/test_omp_run_python.py` (both of its files are
  untouched by this increment). On this host it reports `Ran 45 tests in 85.129s` →
  `FAILED (failures=1, skipped=3)`; the one failure is `test_18_tmux_backend_owns_its_session`, whose
  `start --backend tmux` cannot create a session: `omp-run: start: tmux new-session failed for
  omp-tmux-18`, and a direct probe gives the reason — `create window failed: fork failed: Permission
  denied`. This sandbox cannot fork for tmux, so the failure is environment-caused; nothing was edited to
  make it pass.
- **The pull request's CI results (measured facts about named heads, not about this tree).** Run
  [43655233172](https://github.com/wxxb789/hoa/actions/runs/43655233172) (`event: pull_request`, head
  `1a091bca528e768da86299c7ffb1fc2ba0cefa1e` — the committed round-5 tree, conclusion `success`): the
  `test` job succeeded (job
  [132632178055](https://github.com/wxxb789/hoa/actions/runs/43655233172/job/132632178055), including the
  step that runs the Python launcher suites), and the `release` job is `skipped` on pull requests (job
  [132632689438](https://github.com/wxxb789/hoa/actions/runs/43655233172/job/132632689438)). The earlier
  run [43650076593](https://github.com/wxxb789/hoa/actions/runs/43650076593) covers head
  `db557b340723da83674b30eec26bb3ff3d58a386` (the pre-round-5 tree) the same way. **No CI run covers the
  round-6 working tree**: this session cannot write the git index, so the branch head is still `1a091bc`
  and the four changed files are uncommitted, left for the operator to commit and push. The tmux
  failure recorded above is this sandbox's, not any of those runs'.

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

Round 5 (`fix-5-second-review.md`) answered the second independent machine-review cycle on the committed
head (`db557b3`); every finding below was accepted and fixed:

- **Adapter (A1–A7).** `start` refuses `.` and `..` and any run directory that is not a date bucket's
  direct child (`checked_run_dir`), before any write (A1); a process group whose leader is gone is never
  signalled by its bare id — only through a recorded member whose live identity still matches
  (`signal_member_group`), or not at all (A2); a stop that leaves processes alive publishes no terminal
  state — the run stays `running` with `stopping: true` and the survivors (pid, identity, group) recorded
  in `state.json` and `lock`, so it stays live for `run_alive`, stays occupied for `start`, and a later
  `kill` settles it through the survivors' identities (A3); `_run` refuses a run that is still live, so
  replaying a running run's `run.sh` cannot overwrite its runner pid or start a second agent on the same
  cwd (A4); discovery, recovery and signalling are scoped to runs whose `state.json` records
  `backend: dsh` — another route's run is listed `read-only(<backend>)` and is never finalized, rewritten,
  moved aside or signalled (A5); the `ps -o lstart=` identity probe runs with `TZ=UTC` and `LC_ALL=C` for
  that call only, so the caller's timezone is no longer part of the token (A6); the stop escalation
  branches on the platform — Windows never reads `signal.SIGKILL` (`stop_signal`), and a failing
  `taskkill` is reported instead of assumed (A7).
- **Tests (B1, B2).** The POSIX-only signal test is skipped on Windows (B1); the two hand-written recovery
  fixtures now record `backend: dsh`, like every run the adapter writes, so the A5 gate is exercised
  against this route's own runs. New pins: `test_30`–`test_33` (bucket escape, live replay, foreign-run
  recovery, failed stop) plus `test_a_vanished_leader_is_never_signalled`,
  `test_a_verified_member_names_the_group_of_a_gone_leader`,
  `test_a_failed_stop_records_survivors_without_finalizing`,
  `test_a_run_dir_must_be_a_direct_child_of_a_date_bucket`,
  `test_the_ps_identity_probe_fixes_its_own_view`,
  `test_the_stop_escalation_branches_on_the_platform` and
  `test_a_failing_taskkill_is_reported_not_assumed`; the suite grew from 57 to 68 tests. The archived
  goal's failure-control clause now states the exit→state mapping once — `killed` for the adapter's own
  stop and for a signal-convention exit (`KILLED_EXITS`), `failed` for any other non-signal non-zero
  exit, `failed`/`-1` with `stale_recovered` for an unfinalized death — matching `omp-run.py` rather than
  changing either adapter's mapping (B2).
- **Documentation (C1–C4).** The credential claim is precise: the adapter never reads, logs or stores a
  key and passes the environment through; the environment-only dispatch (the profile's `apiKeyEnv` in the
  launch environment) is the recommended and canonical shape; the smoke's scratch copy is described with
  its exact `mkdir -p`/`cp -a` command and its `rm -rf` cleanup, and the unsupported "carries the
  Authorization header" / "no credential was stored" pair is gone (C1). The skill's opening no longer
  promises a write boundary the working directory cannot give: the permission policy sets the boundary,
  `--cwd` selects the workspace, and changing either requires re-confirming it (C2). The CI claim cites
  the measured run — [43650076593](https://github.com/wxxb789/hoa/actions/runs/43650076593), `test`
  success, `release` skipped on pull requests — instead of predicting `ubuntu-latest` (C3). The
  changelog's exact count is re-derived from the final tree (68 tests), not the stale 55 (C4).

Round 6 (`fix-6-lifecycle-class.md`) answered the third independent machine-review cycle — a cross-family,
diff-only review whose findings were the third round of one class: what a run's recorded lifecycle may claim
versus what the adapter has proven. The six rules below are now the code's actual discipline, each pinned by
a test that fails when the rule is reverted (mutations in §3). Files changed: exactly the four this round was
allowed to touch (scope block below).

- **R1 — a terminal state requires proof, never an empty hole.** Every stop path ends in exactly three
  outcomes: *stopped* (proven gone), *not stopped, survivors known*, *not stopped, survivors could not be
  enumerated* (Windows has no group table; an inspection command can fail). `group_member_pids` and
  `surviving_members` return `None` — not `[]` — when they could not read the table, `terminate_agent`
  returns that third value, and `report_incomplete_stop` records it as `survivors_complete: false` together
  with every live recorded process it still knows, so a later attempt has real identities to verify. Only
  the proven outcome may reach a terminal state; on Windows the `taskkill` receipt is the proof.
- **R2 — an unconfirmed stop keeps the run live and the slug occupied.** The run stays non-terminal,
  `status`/`list` report it as stopping, `occupying_run` returns it even when no recorded process is alive,
  and a later `kill` can still finish it: a fresh, complete enumeration (`stop_survivors() == []`) or the
  survivors' recorded identities settle it as `killed`/`143`. No reader recovers such a run as `failed`/`-1`.
- **R3 — a terminal write is bound to the run generation.** Every run `start` writes records a `generation`
  token; `finalize` takes the caller's token before the decision, re-reads it inside the finalize claim, and
  writes nothing (with a named refusal) when the path now holds a different run. `effective_state` and
  `stop_run` report `recovered` only when the marker really landed.
- **R4 — one agent per run, atomically.** Every entry that can start an agent — `start`, and the `_run` a
  generated `run.sh`/`run.cmd` replays, including a dead-run takeover — takes the same stable
  `<slug>.start.lock` claim, which is a sibling of every date bucket and therefore does not move when a run
  directory is replaced. The runner `start` spawned proves it owns its directory with the single-use
  `spawn.token`/`DSH_RUN_SPAWN_TOKEN` handshake instead of re-claiming what its parent already holds.
- **R5 — every lifecycle answer names its uncertainty.** One vocabulary — `terminal`, `live`,
  `stopping (survivors known)`, `stopping (enumeration failed)`, `unknown (no state)` — is a `lifecycle`
  field in `status` and `result`, the named reason in `answer`'s refusal, and `list`'s single word
  (`running(live)`, `stopping(survivors-known)`, `stopping(enumeration-failed)`, `unknown(no-state)`).
  `run_dirs` now also lists a directory that never recorded a `state.json`, so `unknown (no state)` is
  listable rather than invisible.
- **R6 — one statement of the contract in every document.** `transport.md`'s DSH completion paragraph states
  the full exit→state mapping the archived goal's failure clause states (`killed` for this adapter's own stop
  and for a signal-convention exit, which keeps its raw code rather than being rewritten to `143`; `failed`
  for any other non-signal non-zero exit; `failed`/`-1` with `stale_recovered` for an unfinalized death), and
  its second DSH rule now carries the skill's isolation precondition: the permission policy constrains model
  tool writes only where the host's harness enforces a sandbox, `--cwd` selects a directory and is not itself
  a boundary, and changing the profile or `DSH_PERMISSION_MODE` requires re-confirming the boundary on the
  target host. This record's clause-4 row and §5/appendix state the mapping and the smoke's provider
  provenance as the artifacts support it: the copied profile's own configuration supplied the route and the
  launch environment supplied the key; the leftover sentence that had described the author's smoke as using a
  different provider route is gone and no credential value appears. The operating-method skill's "Stopping and
  recovering" stanza states the two
  endings an operator meets there (`killed`/143; `failed`/−1 with `stale_recovered`) without contradicting
  the full mapping; the skill was outside this round's four-file scope, so the signal-convention clause is
  pinned in the archived goal, `transport.md` and this record.
- **Review-scope notes, not defects.** Each review lane received one part of the 70-file branch, so "the diff
  lacks the stub suite / skill / transport section / evidence" and "the core implementation is not in the
  diff" are artifacts of that split: all of those files are in the branch and verified here (§1, §2, §4, §5).
  The GDD consumer integration is not exercised by the stub suite on purpose (it never shells out to
  `gdd.py`): the dispatcher↔adapter protocol is checked with a stub in §5 and the operator's real dispatch
  through the adapter is recorded in the increment's acceptance record, and §6 keeps that residual limit
  stated. The round-5 note that CI did not cover the round-5 tree was true at that review's moment; §6 now
  cites the measured run that covers the committed round-5 head and states plainly that no CI run covers the
  uncommitted round-6 tree.

Round-6 scope, `git status --porcelain` re-derived after the last edit of the cycle — exactly the four files
this round was allowed to change, no `VERSION`, no mirror, no index, no other adapter, no new dependency:

```text
 M docs/evidence/2026-11-15-dsh-headless-launcher.md
 M skills/gdd/references/transport.md
 M skills/gdd/scripts/adapters/dsh-run.py
 M skills/gdd/scripts/tests/test_dsh_run_python.py
```

The contract file was moved with a plain filesystem move (`mv`): it was untracked, and this session's
sandbox cannot write the git index (`.git/worktrees/hoa-wt/index.lock` resolves outside the workspace),
so `git mv` was not available. The worktree is left dirty for the operator to commit; no commit, push or
branch switch was made.

Round-4 tree scope, kept as it was recorded then (the increment was still uncommitted, and the closeout
round's mirror bookkeeping sat in the same working tree):

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

Round-5 final-tree scope, `git status --porcelain` re-derived on the round-5 tree. The increment is
committed as `db557b3`, and round 5 modifies exactly the six files this second review cycle was allowed to
change and nothing else — no `VERSION`, no version mirror, no index, no other adapter, no new dependency:

```text
 M CHANGELOG.md
 M docs/evidence/2026-11-15-dsh-headless-launcher.md
 M docs/goals/archive/2026-11-15-dsh-headless-launcher.md
 M skills/dsh-headless-gdd/SKILL.md
 M skills/gdd/scripts/adapters/dsh-run.py
 M skills/gdd/scripts/tests/test_dsh_run_python.py
```

The round-5 scope block above is the command's real output and was re-derived once more after the last
edit of the cycle.

Round 7 (`goal8-hardening`) is the hardening round the adjudicated review asked for: the launcher's
ownership and lifecycle were rewritten so that they are *provable* rather than documented, and every rule
below has a test that fails when the rule is reverted (mutation rows in §3). Files changed: the adapter
and its two suites, plus the four documents the mapping and the isolation wording live in (scope block
above them). Two locks carry ownership, both outside every replaceable run directory — S
(`<run root>/<slug>.start.lock`) for starting, M (`<run root>/.dsh-locks/<slug>.lifecycle.lock`) for
mutating — and both are kernel-held flock/`msvcrt` locks on files that are never unlinked and whose inode
is never replaced. Every mutation takes the immutable operation context (canonical root, slug, run path,
expected generation) and re-validates route, generation, process metadata and "no terminal verdict yet"
under M immediately before it writes, signals or enumerates; M is released across every wait. A
generation is mandatory: a record without one is readable and authorizes nothing. The terminal verdict is
one atomic `state.json` replacement written after the compatibility artifacts; the `finalized` marker is
written after the commit, for the observer plugin and older readers, and is never an authority. A stop
request names its generation and a runner acts only on its own; every escalation step re-authorizes; and
destructive signalling exists only through a validated `pidfd` handle with the group enumerated under a
continuously verified anchor — Linux without pidfds, macOS and Windows refuse to escalate, `kill` exits 1
saying so, and the operator ends the tree by hand and re-runs `kill`/`status`.

The third review cycle's findings, each with its resolution:

| # | Finding (round-3 review) | Resolution |
|---|---|---|
| A1 | the persisted Linux token had no boot-cycle/namespace field, so a recycled pid after a reboot could be mistaken for the old run | `_proc_stat_identity()` is `linux:v2:<boot-id>:<pid-namespace>:<pid>:<start-ticks>`, both components validated; with either unreadable the token is `""` and `process_identity()` on a `/proc` system never falls back to the weak `ps:` token; pinned by `test_p1_the_linux_identity_binds_boot_and_namespace` |
| A2 | `env_seconds()` accepted `inf`/`Infinity`, so a stop wait or drain timeout could never expire | `math.isfinite(value) and value > 0`, else the finite default; `parse_max_time()` refuses non-finite values; pinned by `test_b1_every_configured_wait_is_finite` over all three knobs and the flag |
| A3 | process groups were enumerated without proven ownership, so an unrelated process could be recorded as this run's survivor | ownership now comes from a currently verified recorded process (`anchored_members`), every member is re-validated (identity, current group) before it is recorded, and `stop_survivors()` returns `None` — never `[]` — when ownership or the table cannot be established; pinned by `test_p6_an_anchor_that_leaves_the_enumeration_discards_it`, `test_kill_tree_leaves_an_unverified_pid_alone`, `test_a_recycled_pid_is_not_alive_for_this_run` |
| A4 | a signal path kept using the recorded group id when the current group could not be read | `current <= 0` is a refusal ("a recorded group number is not a fallback") and a recorded group must equal the current one; pinned by `test_p5_membership_must_be_readable_and_matching`, `test_signal_group_refuses_a_pid_it_cannot_prove` |
| A5 | a replacement could interleave with a finalization and the old finalizer then overwrote the new generation | S and M are distinct objects outside the run directory; the finalizer holds M across the whole publication and `start` rebuilds the directory under M (`test_l1_a_finalization_cannot_be_interleaved_with_a_replacement` pauses the publication and proves a child process cannot pass M, then proves the stale generation writes nothing into the new one) |
| A6 | an old-generation `kill` could stop the run that replaced it | the stop request carries the generation, the runner acts only on its own (`stop_request_for`), and every escalation step re-authorizes under M; pinned by `test_g2_a_stale_kill_cannot_request_or_wait_against_the_new_run`, `test_g3_only_the_runs_own_wellformed_stop_request_is_actionable`, `test_g4_every_escalation_step_reauthorizes_the_generation` |
| A7 | a late incomplete-stop report could revive a committed terminal state | `report_incomplete_stop()` re-reads state and generation under M, refuses a committed verdict, and writes neither state nor lock; pinned by `test_g8_a_late_stop_report_cannot_revive_a_committed_verdict` (report A paused, stop B committed first, then a replacement) |
| T1 | the "ignores SIGTERM" fixtures reported the child's pid before its handler was installed | every fixture now acknowledges readiness through a pipe after installing `SIG_IGN`, and the parent blocks on that acknowledgement with a finite deadline (`ignoring_agent`, `group_with_ready_member`) |
| T2 | helpers leaked real processes when an assertion or the setup failed after `Popen` | every spawn registers `addCleanup(reap, process)` immediately after a successful `Popen`, and `reap` kills, waits and closes the pipes on every path; the class tears a run tree down through `kill_tree` |
| T3 | the gone-leader regression test used the still-live leader as its own member | `group_with_ready_member()` builds a leader plus a distinct ready member and the test reaps the leader before signalling through the member; pinned by `test_a_verified_member_names_the_group_of_a_gone_leader` |
| T4 | the failed-stop test accepted a stopped-survivor receipt while its victim was alive | `test_33` now drives a real subsequent stop and proves the victim's exit (`victim.poll()`) before accepting the terminal state; `test_38` proves the later attempt through `cmd_kill` |
| T5 | the "single-use" handshake test deleted the token itself instead of consuming it | `test_the_runner_handshake_is_single_use` authenticates through `consume_spawn_credential_locked()` (the real handshake) and replays the same credential, which is refused |
| T6 | the "same exit mapping" document test only checked keyword presence | `test_q3_the_document_mapping_check_catches_a_swapped_mapping` checks the *associations* per state in four documents and raises on mutated copies (the `failed` entry replaced by the `killed` entry, a dropped condition, each state missing) |
| D1 | the author's smoke was described as "no provider route substituted" while the orchestrator's record says the author's run used the local `ghc` route | the record now marks the author smoke's provider route **not verified** from the retained artifacts, and names the operator's default-route dispatch as the canonical route evidence (§5, appendix) |
| D2 | `CHANGELOG.md` still said "68 tests" for a suite that had grown | the entry now states the final count (116) and the round-7 rules |
| D3 | the "complete" exit→state mapping did not assign `exit 0` whose last `final` is missing or not `completed` | the clause is now in `transport.md`, the archived goal's failure clause, `SKILL.md` and this record, and pinned by `test_t1_death_at_each_publication_boundary_leaves_one_verdict` (the `exit-zero-without-final` boundary) and by the association checks |
| D4 | the skill said the whole repository never has two writers, contradicting the parallel-work guidance two lines above | the isolation unit is stated as the **worktree/session** (several goals of one repository run in parallel in their own worktrees; one worktree never has two writers), pinned by `test_the_docs_state_the_write_isolation_unit` with two mutations |
| — | tests-packet 2 and docs-packet 3 reported no findings beyond the ones above | nothing to fix; their "checked and correct" notes were re-verified against the round-7 tree |

Two review claims could not be reproduced and are recorded as such: the "replacement overwrites the new
run" sequence (A5) is now *impossible* rather than merely unlikely — S and M are separate objects, the
replacement rebuilds the directory under M, and the pause-and-probe test shows a child process refused
mid-publication — and the "old kill stops the new run" sequence (A6) is refused by the generation-bound
request. Both were fixed by construction, so the tests pin the property rather than the old symptom.


### Closeout round — the unpinned row, the momentary-hold regression, and the series

The closeout pass re-ran the mutation driver and found two things that the round-7 revision had not
settled.

1. **One mutation row never ran.** `R6-transport-loses-the-raw-signal-codes` reported
   `SKIPPED-patch-not-found`: the literal it removed had been reworded earlier in the round, so the
   driver refused to pass silently and said so. The document *does* state the raw codes in the `killed`
   entry. Deriving the mutation from the entry's current text, the re-run reports
   `FAILED (failures=2)` — exactly `test_q3_the_document_mapping_check_catches_a_swapped_mapping` and
   `test_the_documents_state_the_same_exit_mapping` — so the rule is pinned; a mutation that stops
   matching its target is a driver defect, not a documentation one.
2. **A real regression, found by the series, fixed and pinned.**
   `test_12b_replace_stops_a_live_run_before_restarting_it` failed intermittently with
   `start: run 'replace-12b' has a lifecycle operation in progress or its mutex is unavailable`: the
   round-7 rewrite made `start`, `request_stop` and the other "must land" writers take M *without
   waiting*, so a live run's own runner — publishing a tracker update, which holds M for a moment —
   could make `start --replace` (and `kill`) fail spuriously. The pre-rewrite adapter had no mutex in
   that path, so this was introduced by the rewrite, not inherited. The fix threads one constant
   (`MUTEX_WAIT_SECONDS = 5.0`) through the nine sites whose mutation must land (both `start` phases, the
   stop request, the runner's spawn registration, `update_lock`, `write_state_op`, both escalation-step
   authorizations, and the incomplete-stop report), keeping the bounded-wait policy in the lock-order
   comment; a held mutex still ends in a refusal. `stable_lock` also learned to tell a *contended*
   acquisition from a *broken* one (`_lock_contention`: `BlockingIOError`/EAGAIN, and EACCES/EDEADLK on
   Windows, versus everything else): only contention waits, so a read-only lock directory or an injected
   I/O failure is still refused immediately instead of waiting out the bound — the first version of this
   fix used a 30 s bound, so `test_l2_a_lock_io_failure_denies_every_mutation` waited it out four times
   (120.08 s of one test, from a `--durations 12` run) and the suite took 264.8 s instead of 94.8 s. `test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop`
   pins it deterministically (a child process holds M for 1.5 s; `start --replace` and `kill` must wait it
   out and succeed), and reverting the nine waits in a copy of the tree fails exactly that test
   (`FAILED (failures=1)` — row `M1` in §3).

The suite grew from 117 to 118 tests with that pin. Every count in this record that says 117 belongs to
a run made before the fix; the rows re-run afterwards (`M1`, `G8`, `R6-transport`) report the 118-test
revision.

### Closeout round 2 — a committed stop is waited out, not sampled once

The fifteen-run series (§2) found one further regression, in the same class as the momentary-hold one: a
run whose stop had *committed* was read as if its stop were unresolved. `plain-7` failed with

```text
FAIL: test_12c_a_momentary_mutation_never_fails_a_start_or_a_stop
AssertionError: 1 != 0 : start --replace failed: dsh-run: start: run 'momentary-12c' in
  <run root>/2026-11-15/momentary-12c still has unproven processes; refusing to replace it while a
  stop is unresolved
```

**Reproduced before fixing.** Thirty consecutive single-test runs of `test_12c` on the pre-fix tree
(`evidence/goal8-hardening/flake-repro.sh plain12c` — one process per run, `python3 -B -m unittest
discover … -k test_12c_…`) produced **2 failures** (runs 10 and 21) and 28 `OK`; thirty runs of `test_12b`
produced 30 `OK`. A temporary, environment-gated trace on the phase-3 settle sample (removed from the
final tree; the block was marked `REPRO-INSTRUMENTATION`) recorded one NDJSON line per sample — the exact
values the refusal uses — plus a raw dump (`state.json`, `lock`, `stop`, the `ps` table, the per-pid
liveness table) whenever a sample was unproven. Run 10's sample, verbatim:

```json
{"run_alive": true, "survivors_none": true, "survivors": null,
 "recorded": [{"pid": 108367, "liveness": "gone", "identity_strong": true, "group": 108367},
              {"pid": 108368, "liveness": "gone", "identity_strong": true, "group": 0}],
 "state": {"state": "killed", "exit": 143, "generation": "7e73fad1b3d2a7e6f81d211c85de05e7",
           "stopping": null, "survivors_complete": null},
 "terminal": true, "stop_request": true}
```

with the committed `state.json` (`killed`, `exit 143`, terminal record for that generation), the `stop`
request present (written 0.5 s earlier by the starting process), the recorded **runner** pid 108367 live
at the sampled instant — and the dump's own per-pid re-probe, microseconds later, reading both recorded
pids `gone`. The runner leads its own session, so its pid is also the group id the enumeration anchors
on. Run 21's sample has the same shape (`run_alive` true, `survivors` `None`, both pids gone by dump
time). Every other sample in the 30 runs (and in the series) was already conclusive: `run_alive` false and
`stop_survivors() == []`.

**The cause, as the code had it.** Phase 3 of `_start_run_claimed` sampled the settle evidence exactly
once, in one expression:

```python
            if run_alive(occupant, stopped_state) or stop_survivors(occupant, stopped_state) != []:
                die(... "still has unproven processes; refusing to replace it while a stop is unresolved")
```

`stop_run` returns as soon as a *validated terminal snapshot* is observable, and the runner that
publishes it holds M through the rest of its last publication, then has to return, flush its streams and
be reaped. Inside that window `run_alive` is still true for the runner, and `stop_survivors` returns
`None` — its "unknown" value, never `[]`, because `anchored_members` discards an enumeration whose anchor
leaves mid-way. Both readings are momentary; a sample-once refusal therefore fails the very run it just
stopped.

**The fix.** `SETTLE_WAIT_SECONDS = 10.0` (overridable per install with
`DSH_RUN_SETTLE_WAIT_SECONDS`) and `await_settled_stop(run_dir, generation, seconds=None)`, whose bound is
resolved at call time: after a
stop commits, the replace path re-asks the *same* predicate on freshly read state — `run_alive` false
**and** `stop_survivors() == []` — until it is conclusive or the bound expires, holding no lock (the
discipline `stop_run` and the start handshake already follow; phase 3 still re-checks everything under
M). A generation change ends the wait at once, and the phase-3 generation check reports that. The first
unproven sample is announced (`warn`) with the reason and the bound. It cannot mask an unproven stop: it
runs only after a validated terminal commit for the generation that was stopped, it uses the refusal's
own evidence on fresh state, it never signals and never writes, and a genuinely live survivor or an
unreadable process table never satisfies the predicate — the bound then expires and the refusal below
stands unchanged (not an infinite wait, and not a pass).

**The pins.** `test_l3_a_replace_waits_out_a_stop_that_is_not_settled_yet` stages the moment with no
sleep-based ordering: a child process in its own session waits for the `stop` control file, commits the
verdict through the adapter's *own* `finalize()`, and then stays alive while the replacement runs. The
replacement must not decide while the tree is still unproven (a bounded 2 s observation; a refusal there
fails the test with the refusal's stderr in the message) and must land once the child is reaped.
`test_l3_the_settle_wait_is_bounded_and_the_refusal_stands_at_the_bound` stages the other half of the
rule — a tree that *stays* unproven — and pins the bound itself: with `DSH_RUN_SETTLE_WAIT_SECONDS=1` the
replacement must exit 1 with the existing refusal inside the test's own 20 s deadline (an unbounded wait
fails it there), move nothing aside and leave the run in place. Reverting the wait (row `M2`) fails the
first test and only it; removing the bound (row `M3`) fails the second and only it. The suite grew from
118 to 120 tests; thirty further single-test runs of `test_12c` and of `test_12b` passed on the fixed
tree (60 `OK`) before the bound pin — with the small call-time bound resolution it needs — and the
docstring clause were added, and the §2 series and the final confirmation run cover the final revision.

## Appendix — the operator's canonical dispatch

The author's dispatch ran the profile configuration itself under a scratch `DSH_HOME` (the copy and the
reason are in §5). Which provider route that copy reached is **not verified** from the retained artifacts;
the orchestrator's acceptance record states it was the local `ghc` route. The operator
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
