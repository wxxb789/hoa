---
name: gdd-route-omp
description: >-
  Use when delegating a repo task to OMP (`omp -p`) that runs more than a couple of minutes —
  standalone or as `gdd`'s OMP route — or recovering a run killed mid-turn. Launches it detached to
  survive session restarts: NDJSON event log, polled completion, session-id recovery. Not for a short
  command (run inline) or work needing live steering (TUI).
metadata:
  revision: "2"
  areas: "software-development,work-management"
  targets: "pi"
  summary: "detached runner for long `omp -p` runs; polled completion, session-id recovery (requires skill `gdd`)"
  summary_zh: "脱离会话的 runner 跑 `omp -p` 长任务；轮询完成、按 session id 恢复（需要 skill `gdd`）"
  kind: "entry"
---

# gdd-route-omp

Delegate bounded work to OMP (`omp -p`) without losing runs when the dispatching session, gateway or
terminal goes down.

## When to Use

- Delegating a repo task to OMP that will run longer than a couple of minutes.
- You are working from chat (Discord/Slack) and cannot watch a terminal, but the run must not die when
  the session ends.
- Recovering an OMP run that was killed mid-turn (needs its session id).
- Deciding between headless `-p` and an attachable tmux TUI.

## Rule: never launch OMP as a bare background job of the session

A background child of the orchestrating session receives SIGTERM when that session ends, and `omp -p`
prints only at exit — a run killed at minute 37 leaves a 0-byte output file. Always launch through the
shared runner (a detached process: own session on POSIX, one hidden console on Windows):

```bash
uv run ../gdd/scripts/agent_run.py start --agent omp --name <slug> --prompt <file> --cwd <repo> \
  [--resume <session-id>] [--model M] [--thinking L] [--max-time 3h] [--extra "--no-tools"]
uv run ../gdd/scripts/agent_run.py status <slug>
```

`--max-time` takes seconds or one unit (`90m`, `2h`); the runner enforces it (exit `124`, `failed`).

A detached run hangs off init (POSIX) or off the process tree Windows keeps alive on its own, not off
your session, so it survives session and gateway restarts. Verify with the ancestor chain of the omp
pid, not by assumption.

This skill requires skill `gdd`: the runner is maintained once, as gdd's `../gdd/scripts/agent_run.py`
(cross-platform, stdlib Python), because that skill's `gdd.py` launches through it too. Existing
POSIX callers can still use `scripts/omp-run.sh`, a forwarder that sets `GDD_AGENT=omp`.
Only if a script command fails (for example `uv` is not found), read
[the runner troubleshooting reference](../gdd/references/troubleshooting.md).

## Why headless (not TUI)

- Headless output is a machine-checkable artifact; you can work from chat and attach to a TUI only for
  rare manual intervention.
- A TUI in tmux loses information when the pane scrolls or the client detaches; the NDJSON event log
  does not.
- `--mode=json` gives live progress (`session`, `turn_start`, `message_start`,
  `tool_execution_start`, `message_update`, `message_end`, `turn_end`) — observability does not
  require a TUI.

## Pitfalls (each one observed in production)

1. `--restore` ("continue the interrupted turn") requires a TTY: it fails with
   `open terminal failed: not a terminal` under `-p`. Headless recovery is
   `omp -r <session-id> -p "<hand-written continuation prompt>"`.
2. `-p` emits nothing until exit. Without `--mode=json` a long run is a black box and a kill costs
   everything: always tee the event stream.
3. Never run a measurement/benchmark project concurrently with the full test suite on a host sized for
   one heavy job: the run dies as exit `-9` and looks like an OOM. Serialize heavy steps and say so in
   the prompt.
4. Approval must be resolved before launch: headless with the default approval mode blocks silently
   forever and no human sees the prompt. Use an explicit non-interactive approval mode (the wrapper
   passes `--approval-mode yolo`) **only** in repos with machine gates.
5. `-c` / "continue last session" is ambiguous when lanes run in parallel — always pass an explicit
   session id (`-r <id>`).
6. Budget by stage: a single implementation run costs 45–55 min, a review 15–30, a fix 10–25. Anything
   above ~30 min is a kill risk; resuming needs the session id, so the runner records it in
   `state.json` (`session_id`) the moment it appears. **A review/simplify stage that fans out sub-reviewers costs
   the sum, not one pass** (~5 parallel reviewers, 20–100k tokens each, 35–40 min, tens of MB of
   events) — budget that, and do not read its timeout as a hang.
