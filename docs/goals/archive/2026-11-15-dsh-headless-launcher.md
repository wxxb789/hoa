# Goal — a second headless route: DSH as a GDD launcher

Increment id: `dsh-headless-launcher`
Repo: `wxxb789/hoa` · one run · one PR · mergeable alone

## Why this exists (the failure it answers)

Goal-driven delivery dispatches every stage to an agent through a launcher that implements one contract
(`skills/gdd/references/transport.md`). Today the shipped route is OMP-only: `gdd.py` defaults to
`scripts/adapters/omp-run.py`, and the only alternative is the opt-in native Paseo adapter. The owner
runs DeepSeek Harness (`dsh`) on the same machine and wants GDD to be able to dispatch a stage to it
without changing the protocol, the stage semantics, or the ledger.

This increment adds that second headless route as one adapter. It must not touch `gdd.py`'s stage model,
must not add a dependency, and must not change any existing route's behaviour. The operating method for
the route ships with it as the `dsh-headless-gdd` skill, so the rules measured while building the adapter
are not left in a handoff note with nothing invoking them.

The intended outcome: `skills/gdd/scripts/adapters/dsh-run.py` implements the existing launcher contract
on top of `dsh --profile headless`, so `GDD_LAUNCHER=…/dsh-run.py python3 skills/gdd/scripts/gdd.py stage …`
dispatches the stage to DSH and the operator reads the same artifacts (`state.json`, `answer.md`, event
log, `exit.code`) through the same commands as the OMP route. DSH facts that shape the adapter are
recorded in the handoff note the implementer is given (`dsh-headless-facts.md`); the adapter must encode
them, not re-derive them by trial.

## 1. Observable pass condition

1. `skills/gdd/scripts/adapters/dsh-run.py` exists, is stdlib-only (no third-party import), and implements
   `start`, `list`, `status`, `result`, `answer`, `tail`, `kill` with the argument shapes the contract
   fixes (`start --name SLUG --prompt FILE [--cwd DIR] [--session-id ID] [--model M] [--thinking L]
   [--max-time D] [--resume ID] [--replace]`).
2. It creates `<run root>/<YYYY-MM-DD>/<SLUG>/` (the root is `DSH_RUN_ROOT` when set, else
   `GDD_RUN_ROOT`, else the documented default) containing at least `prompt.md`, `run.json`,
   an events log, `stderr.log`, `exit.code`, `answer.md`, `state.json`, and keeps `state.json` current with
   `{"name","state","exit","cwd","started","ended","duration_s"}` plus `state` in
   `running|done|killed|failed|unknown`.
3. `start` exits 0 only after the run has actually started, and refuses a second `start` for a slug whose
   run is still running.
4. Completion is decided as: `exit 0` **and** the last `final` event carries `reason.kind == "completed"`;
   anything else is `failed` (exit −1 when the run died without finalizing) or `killed` (exit 143 after a
   `kill`), and a dead unfinalized run is finalized by the next `status`/`result`/`list`/`answer` with
   `stale_recovered: true` — idempotently, guarded by a `finalized` marker.
5. `kill` works without signals: it writes a control file the monitor observes, waits for the run's own
   finalizer, and only then escalates to a process-group TERM/KILL.
6. The event log is bounded and reports `events_bytes`, `events_bytes_total`, `events_truncated`,
   `events_dropped_bytes`; counters derived from a truncated stream are marked `*_partial`.
7. `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_dsh_run_python.py'` passes with a
   stub `dsh` on `PATH` (no network, no model, no real run), covering: the settled run and its exit mapping,
   stale recovery, `kill` through the control file, the event-bound accounting, argv passthrough, and the
   refusal of a second `start`.
8. `skills/gdd/references/transport.md` gains the DSH row in the route table plus a short configuration
   table (`DSH_BIN`, `GDD_RUN_ROOT`, the `DSH_*` bounds it honours), and states the two DSH-specific rules:
   the run's cwd must be the worktree the session recorded, and `--approval-policy never` is required for
   unattended runs.
