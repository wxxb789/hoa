# Paused conversations: "my threads stopped answering"

Owner reports several threads (or DMs) with work in progress went quiet. Discord still shows the
message, the bot posted at most one line and then nothing. The line is the diagnosis:

> ⏸️ This conversation is paused: a previous turn did not finish when Hermes restarted, and only you
> know whether to send it again. Your message is saved. Send /discard to drop the lost turn and continue
> (it is not re-run), or /reset to start a fresh conversation.

## Mechanism

1. The gateway process died **uncleanly** mid-turn (SIGKILL by systemd-oomd, a crash, or a kill issued
   by a child process). No exit path ran.
2. Turns that were in flight are fenced `unknown` in `session_admissions` — Hermes cannot know whether
   they executed, and replaying a half-run turn is worse than dropping it.
3. The conversation is **paused**: new inbound messages are admitted and saved, then left `queued`.
   Only the first message of a pause episode gets the notice; later ones are accepted silently, which is
   why it looks like the bot simply ignores the thread.

This is deliberate state, not a stuck lock. Do not "fix" it by deleting rows or by replaying the turn.

## Find exactly which conversations are paused

```bash
python3 - <<'PY'
import sqlite3, pathlib
for db in [pathlib.Path.home()/'.hermes/state.db', *sorted((pathlib.Path.home()/'.hermes/profiles').glob('*/state.db'))]:
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rows = con.execute('''select a.target_session_id, a.status, a.outcome, a.generation,
                                 s.chat_id, s.chat_type, s.title, s.last_activity_at
                          from session_admissions a left join sessions s on s.id=a.target_session_id
                          where a.status in ('unknown','queued','started')
                          order by a.seq desc''').fetchall()
    if rows:
        print(db.parent.name)
        for r in rows: print('  ', r)
    con.close()
PY
```

- `status='unknown'` = the lost turn; `status='queued'` = messages waiting behind it.
- Scan **every profile's** `state.db`. A pause only exists in the profile that owned the conversation;
  checking the root store alone misses specialist bots.
- `sessions.handoff_state` is null in this scenario — do not look there. `session_turn_leases` rows whose
  holder string carries a pid other than the current `MainPID` are the same event seen from the other
  side (a lease held by the dead process).

## Recover

Per conversation, in that chat:

- `/discard` — drops the lost turn (it is not re-run) and lets the queued messages run.
- `/reset` — starts a fresh session; the lost turn and its followers stay on the old one.

From the CLI (non-interactive, same effect as `/discard`):

```bash
hermes sessions discard <session-id-or-title> --yes            # every unknown admission in it
hermes sessions discard <session-id> --admission <id> --yes    # one specific admission
```

**Check the queued payload before releasing.** Discarding resumes work that was already typed — if the
thread was driving a long autonomous job, releasing it starts that job. Ask the owner when the release
would kick off heavy or irreversible work; otherwise just do it and report which session ids you cleared.

## Why it died — check before blaming the model

```bash
grep -n 'exited UNCLEANLY' ~/.hermes/logs/gateway.log | tail -3
journalctl --since '<t-10min>' --until '<t+2min>' --no-pager | grep -iE 'oomd|Killed'
```

The gateway writes `Previous gateway life (pid=…, started_at=…) exited UNCLEANLY (no exit path ran —
SIGKILL / OOM / VM death, or a process kill issued by the agent…)`. Cross-check the same minute in the
journal: `systemd-oomd: Killed … due to memory pressure for /user.slice/user-1000.slice being 85.03% >
80.00% for > 30s with reclaim activity` is a memory kill, `Consumed … CPU time` alone just means the
unit stopped.

## The silent variant: a turn killed by a *clean* restart

Not every lost turn posts the ⏸️ notice. A restart that lands while a turn is running — including one you
never scheduled, so check `ActiveEnterTimestamp` against your own write times — fences that turn
`unknown_execution`; startup logs `Native session startup recovery <session> … unknown_execution` and the
session later reads `Session … paused: unknown_execution`. What the owner sees is **silence**: the tool
calls ran and their artifacts are on disk, but the closing reply was never composed, so nothing was sent.

