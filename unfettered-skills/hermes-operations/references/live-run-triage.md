# Live-run triage: running, waiting, or hung

For the owner's "都在跑吗 / 真的在跑吗 / 还是 hang 住了" — a question about **detached lanes**
(`omp -p` runs, `pi -p` review lanes, `hermes -p <profile> chat … --oneshot -Q` dispatches, the
`systemd-run --user --collect` units wrapping them). Verdict per lane, from evidence. Dispatch intent,
an "in progress" state file and a silent log are all non-evidence (rule 22 for how the lane is
supervised; `hermes-gateway` for a batch killed by a gateway disconnect).

## Three verdicts

| verdict | shape | what decides it |
|---|---|---|
| running | work advances | a probe below moves between two samples |
| waiting | blocked on a sub-agent / background command / model call | the wait structure is visible in the lane's own state; **the common false alarm** — waiting looks exactly like hung |
| done / dead | nothing advances | a terminal artifact (`answer.md`, `exit.code`, `finalized`) or unit gone + no artifact |

**Sample twice, 30–60 s apart, and quote both values.** One snapshot cannot separate progress from a
stall, and "no error in the log" is not progress. Report the interval you used.

## Probes

1. **mtime before size.** `stat -c '%i %s %y %n' <events.ndjson>` twice. An NDJSON event log keeps a fixed
   head block plus a ring buffer (`events.stats.json`: `max_bytes` — 8 MiB default — `retained_bytes`,
   `total_bytes`, `dropped_bytes`), so a long run's file **shrinks** and its line count resets while it is
   working. Liveness = mtime advancing **and** `total_bytes` growing; fresh mtime with frozen `total_bytes`
   narrows the stall to the model call.
2. **Socket to the serving side.** `ss -tnp | grep "pid=<lane pid>"` → ESTAB to the model provider means it
   is streaming. A live pid at ~0 % CPU holding no socket is the shape of a hang.
3. **Process tree.** `pstree -p <pid>` / `ps --ppid <pid>`: live worker daemons or a spawned test runner
   prove work in flight; their absence while the parent sits idle is the opposite.
4. **Structured progress, if the lane publishes it.** An `omp -p --mode=json` run emits
   `tool_execution_update` events whose `partialResult` for a `task` (sub-agent) call carries the child's
   `lastIntent` and `contextTokens`. Values advancing across the two samples are the strongest signal
   available; `async: {state: running, jobId…, type: task}` is a normal wait, not a hang.
5. **Serving-side log for buffered lanes.** `journalctl --user -u <model proxy service> --since '-3 min'`
   filtered to the lane's model shows its requests being answered while its own output file is still empty.
6. **Unit state.** `systemctl --user show -p ActiveState,SubState,ExecMainStartTimestamp,Result <unit>`.

## Board-dispatched workers (a card is a lane)

A card dispatched to a profile runs as a normal agent session in **the assignee's own home**, so the card's
log file is not a progress feed: while the run is live it typically holds a session header line and nothing
else until the run ends. Read the store instead:

- `~/.hermes/profiles/<assignee>/state.db`, read-only: `sessions` (`message_count`, `tool_call_count`,
  `last_activity_description`) plus the tail of `messages` (role and first ~200 chars per row). A growing
  `tool_call_count` across two samples is the probe; the tail shows which commands and gates it is running.
- `last_activity_description` is the liveness line: it names the model being awaited and the wait state
  (e.g. a first-stream-chunk countdown). A long wait there is a provider stall — keep polling rather than
  re-dispatching, which spends a second worker on the same card.
- The worker's cwd is `~/.hermes/kanban/workspaces/<task_id>` and is commonly empty while it is busy,
  because the edits land in the target checkout the card pointed at. An empty workspace is not an idle
  worker.
- Board-level state comes from `list` / `runs <id>` / `show <id>`; a terminal run whose output says the
  execution outcome is unknown and retained by the owner means the worker died on a state transition, not
  that the work is missing — verify the artifact before re-running it.