9. `docs/goals/README.md` lists this goal with its evidence file, and the evidence records one real
   end-to-end dispatch (`start` → `status` → `answer` through the adapter against a real `dsh` run) with
   the exit code and the artifact paths.
10. `skills/dsh-headless-gdd/SKILL.md` exists, declares `metadata.kind: mechanism`, and is referenced by the
    DSH route documentation in `skills/gdd/references/transport.md`, so the operating method is invoked by
    the route that needs it rather than left orphaned.

## 2. Judging artifact

- A run directory from a real dispatch, `<run root>/<YYYY-MM-DD>/<SLUG>/` (the root is `DSH_RUN_ROOT`
  when set, else `GDD_RUN_ROOT`, else the documented default), holding at least
  `prompt.md`, `run.json`, the events log, `stderr.log`, `exit.code`, `answer.md`, `state.json`, with
  `state.json` current and carrying `{"name","state","exit","cwd","started","ended","duration_s"}` plus
  `state` in `running|done|killed|failed|unknown`.
- `python3 -B -m unittest discover -s skills/gdd/scripts/tests -p 'test_dsh_run_python.py'` on the final
  tree with a stub `dsh` on `PATH`: no network, no model, no real run.
- The `gdd.py` dispatch shape: `launch()` against this adapter returns the run name, run directory and run
  root, and the run settles `state=done exit=0 final_reason=completed` with a stub `dsh`.

## 3. Failure control

- Completion is two conditions, never one: `exit 0` **and** the last `final` event carries
  `reason.kind == "completed"`. A `tool_result` status of `completed` only means the tool returned.
  Anything else is `failed` (exit −1 when the run died without finalizing, recovered by the next
  `status`/`result`/`list`/`answer` with `stale_recovered: true`, idempotently and only while no
  `finalized` marker exists) or `killed` with exit 143 after this adapter stopped it.
- A composition row that fails to load degrades the run **while the process still exits 0**
  (`stderr.log`: `did not activate` / `pending (waiting for service: …)`), so a green exit code alone is
  not a gate result: the operator re-runs the repository's gates on the final tree.
- Budget: two corrective rounds per stage, then stop and escalate (different model, narrower contract,
  abandoning). The route's own failures are loud rather than degraded: `--model`/`--thinking` are refused,
  a missing credential is `MISSING_CREDENTIAL` with exit 1, and a corrupt session log is refused with its
  byte offset.

## 4. Out of scope

- No change to `gdd.py`, `delivery-state.py`, the stage templates, or the merge gate.
- No PTC/Preset/executor selection: headless composes no agent presets, so `--model`/`--thinking` are
  refused and the provider route stays the profile's own configuration.
- No PR, no push: this worktree is local; the operator owns publication.
- No credential handling: the adapter passes the environment through and never reads or stores a key.

## 5. Evidence plan

- Unit suite with a stub CLI (the judging artifact above), run by the operator on the final tree.
- One real dispatch recorded under `docs/evidence/2026-11-15-dsh-headless-launcher.md`: the exact commands,
  exit code, `state.json`, and the first line of `answer.md`.
- `python3 -m compileall` on the new adapter, plus a `--help` run of each subcommand.
- The repository gates on the final tree: the adapter suite above, `python3 -B -m unittest discover -s
  scripts -p 'test_*.py'`, `check_frontmatter.py`, `check_contract_graph.py`, `generate_index.py --check`
  and `check_changelog.py`, each with its real exit code.

## 6. Mergeable alone

Adds `skills/gdd/scripts/adapters/dsh-run.py` and its stub suite
`skills/gdd/scripts/tests/test_dsh_run_python.py`, the `dsh-headless-gdd` skill, the DSH section of
`skills/gdd/references/transport.md`, the goal row in `docs/goals/README.md`, the evidence record and the
regenerated `index.md` / `index.zh-CN.md`. No change to `gdd.py`, `delivery-state.py`, the stage templates,
the merge gate or any other adapter, and no new dependency. Reverting the commit removes the DSH route and
restores every other route's behaviour exactly.