The thread is usually not stuck — the next inbound message repairs the transcript (`Repaired N
message-alternation violation(s) while restoring session …`) and runs normally, so never prescribe
`/discard` from the `paused` line alone, and never report "the conversation is frozen" without checking
whether the following turn actually ran. What is genuinely lost is the report, and only you can re-send it.

### Delivery forensics: what did the owner actually receive?

Agent-log tool lines prove the work, not the delivery. The delivered record is the session's own message
list plus the adapter's send lines:

```bash
python3 - <<'PY'
import pathlib, sqlite3, datetime
con = sqlite3.connect('file:' + str(pathlib.Path.home()/'.hermes/state.db') + '?mode=ro', uri=True)
for role, ts, n, body in con.execute(
        "select role, timestamp, length(content), substr(replace(content,char(10),' | '),1,200) "
        "from messages where session_id=? and role in ('user','assistant') "
        "and length(coalesce(content,''))>0 order by id", ('<session_id>',)):
    print(role, datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S'), n, body[:120])
PY

grep -n 'Sending response' ~/.hermes/logs/gateway.log | grep <chat_id>   # what went out, and how long
python3 -c "import json;d=json.load(open('$HOME/.hermes/gateway.pid'));print(d['start_time'])"
grep -n -E 'startup recovery|paused:' ~/.hermes/logs/gateway.log
grep -n '<session_id>' ~/.hermes/logs/agent.log                          # turns, api calls, recoveries
```

A gap in the assistant rows spanning the restart is the verdict: no assistant message between your last
tool call and the owner's next message means the report never existed, and re-asking cannot fix it. Re-send
the summary — and re-check every gate claim you made on that timeline ("no approval was requested", "this
still needs a restart") against the same clock, because a mid-turn restart also invalidates the assumptions
you formed before it.

## Batch repair: threads whose title never changed

The second signature of a killed turn, and the easier one to see from outside: the thread still carries
the raw URL or the gateway's placeholder name (`Analyze X post by …`) written at auto-thread creation,
because renaming the thread is the *last* step of the turn. One dead turn per thread, all inside the same
minute, is a fleet event — not a queue, and not "we are still working through them".

Cross-reference the platform's thread list against session rows (read-only, **every** profile's
`state.db`) and sort each thread into exactly one class before touching anything:

| Thread name | Session row | Class | Action |
|---|---|---|---|
| placeholder / raw URL | exists, `last_activity_at` old | **hung mid-turn** | resume |
| any | exists, activity within minutes | in flight | skip — a second driver double-runs it |
| any | **no row at all** | never ingested (rejected by the admission cap, or killed before the session was created) | rebuild from scratch |

Resume one unit, detached so it outlives the turn that launched it:

```bash
hermes sessions discard <sid> --yes                                   # clear a paused/unknown admission first, or the resume just queues behind it
hermes -p <profile> chat --resume <sid> --query-file <unit-prompt.md> --oneshot -Q > <log> 2>&1
```

The unit prompt must (a) finish the work the dead turn was doing, (b) set the final thread title, and
(c) make its final answer *be* the report — a resumed session keeps its delivery binding, so the gateway
posts that answer into the thread itself, and an extra explicit `hermes send` delivers everything twice.
Read the thread name back over REST instead of trusting the prompt: "the last step never ran" is exactly
the failure being repaired.

Rebuild (no session row): nothing to resume, so the unit starts a fresh session in that thread — hand it
the source material and require it to both do the work and name the thread.

Lane discipline — the point is that it runs unattended over dozens of units:

- Live in a **persistent** directory (`~/claw/tools/<area>/…` plus its log dir). A lane kept under
  `~/.hermes/cache/scratch/` is deleted by the idle prune partway through the job.