- Subscribe the notification to the thread that asked for the work so the verdict lands there: a
  review-shaped card runs for many minutes and blocking a foreground turn on it spends the wait twice.
- Watching is not accepting — the worker's completion summary, including any verdict it posted to a
  hosting service, is still a claim to verify against the artifact.

## A card parked in `blocked` (nobody will retry it)

A long `blocked` (hours to days) is usually **not** "waiting for the owner": the worker crashed once,
and nothing ever dispatched it again. The dispatcher counts against `kanban.failure_limit`, gives up, and
then neither retries nor alerts — `show` prints only a `Task has been blocked for NNNh` warning.

- **Resolve the board before touching the id.** The kanban CLI serves several boards and a command
  without `--board` acts on the **current** board: a card living elsewhere answers `no such task: t_xxx`,
  which reads like a missing card. `hermes kanban boards` marks the current one with `●`; pass
  `--board <slug>` on every later `show` / `list` / `unblock`.
- **Read the root cause out of the run history** (read-only sqlite):
  `~/.hermes/kanban.db` → `task_runs` (`id,task_id,profile,status,started_at,outcome`). Last run
  `crashed`, no run after it, large `age_hours` = this shape. The usual crash text is a session-save
  failure (disk full, or the session DB held by another writer) — so check `df -h /` before re-arming.
- **Recovery is `unblock` plus proof it actually dispatched.** `hermes kanban --board <slug> unblock
  <id>` only moves the card back to `ready`; with `kanban.dispatch_in_gateway: true` the gateway itself
  dispatches every `dispatch_interval_seconds`, so within a minute `list` must show `running` and
  `task_runs` must gain a row — those two are the verification, never `unblock`'s return value. Do **not**
  start `hermes kanban daemon` while `dispatch_in_gateway` is true: two dispatchers compete for one board.
- **Check resources before unblocking a batch.** A batch that crashed together usually crashed for a
  shared reason (disk, memory, gateway); unblocking replays the attempt that died. Fix the cause first.
- **Read the card body before unblocking it.** Unblocking starts the action written on the card, and some
  of those are destructive (deleting data, cleanup, publishing, outbound delivery). If the body's scope is
  no longer what the owner authorized, `block` it again and ask separately instead of re-arming it.

## Output-file traps

- **Block-buffered one-shots write only at exit.** `pi -p` and `hermes … -Q` print nothing until the lane
  ends, so an output file still holding just your own header after ten minutes proves nothing: a review
  lane can look empty for its whole run and then land a full report. Confirm with probes 2/5, then read the
  file once the pid is gone.
- **`-Q` logs its failure, not its progress.** A log containing only an error plus a `session_id` is that
  unit's failure signature; an empty log is not health.
- **Parse the event stream in Python, never `wc -l` or `tail` it.** Per-line `json.loads`, count
  `tool_execution_start` per `toolName`, print only the tail of the last `partialResult`. In a truncated or
  ring-buffered window most physical lines do not parse, and one `tail` returns hundreds of KB (every
  sub-agent's prompt) for no signal.
- **A `pid` field is only reliable at finalize.** While in flight, a structured state file holds little
  beyond `model`; take the pid from the launcher's own argv
  (`ps -eo pid,ppid,args | grep '<run-name>'` — adapter and agent child both carry the name).
- **Ended runs** leave a `finalized` marker, `exit.code`, and a `runner.log` line
  `[finalize] <name> state=done exit=0 dur=… tools=… cost=…`. `exit=0` means the process ended, not that the
  stage produced results — read `answer.md` for trailing wait language before calling the phase done.

## Reporting

1. Verdict per lane on the first line: running / waiting on X / done / dead. Nothing is hung unless a probe
   says so.
2. The probe values with both samples and the interval, path by path, plus what each finished lane actually
   produced (artifact path + exit code).
3. Agent cards/threads are written per thread: check the task dir's own `status.md` before assuming the
   thread's label names the work — a done task with nothing running is a valid, complete answer.