7. Model and thinking effort are coupled per provider: the fast reasoning model needs its high effort
   setting, a fallback model usually needs a lower one. A wrong pairing degrades quality silently.
   Record the pairing your CLI needs and pass it explicitly — never inherit a default.
8. Headless only works when the result is falsifiable. Treat the agent's report as a claim; re-run the
   repo gates yourself (build, test, format, docs snippets, api baseline, examples) and read exit codes
   before committing.
9. **Judge liveness from `state.json` or the runner's `status`, never from `ps | grep <shim path>`.**
   Package-manager shims (`mise`, `asdf`, `volta`) point at a different binary than the one running, so
   grepping the shim path reports a healthy run as dead — use the pid in `state.json`.
10. **A detached run has no completion notification.** Nothing pings you when it ends: poll
    the runner's `status <slug>` at turn boundaries, and treat `state` leaving `running` as the done
    signal. A run whose runner and agent died is finalized as failed (`stale_recovered: true`, exit
    `-1`) the next time `status`/`list`/`result`/`answer` reads it; a state file stuck at `running` is
    not evidence that the work is alive — read `finalized` or the `stale_recovered` flag.
11. **`exit=0` means the process ended, not that the task finished.** A run can end its turn while a
    long command is still in flight and report "waiting for the test gate" as its last text. Read
    `answer.md` for trailing wait language before treating the phase as done; the fix is a continuation
    run (`-r <session-id>` plus a prompt that names the remaining steps), not a fresh restart.
12. **Never print the raw `events.ndjson` of a JSON-mode run.** Each event carries the full prompt of
    every sub-agent the run spawned, so one raw read returns hundreds of KB and floods the context for
    no signal. The runner's `tail <slug> [N]` prints one line per event (type plus at most 160 characters
    of text), which is safe; poll `status <slug>` for liveness and read `answer.md` (or `result <slug>`)
    for the outcome.
13. **`state.json` grows over the run lifecycle.** Counters and the final fields (`ended`,
    `duration_s`, `error`) appear as the run progresses. Read `state`, `exit`, `duration_s`, `cwd` and
    `run_dir` defensively; treat everything else as optional.

15. **A run that says it "launched" its verification is not evidence.** Whether teardown takes
    backgrounded children with it is the launcher's cleanup contract, not a universal law: a launcher
    that terminates its cleanup group at finalize (`systemd-run`, `KillMode=control-group`) kills a gate
    left under `&` / `nohup` with no exit code anywhere, while one that merely returns may leave it
    running. Require the exit code before treating the verification as done — a gate awaited to
    completion is fine, a gate left behind is not. The stage-side rule lives in skill `gdd` →
    `references/run-failure-modes.md` §8.

16. **A model-endpoint restart window is a transport fault, not a model defect — and a report-only
    stage can hide it behind `exit 0`.** The endpoint that fronts the models restarts on a schedule
    the operator's runtime configuration declares — read that schedule from the configuration, never
    assume it. A lane dispatched inside the window fails with `ECONNREFUSED`: classify that as
    suspected transport, not as a model failure. Confirm the window, retry **once** against the same
    route, and on a second failure switch to another model in the pool or fall back to the primary
    route — a third attempt on the same assumption is wasted budget. The window is doubly easy to miss
    because a report-only stage (simplify / review) can still exit 0 with an empty or truncated
    `answer.md`; that is a suspected failure to re-verify, not a completed stage — read the artifact,
    not just the exit code (pitfalls 8 and 11 are the same rule at the run level).

## Recovery after a session restart

```bash
uv run ../gdd/scripts/agent_run.py list  # failed(stale) = runner and agent died; sess= is the resume id
```

Then start a new run with `--agent omp --name <slug>-r2 --prompt <continuation> --resume <id>`.

Artifacts per run (`<run_root>/<YYYY-MM-DD>/<slug>/`): `prompt.md`, `run.json` (the exact argv),
`events.ndjson`, `stderr.log`, `runner.log`, `state.json` (the single record, including `session_id`),
`answer.md`, `exit.code`, `finalized`. There is no runner ledger; `list` shows every run.

## When a TUI is still right

Ambiguous scope, work needing mid-run steering, or the operator explicitly asking to watch:
`tmux new -d -s omp-<slug> 'omp --resume <id>'` and let them attach. Never run a TUI and a headless
process on the same session id.

## Related

Delivery-specific transport rules (one run per stage, no cross-increment resume, one run per worktree):
skill `gdd` → `references/transport.md`. That skill's `scripts/gdd.py` calls the same runner
through the same contract.