- **Classify from the live sources every pass** (platform REST + session store), never from a snapshot a
  previous run wrote: a frozen `classified.json` keeps re-selecting units that are already done and looks
  exactly like a queue that never drains.
- **Ledger** each unit (attempts, rc, delivered) in a JSON state file with an attempts cap per unit — the
  state file, not the log, is what makes a re-run idempotent. **A resume's exit code is not the unit's
  verdict.** The CLI prints `Gateway disconnected; turn outcome is unknown` and exits non-zero whenever the
  adapter drops the socket mid-turn, while the gateway finishes that turn and posts the answer into the
  thread anyway — its `Sending response (… chars) to <thread>` line is that delivery. A lane keyed on `rc`
  re-queues units that already landed and re-runs each of them every pass; classify a unit done when the
  thread holds its closeout report, and fall back to the CLI's rc only when it does not.
- **One malformed unit must not be able to end the lane.** A unit with no session row (`sid = None`) taken
  straight into argv kills the driver at command construction (`os.fork_exec` raising `TypeError`), and the
  whole batch dies at entry — every later unit never runs, while the lane still *looks* busy because the
  traceback sits at the end of the log, after the last unit that did run. Validate the unit's session id
  before building the command (log it, mark the unit skipped, return a sentinel), wrap each unit in
  `try/except`, and report lane health as the ledger's `done/total`, never from the tail of the lane log.
- **A running lane owns its state file.** The driver rewrites the whole ledger from its in-memory copy
  after each unit, so a hand-edit (marking a unit done, dropping a bad row) is silently reverted at the
  next unit boundary. Stop the lane, edit, relaunch — or scope the change to the next launch and say so.
- **One lane at a time**: `fcntl.flock` on a lock file inside the lane, plus a liveness guard in whatever
  launches it (a lane process started from an older revision holds no lock of its own).
- `--limit` + `--concurrency`, and a `--dry-run` that prints both the unit list and the command it would
  run. **Never smoke-test a lane script in the foreground**: the "test" starts real work over the real
  queue, and when the shell call times out the lane is killed mid-unit. `--dry-run` first, always.
- A **`no_agent` cron janitor** (every 15 min) is the queue for the units no lane picked up: thin launcher
  under `~/.hermes/scripts/`, first act a liveness check on any running lane (`pgrep -f '<lane argv>'`),
  empty stdout when there is nothing to do, ≤6 lines when it acted, delivered to the ops channel.
- Verify with the pending count (units still classified and unclaimed), not with "the lane is running".

## Pitfalls

- **"再问我一遍 / you never told me" is a delivery claim, not a request to repeat the question.** Read the
  delivered message list (above) before re-asking: repeating an ask the owner never received buries the
  real fault — a killed turn — under a fresh round of prompts, and it reads as if the agent ignores them.
- **`ManagedOOMPreference=omit` does not reliably protect the gateway.** Even with the property set on
  the unit and `user.oomd_omit=1` present on the cgroup, oomd can still pick it when the trigger is an
  ancestor slice's pressure action. Verify what actually got killed in the journal instead of trusting
  the drop-in, and report the mechanism to the owner rather than "the config should have prevented it".
- **The memory hog is usually a delegated worker, not the gateway.** `hermes-worker-*.scope` (OMP/agent
  subprocesses) can sit at high memory-pressure while the gateway is merely the second largest cgroup.
  The effective lever is capping worker memory (`MemoryMax` on worker scopes) so the worker dies first,
  not tuning the gateway.
- **Do not diagnose from Discord thread state.** Paused threads stay active and unarchived; only the
  transcript shows the problem. Fetch the last few messages of each thread and look at who spoke last
  (a user message with no bot reply behind it is the signature).
- **Do not offer `/reset` first.** It discards the whole context of a work conversation; `/discard` keeps
  it and only drops the unfinished turn.
- **Report the count, not a vibe.** "Two conversations paused in default, ids …, one queued message each"
  is actionable; "some threads are stuck" sends the owner hunting.
