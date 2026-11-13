---
name: omp-headless-orchestration
description: >-
  Run long OMP (`omp -p`) jobs headlessly so they survive the session that dispatched them — detached
  tmux, NDJSON event log, polled completion, session-id recovery. Use when delegating a repo task that
  will run more than a couple of minutes, when the orchestrating chat/session may restart, or when
  recovering a run that was killed mid-turn. Do not use for a two-minute command (run it inline) or for
  work that needs live steering (that is a TUI session).
metadata:
  version: "0.1.52"
  areas: "software-development,work-management"
  targets: "pi"
  summary: "detached tmux launcher for long `omp -p` runs; polled completion, session-id recovery"
  summary_zh: "脱离会话的 tmux 启动器跑 `omp -p` 长任务；轮询完成、按 session id 恢复"
  kind: "entry"
---

# OMP headless orchestration

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
tmux wrapper shipped with this skill:

```bash
scripts/omp-run.sh start --name <slug> --prompt <file> --cwd <repo> \
  [--resume <session-id>] [--model M] [--thinking L] [--max-time 3h] [--extra "--no-tools"]
scripts/omp-run.sh list | status <slug> | tail <slug> 20 | result <slug> | answer <slug> | kill <slug>
```

A detached tmux session hangs off the tmux server (init), not off your session, so it survives session
and gateway restarts. Verify with the ancestor chain of the omp pid, not by assumption.

The implementation is maintained once, with skill `gdd`
(`scripts/adapters/omp-run.sh`), because that skill's `gdd.py` defaults to it; the copy here
(`scripts/omp-run.sh`) is a forwarder, so manual and dispatched runs share one code path.

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
   above ~30 min is a kill risk; resuming needs the session id, so the wrapper captures it into
   `session.id` within seconds of start. **A review/simplify stage that fans out sub-reviewers costs
   the sum, not one pass** (~5 parallel reviewers, 20–100k tokens each, 35–40 min, tens of MB of
   events) — budget that, and do not read its timeout as a hang.
7. Model and thinking effort are coupled per provider: the fast reasoning model needs its high effort
   setting, a fallback model usually needs a lower one. A wrong pairing degrades quality silently.
   Record the pairing your CLI needs and pass it explicitly — never inherit a default.
8. Headless only works when the result is falsifiable. Treat the agent's report as a claim; re-run the
   repo gates yourself (build, test, format, docs snippets, api baseline, examples) and read exit codes
   before committing.
9. **Judge liveness from `state.json` / `tmux has-session`, never from `ps | grep <shim path>`.**
   Package-manager shims (`mise`, `asdf`, `volta`) point at a different binary than the one running, so
   grepping the shim path reports a healthy run as dead — use the pid in `state.json`.
10. **A tmux-hosted run has no completion notification.** Nothing pings you when it ends: poll
    `omp-run.sh status <slug>` at turn boundaries, and treat `state` leaving `running` (not the tmux
    session vanishing) as the done signal. A run whose pane died with its process is finalized as
    failed (`recovered_stale: true`, exit `-1`) the next time `status`/`list`/`result`/`answer` reads
    it; a state file stuck at `running` is not evidence that the work is alive — read `finalized` or
    the `stale_recovered` flag.
11. **`exit=0` means the process ended, not that the task finished.** A run can end its turn while a
    long command is still in flight and report "waiting for the test gate" as its last text. Read
    `answer.md` for trailing wait language before treating the phase as done; the fix is a continuation
    run (`-r <session-id>` plus a prompt that names the remaining steps), not a fresh restart.
12. **Never `omp-run.sh tail` a JSON-mode run to "see what it is doing".** Each event carries the full
    prompt of every sub-agent the run spawned, so one tail call returns hundreds of KB and floods the
    context for no signal. Poll `status <slug>` for liveness and read `answer.md` (or `result <slug>`)
    for the outcome; if you truly need the event stream, filter it by event type and count
    (`grep -c tool_execution_start`), never print it.
13. **`state.json` is not schema-stable across the run lifecycle.** Keys present while running (event
    byte counts, pid) are dropped when the run finalizes, so a reader that indexes them crashes on a
    finished run. Read `state`, `exit`, `duration_s`, `cwd` and `run_dir` defensively; treat everything
    else as optional.
14. **`--max-time` takes one unit only.** `omp --max-time 1h30m` exits 2 before any work with
    `Invalid --max-time value`, leaving a 0-byte `answer.md` and an empty event log — which reads like
    an instant crash, not a rejected flag. Use `90m`, `2h` or plain seconds. The wrapper does not
    validate this, so read `stderr.log` before blaming the prompt or the repo.

## Recovery after a session restart

```bash
scripts/omp-run.sh list          # GONE = crashed/killed, shows the resume id
```

Then `omp-run.sh start --name <slug>-r2 --prompt <continuation> --resume <id>`.

Artifacts per run: `<run>/prompt.md`, `run.sh` (replayable), `events.ndjson`, `stderr.log`,
`state.json`, `exit.code`, `session.id`, `answer.md`. Ledger: `$OMP_LEDGER`
(default `<run_root>/ledger.tsv`).

## When a TUI is still right

Ambiguous scope, work needing mid-run steering, or the operator explicitly asking to watch:
`tmux new -d -s omp-<slug> 'omp --resume <id>'` and let them attach. Never run a TUI and a headless
process on the same session id.

## Related

Delivery-specific transport rules (one run per stage, no cross-increment resume, one run per worktree):
skill `gdd` → `references/transport.md`. That skill's `scripts/gdd.py` calls this
launcher through the same contract.
