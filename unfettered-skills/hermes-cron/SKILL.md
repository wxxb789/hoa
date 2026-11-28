---
name: hermes-cron
version: 2.0.0
description: "Use when creating, auditing, or debugging Hermes cron jobs."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [hermes, cron, watchdog, delivery, scheduling, automation]
---

# Hermes Cron

Create, audit, and repair scheduled jobs — including watchdogs that must stay silent when healthy.

## When to Use

| You hear / see | Do |
|---|---|
| "加一个每天/每周跑的任务"、routine、提醒 | create (rules below) |
| "定时任务还正常吗"、"为什么没收到推送" | health audit |
| "cron 太多 / 有重复吗 / 重构一下"、dashboard 太吵 | redundancy audit → `references/cron-health-audit.md` |
| watchdog 太吵 / 太安静 / 阈值不对 | `references/cron-internals.md` |
| 推送落到错的 chat、`deliver` 报错 | `references/delivery-routing.md` |
| `Restart-safe cron worker dispatch failed` | `references/cron-internals.md` → toolchain shim |
| `last_status: ok` 但没收到消息 | `last_delivery_error`, `hermes cron doctor` |

**Not for**: messaging-channel defaults (`*_HOME_CHANNEL`) → `hermes-gateway`.

## Rules

1. **`script` is a bare filename** relative to `~/.hermes/scripts/`; absolute and `~` paths are rejected.
   When the job lives in a secondary profile, that profile's own `scripts/` is searched **first** — copy
   the script there, or the create fails `Script file not found: …/profiles/<p>/scripts/<f>`.
   **The containment check runs on the RESOLVED path, so `ln -s` is not a way to reuse a tool that lives
   elsewhere**: a link whose target sits outside that scripts dir is refused with
   `Failed to create job: Script path escapes the scripts directory via traversal: '<name>'` — symlink
   only within the same directory. To run logic that legitimately belongs to a project
   (`~/claw/tools/<tool>/…`), drop a **thin launcher** in `~/.hermes/scripts/`: a real file that
   `subprocess.run`s the tool with fixed args, forwards child stdout+stderr, and echoes its exit code
   (copy `templates/script-launcher.py`). Keep the logic in one place — the launcher owns paths and
   argv, nothing else. Two traps while writing it: author it at its **real** path (a file writer resolves
   a symlinked destination to its target and refuses the overwrite as a stale write — `rm` the link
   first, then write), and self-test the launcher directly before wiring the job, because `--script`
   resolves `.py` by extension onto the managed venv interpreter (rule 24), not onto the shebang.
   CLI shape: the prompt is a **positional** argument (`hermes cron create "<sched>" "<prompt>" --name …`);
   `--prompt` exists only on `cron edit`, and passing it to `create` errors `unrecognized arguments`.
2. **`no_agent` = stdout verbatim; empty stdout sends nothing.** Healthy checks print nothing — including
   dependency/setup diagnostics like `psutil import failed`. `/proc` is the Linux fallback for RSS.
   For a checker that can keep finding the **same** issue, persist a findings hash
   (`~/.hermes/cache/<name>-state.json`) and print only when the set changes; a permanent finding that
   re-alerts every run trains the owner to ignore the channel. `--verbose` should still dump everything.
   **A silent-by-design job still needs an alarm, or its failures are journal-only.** With `deliver: local`
   (or empty stdout) and no failure target set, a crash is written to `cron/output/<id>/` and reaches
   nobody. Set the failure target (`failure_deliver`) and confirm it — together with `deliver`,
   `no_agent`, `script` and `timezone` — by reading the job's own record back out of `jobs.json`:
   `cron list` prints a subset of the definition, and the field your create/edit never mentioned is the
   one that costs you (rules 4, 32).
3. **Agent-run jobs must be self-contained**: fresh session; prior context exists only through explicitly
   configured attachment/continuity. Supply evidence paths and output rules even when continuity is on;
   scheduled runs cannot resolve missing requirements interactively. Verify the writer's persisted context
   representation (`context_from` containing `self` on the current schema), not a request-only boolean.
   The final response *is* the delivery; do not send a second message. Silence is a valid monitor result.
4. **`deliver='origin'` without a captured origin** falls back to the home channel; with no home
   channel it only saves to `cron/output/<id>/` while the job still reports `ok` (creation prints a
   local-only notice; after the upstream fix the status reads `delivery_not_configured`). Prefer
   explicit targets, and check `last_output` when an expected message never arrives.
   **`origin` is session-scoped, so a recurring job that ASKS something there is a dead letter.**
   Deliver into the session that created it and the question lands in a room nobody is watching once that
   session goes idle: the prompt sits unread until it expires, no error is raised, the job reports `ok`,
   and the only trace is a `timed_out` clarify record nobody looks at. A one-shot the owner is actively
   driving may use `origin`; anything owner-facing that waits for an answer — a decision, an approval,
   a question — delivers to a channel (that profile's home/DM, or the dashboard), never to `origin`.
5. **Home channel is per job-owning profile** — set `<PLATFORM>_HOME_CHANNEL` in that profile's `.env`,
   not just root. A missing target raises `UnscopedSecretError` while `last_status` stays `ok`.
6. **Routing convention (this install)**: system/ops jobs → `discord:${HERMES_DASHBOARD_CHANNEL_ID}` (`#dashboard`,
   one-way, configured in `~/.hermes/.env`); personal reminders / briefs / career → `discord` (DM). Canonical: `~/claw/AGENTS.md`.
7. **`hermes cron run <id>` proves the payload, not the worker path.** The restart-safe worker is proven
   by the job's own scheduled runs; a broken toolchain env fails *every* script job at once.
8. **Never schedule `hermes update` as a cron job** — the gateway scheduler must not replace and restart
   its own runtime.
9. **Owner-facing reminders obey the same silence rule as watchdogs.** Surface only when the owner must
   decide something, a threshold is crossed, or the state changed since the last run; fold everything
   else into one daily/weekly digest. A habit nudge (water, posture, stand up) is not a job of its own —
   attach one line of it to a single work-block message that also carries the next concrete action.
   Keep one routine per week that always fires (the review); everything else earns its interrupt.
   **An explicit owner demand is itself the justification.** "一定要提醒我" about a dated commitment
   outranks the earns-its-interrupt test — build ONE job carrying the checkpoints (a single-day
   schedule with several times, see rule 14) whose script names the remaining work and one reply
   format, not a chain of separate nudge jobs.
   **Check a checkpoint's own state before re-issuing it.** A chat turn can arrive hours after the last
   one: run `date` and `hermes cron runs <id>` (the delivered text is the job's own stdout under
   `cron/output/<id>/<timestamp>.md`) before restating today's list. The checkpoint may already have fired
   and the "pending" items may already be finished by another lane; re-narrating a finished plan, or
   talking about a reminder whose `Repeat: N/N` is spent, reads as a channel that is not watching.
10. **Replace routines without clobbering scheduler state.** Capture a private full-file backup for
    evidence, then stage/test replacement coverage, switch the approved jobs, verify readback, and remove
    approved old ids. Avoid dual-run side effects; retain retired scripts for rollback. Roll back only the
    affected definitions through the supported writer/lock or canonical generator, preserving unrelated
    jobs and live counters/claims/progress — never overwrite live `jobs.json` with a stale snapshot.
    Sweep retired names everywhere a schedule can be re-read from: skills `references/` (the ops
    skill's install doc holds a cron table — re-derive it from live `jobs.json`, never eyeball it),
    `LOCAL_OVERRIDES.md` (history entries get a dated superseded note appended, never rewritten), and
    `AGENTS.md` (approval-gated: a timed-out prompt is not consent — leave the edit pending, do not
    bypass through terminal).
    The `script` field carries a bare filename only — a replacement payload needing fixed CLI args
    (frozen policy paths, state files, timeouts) gets a thin wrapper script under `~/.hermes/scripts/`
    that owns those paths; test the wrapper directly (exit code + silence semantics) before switching
    the job, because the scheduled path and your module-level test differ by exactly that plumbing.
    **Restoring a dropped job goes through the CLI, which exposes only a subset of the record.**
    `cron create`/`edit` on this build take no `--enabled-toolsets`, so a faithful-looking recreate
    silently loses toolset scoping — and any other field without a flag. Build the replacement from the
    archived record, read it back, diff field by field, and state every delta instead of calling the
    restore exact. Any checker that requires the job by name (`required_jobs` in
    `post-update-check.py`) is edited in the same change as the re-add or the removal, or the next health
    run reports red for a decision the owner already made.
11. **`no_agent` scripts exit 0 whenever stdout is the alert.** A non-zero exit adds a cron failure
    incident plus a duplicate failure notice on top of the message you already printed. Reserve
    non-zero for a broken harness (crash), never for "found drift". This holds for aggregators too:
    the wrapper that prints a multi-check report must still exit 0.
12. **Frequency follows fault cost, not curiosity.** Ask "how long can this be broken before it hurts?" —
    resource spikes need minutes, invariants and staleness need a day, cleanup sweeps need a night.
    A check whose finding is harmless for 24h at a 15-minute interval is pure scheduler load.
    **Retention and cadence are one decision, not two.** A retention window is only as short as the
    interval that enforces it: a 3-day retention on a weekly sweep is a 3-to-10-day retention, so quote
    the *effective* window and never the configured one. When the owner's complaint is a resource filling
    faster than expected, tighten the interval instead of adding a second job — a sweep that stays silent
    below its report threshold costs no attention, which is what makes the extra runs free. Then pay the
    bookkeeping in the same pass, because a schedule change invalidates every copy of the job's identity:
    rename the job when its interval changes (`weekly disk reclaim` firing daily is a name the next audit
    reads as coverage that no longer exists), and re-derive the places that quote the name/schedule — the
    ops skill's cron sheet via its generator (never by hand) and the generated live inventory — instead of
    editing those tables (rules 2, 10).
13. **A threshold below the healthy steady state is a permanent alarm; alert on transitions.**
    Measure the steady value (and its range) before setting a threshold — a limit under normal usage is
    true forever. A cooldown does not bound the rate (measured: 2519 MB against an 1800 MB limit with a
    30-minute cooldown → one alert every 33 minutes, ~43/day). Keep `ok / warn / critical` in a state
    file, print only on a level edge plus one recovery, and re-remind critical on a long timer (6h).
    `--verbose` must always print the current picture. Add hysteresis: commit a new level only after N
    consecutive samples agree (N=2), except a jump to critical. One-sample dips on a fluctuating box
    otherwise produce 6–9 messages a night even though every message is technically true.
14. **`repeat.times` is a silent stop — in both directions.** A monthly job created with `--repeat 12`
    ends after twelve fires with `state=scheduled` and no error; recurring jobs must use unlimited
    (`times: null`). The mirror case bites a same-day reminder: one schedule expression that matches
    several times (`0 14,17 13 11 *`) counts **one fire per match**, so `--repeat 1` delivers the 14:00
    check-in and silently never sends the 17:00 one — set the repeat count to the number of intended
    fires and read `Repeat: 0/N` back from `cron list` immediately after create. Check it in the same
    pass that checks `enabled`.
15. **Timezone: state it at create time where the build allows it, and verify from the echo either way.**
    This build takes `--timezone <Zone>` and prints it back (`Timezone: Asia/Shanghai (schedule runs on
    this zone's wall clock)`); builds without the flag interpreted the schedule in the owning profile's
    `config.timezone`. Do not assume — a bare `15 9 * * *` on a differently configured profile fires at
    the wrong hour, so pass the zone when the flag exists and confirm it in the create output / `cron list`,
    not from the flag you believe you passed.
16. **A `--script` job printing `{"wakeAgent": false}` skips the agent turn entirely** — the gate output
    is still saved under `cron/output/<id>/`, but no model call happens. Use it for high-frequency
    monitors so an idle check costs nothing; every 3 hours is then affordable. The same mechanism turns a
    clock-driven job into a **condition-driven** one: the gate reads the watched artifact and prints either
    silence or a compact digest, so the agent wakes on the condition. Four things make such a gate
    trustworthy. (a) **Both branches exit 0** — a non-zero exit is a failure incident, not an alert.
    (b) **The branch order is explicit and written down**: absent artifact → silent, unchanged artifact
    inside the dedupe window → silent, and a check of the **liveness of the unit that owns the work** →
    silent while it runs (a live owner means the record was already consumed, so re-alerting on it is a
    stale wake). (c) **Every input comes from env with the live value as the default** (artifact path,
    state file, unit name) so each branch is provable against a fixture: with the liveness probe pointed at
    the really-running unit, the re-alert branch is unreachable and a fixture test that "fails" there is
    testing the wrong thing. (d) **Assert on stdout text, not on the exit code** — both branches exit 0 by
    design. Prove the silent branch through the runtime instead of by hand: after `hermes cron run <id>`,
    the job's own `cron/output/<id>/<timestamp>.md` records
    `Script gate returned wakeAgent=false — agent skipped`, which is the evidence that an idle tick costs no
    model call. Pair the gate with `deliver: local` when the woken turn's only audience is one work thread:
    the job then never posts noise, and the agent decides whether anything is owner-facing.
17. **`hermes cron remove <id>`** is the removal command (not `delete`). When reconciling generated job
    sets, remove stale `[bot:<profile>]` ids instead of leaving them paused — a paused orphan still
    appears in audits as coverage that does not exist.
18. **Reconcile frozen audit coverage with live scheduler state.** Finish with a backup-vs-live diff;
    keep frozen review totals, current totals and projected endpoints separate. Classify concurrent
    additions by exact owning home/id, independent authorization and verified payload; fail closed on
    unknown additions, removals or definition changes rather than ignoring all drift. Preserve authorized
    additions and recompute projections from the current fleet. Never state a live count without readback.
    Classify `repeat.completed` and `last_dispatch` as scheduler bookkeeping only after inspecting their
    writer and exact changes; preserve `repeat.times` and all unclassified fields in the definition diff.
    For the baseline-vs-live diff itself, exclude the stable bookkeeping fields up front
    (`last_run_at`, `next_run_at`, `last_status`, `last_error`, `last_failure`, `failure_streak`,
    `last_dispatch`, `last_delivery_error`, `last_delivery_unverified`, `canonical_completions`,
    `state`, `paused_at`, `paused_reason`, `fire_claim`) — a naive whole-record diff reports false drift
    on every job that has run since the baseline and drowns the one real change you are hunting.
19. **A bot's routines belong in that bot's own `profiles/<p>/cron/jobs.json`** — create them with
    `hermes -p <p> cron create …` so the per-profile ticker owns the schedule, the home channel and the
    output dir. The `[bot:<name>]` name prefix is ownership *metadata* for the roster view only:
    `hermes cron edit <id> --name` relabels a job without moving it, so use it to attribute an existing
    job, never to fake a migration. **Exception:** install-level maintenance scripts resolve paths from
    their own `HERMES_HOME`/`scripts/`, so moving such a job into another profile yields `script not
    found` or the wrong home — leave them on the profile that runs them and attribute by prefix instead.

20. **Machine-check ownership, don't eyeball it.** A ledger script that walks every `cron/jobs.json`
    (root + `profiles/*`) catches what `cron list` cannot: `[bot:X]` naming a profile that no longer
    exists, an **agent-mode** job sitting in another profile's store (it runs with that profile's SOUL and
    memory — silently the wrong identity), a missing script, duplicate names, and prefix-less jobs. Treat
    "agent-mode job outside its owner store" as an error and "script-mode job outside its store" as a note:
    install-level scripts legitimately stay on the scheduler that owns their home (rule 19). Wire the
    checker into the existing daily drift job instead of adding another schedule.
    **Duplicate duty does not need duplicate names to double-deliver.** The same duty re-created under a
    different name in another store (one job carrying the seed script, one carrying the prompt, same
    `schedule_display`) fires twice and both report `ok` — compare schedules across stores, not just job
    names, before declaring a routine unique, and when the owner asks which copy to keep, read both
    records' `enabled` + `last_run` rather than assuming the newer one replaced the older.

21. **A plugin-backed routine on N profiles needs five pieces, not one job**: plugin dir in the profile,
    `plugins.enabled` entry, gate script copied into `profiles/<p>/scripts/`, the job's
    `agent-plugin-<name>-<hash>:<skill>` reference, and `enabled_toolsets` (not settable from
    `cron create` — patch `jobs.json`). Stagger the fleet and finish before the daily auto-update
    restart, or the update aborts a run mid-flight. Full recipe and the free-when-idle wake gate:
    `references/fleet-routine-wiring.md`.

22. **Pin a job's model on the job itself; there is no per-job fallback.** A job's `model`, `provider` and
    `reasoning_effort` are read straight from the job record, so setting them is what makes a routine
    immune to a later switch of the bot's main model — `cron edit --pin` does not persist a `pinned`
    field on this build, and a pin taken at create time can round-trip to nothing. `fallback_providers`
    in `config.yaml` is the ONLY fallback mechanism and it is global to the profile: putting a cheap
    model there to protect one nightly job silently degrades every interactive turn of that bot once the
    primary errors. Say that trade aloud before using it, and verify by reading the job back
    (`model` / `provider` / `reasoning_effort` columns in `jobs.json`), not by the edit's exit code.

23. **When one routine feeds another, schedule order and the handoff are part of the contract.**
    A producer scheduled after its consumer is invisible: a dispatch at 08:40 feeding an 08:30 brief
    never appears, and nothing errors — both jobs report success and the owner simply never sees the
    item. Order producer → consumer with real slack, and hand off through a FILE with one writer and
    one reader (a runtime-state path or the owner's inbox), never by expecting the reader to scan the
    producer's chat. The consumer must treat a missing/empty file as "nothing today" so a silent
    producer is a no-op rather than a failure, and the producer must overwrite its handoff each run —
    appending leaves a resolved blocker resurfacing for days.

24. **A script job that shells out to an interpreter must pick it by capability, not by version or path.**
    "Newest `python-*` under the tools dir" selected an interpreter that lacked the dependency the job's
    first step imported, so the 04:00 run died with `ModuleNotFoundError` inside a helper the unit file
    never names. Probe each candidate (`<interp> -c "import <dep>"`, short timeout) in a documented
    preference order, and raise a named error listing every candidate tried — the failure then reads as a
    config problem instead of a mystery traceback in a scheduled run nobody watched.

    **Cron does not read the shebang, so fixing dependencies through it is a no-op.** `_script_argv`
    resolves `.py` by extension and runs it on the managed dependency venv's interpreter
    (`pm.environments.project_python`, falling back to `sys.executable` when no managed store exists);
    only `.sh`/`.bash` go to bash. That is why a job importing a dependency runs fine while the very
    same file dies with `ModuleNotFoundError` when a human runs `python3 <script>.py` from a shell whose
    PATH leads with a bare version-manager python — and why editing the shebang changes neither side.
    When a script genuinely needs another runtime, set the job's `interpreter:` field (absolute or `~`
    Python, validated at run time; it receives none of the managed overlays). Treat both directions —
    "works under cron, fails by hand" and its mirror — as an interpreter-resolution question before
    touching the script.

25. **Register every finding's check id at load time; an unknown id kills the whole run.** A finding
    emitted with a check name the runner's registry did not know raised `KeyError`, so the job exited 2
    and the finding never reached its delivery target — the gate existed and still could not report.
    Test the negative path *through the runner* (inject one fault, expect exactly one delivered finding),
    not by calling the check function directly.

26. **A validity gate must not swallow its own cause.** `except Exception: raise ValueError('unsafe or
    malformed input: ' + path) from None` turned an intermittent file-specific failure into an
    unfalsifiable message — the same input validated fine on the next run and nothing recorded why the
    first attempt died. Keep a short stable prefix for greppability, append `type(exc).__name__` and the
    first ~160 chars, and add a bounded read retry when the input is a file another runtime may rewrite.

27. **A `no_agent` job's stdout IS the message — keep a render layer between machine output and delivery.**
    Machine payloads (JSONL findings, canonical JSON, `json.dumps(dict)`) must never be the delivered
    text: they are unreadable in chat and the owner stops reading the channel. Delivery text = status icon
    + one-line conclusion + 3 points (up to 5 when the information genuinely needs it — hard errors, several
    fault families in parallel) + one action or one evidence path; full payload goes to a file
    under `~/.hermes/logs/<area>/`. Brevity is traded against *decoration*, never against meaning: cut
    adjectives, boilerplate and repeated templates first; keep who/what/impact/the decision requested;
    truncate only the tail of a name and always keep the identifying head plus a count. If it will not
    compress without becoming ambiguous, let the message run longer inside the limit. Shared renderer: `~/.hermes/scripts/lib/zh_notify.py`
    (`compose(icon, headline, conclusion, points, action, detail)`); per-job wrappers
    (`hermes-health-notify.py`, `hermes-recovery-notify.py`) wrap the producer without changing its machine
    contract, so existing harness tests keep passing. Rules: clean run prints nothing, findings print a
    conclusion (never a data dump), and the wrapper always exits 0 because stdout already carries the alert.
    Verify a renderer by feeding it one REAL saved payload (old `cron/output/<id>/*.md`) and checking the
    character count collapses (measured: 77 KB of findings → 394 chars / 6 lines).

29. **A cross-profile handoff is created in the target's store, not by targeting its chat.** An agent-mode job
    runs in the home that OWNS it: `--deliver bot-chat:<profile>` only injects the finished run's output into
    that profile's Bot Chat **afterwards** (measured: the artifact below was written while the worker's
    `HERMES_HOME` was root, and the target profile's first log line was the inbound cron message two minutes
    later). So root-store + `bot-chat:<p>` makes TWO agents touch the same artifact — the owning profile does
    the work, then the target bot reacts to it. To hand work to another bot, create the job in that bot's own
    store (`hermes -p <p> cron create … --deliver bot-chat:self`) so its identity, memory and skills perform
    it; use `bot-chat:<p>` from elsewhere only to *notify* a bot, never to delegate an edit.

30. **A job whose `deliver` names one task thread is thread-scoped machinery — retire it when that
    thread closes.** A thread-local watcher (a conductor / stage / CI watcher that pings the work thread)
    has no consumer once the work item is done, and left enabled it keeps firing into a closed or
    archived thread forever. Sweep exhaustively *before* archiving: `cron list` prints `Deliver:` for the
    root store only, so parse `~/.hermes/cron/jobs.json` **and every `profiles/*/cron/jobs.json`** for the
    chat/thread id. Then `hermes cron remove <id>` — remove, not pause (rule 17; a paused orphan still
    reads as coverage in an audit). Keep rollback cheap: copy the full `jobs.json` plus the single job
    record aside, leave the script file in place, and confirm with `hermes cron doctor`. Two signals that
    such a job is already *dead* rather than merely idle: its state file is frozen at an old goal/stage
    (the watcher can never produce a new signature), and its liveness probe reads a **host-local** surface
    (`/proc`, a local `state.json`, a named tmux session) that a project moved to another machine can no
    longer satisfy. Do not keep it "just in case" — re-adding it is one command.
    A closed thread's leftovers are not only cron: sweep the same pass for the job's cache file under
    `~/.hermes/cache/` and any generated worktree snapshot directory the work item left in `~/repos/`.
    Who owns which leftover and in what order: skill `hermes-gateway`,
    `thread-and-forum-topology.md` → “关帖前”。

31. **A step queued to run later needs its own trigger, or it never starts.** A chain whose next step is
    launched by "the next turn" stalls silently the moment that turn never comes: the current run
    finishes, the queue is never re-read, and every poll still shows plausible state — indistinguishable
    from work in flight for hours. When you queue a step, write the queue to a file (per item: the path /
    worktree, the run slug, the stage, the next action, and who owns the irreversible action) so a later
    session resumes from disk, and attach a trigger in the same breath. Two triggers work with nobody
    watching: a one-shot job that reads the finished run's state and reports it into the work thread, or —
    for a chain of stages — a recurring agent job gated by a `monitor` script that prints only
    deterministic state (one line per run: `<slug>\t<state>`, never timestamps, durations or live
    counters), so the agent wakes on a transition and stays silent in between; bound it with `repeat: N`
    and sweep it when the chain ends (rules 17, 30). Before reporting a chain as in flight, answer both
    questions out loud: who starts the next step, and how will I learn the current one ended? If either
    answer is "the next turn", the chain is already broken.

32. **A queued job that dispatches work has to carry the authority, the abort conditions and its own write
    boundary.** When the owner pre-authorizes a staged plan ("按设计走" / "go with the design as written"),
    fold the next stage into the job that is already queued instead of waiting for the review he just
    waived — re-asking a question he answered reads as a channel that is not listening. Name three things
    in the prompt, in this order: (a) the authorization and what it covers, so the run does not stop at a
    gate the owner already removed; (b) the exact findings that mean **do not dispatch, report instead**
    (a failed measurement, coverage under a floor, a missing artifact) — an unattended agent given only the
    happy path either improvises past the blocker or reports success having done nothing; (c) what the job
    itself must not touch: it writes the prompt file and dispatches a detached run, and never edits,
    commits or pushes the target repo, which belongs to that run in its own worktree. Give the do-not-run
    branch its own exit ("report and end") and hand delivery one line the owner can act on. `cron edit`
    echoes back only Name/Schedule/Skills, so read `Deliver:` and `Repeat:` from `cron list` after editing
    a prompt — the field the edit did not mention is the one it can cost you.

33. **Read a job's prompt before queueing work to it, deciding anything about it, or feeding it an owner
    answer — `cron list` prints no prompt and `hermes cron show` does not exist.** The prompt lives in the
    job record in `~/.hermes/cron/jobs.json` (`prompt`, alongside `context_from` / `origins` /
    `enabled_toolsets`, which the CLI also cannot fully set — rule 10). It names the artifacts the job
    re-reads every tick (`先读 …`), the queue it advances, its own write boundary, and often its own
    self-retire instruction. **That first-read artifact is the write channel** for anything the job must
    honour on its next run: an instruction or an owner decision written only into the chat the job delivers
    to reaches it only if a human relays it, because agent-authored messages do not wake another session —
    so a conductor can report `ok` every tick for hours while still advancing its pre-decision queue.
    Reading the prompt is also how a thread-scoped conductor is checked: its work thread, its files and its
    retirement condition are all stated there, one line each.

34. **A scheduled unit whose failure is journal-only has no alarm, and a fail-closed gate can wedge it
    forever.** A `systemd --user` timer that refuses an artifact fails *identically* every run: four
    consecutive daily failures wrote one journal line each (`verify.sh FAILED — nothing committed`) and
    reached nobody while `is-failed` stayed true the whole time. Before calling a schedule healthy, name
    what reads its **last result** — a health-check family that covers that unit by name, or the job
    notifying its own failure (deduped, at most once per day per reason, carrying the offending paths and
    the review-queue location). Never leave a refusal to the journal alone. Two consequences follow:
    give the job a prune/repair step derived from the same declaration its gate reads, so one stray file
    cannot block every future run; and diagnose a stalled publisher with
    `journalctl --user -u <unit> --since <date>` plus the age of the remote ref
    (`git log <remote>/<branch> -1`) — a publisher that stopped delivering is refusing work, not a broken
    transport, and the repo's own mtimes say nothing.

35. **A watchdog's message text is a function of the artifact it reads — derive the label, and prove the
    branches without eating the alert.** When the message is assembled from a status record (a block file, a
    state file, a stage report), that record's freshness decides the alert: a hard-coded label keeps asserting
    a condition the record has already moved past, and after the record is corrected the notifier still quotes
    the old reading on every repeat window. Fix the artifact and the derived text in the same pass, reading the
    condition out of the record's own header (`^# Block — none`, a `Reason:` field, the first section) instead
    of out of your enum of states, and suppress the **process-died** branch while such a record exists and
    names the driver — an intentionally stopped unit with a written handover is indistinguishable from a crash
    to a liveness probe, and the owner receives a confident wrong conclusion. After patching the text, expect
    the next scheduled tick to deliver it: the dedupe state file (rule 2) holds the *last sent* message hash, so
    changed text re-alerts on its own. Which is also why the verdict must be proven by **importing the module
    and calling the alert function**, never by executing the script: a hand-run writes that state file as it
    prints, consuming the alert slot, so the real tick goes silent and the corrected text never reaches anyone
    —    you get silence where you meant to verify.

36. **Resuming a paused job is two steps in this order: land its guard, then enable it.** Where two
    automated drivers act on one resource — a recurring job and a long-running series driver both writing a
    repo, a branch, a queue file or a goal chain — the moment the pause lifts is the moment the overlap goes
    live, so the exclusion check belongs in the job that resumes: read the other driver's liveness and exit
    silently while it is active (rule 16b), and get that into the job's prompt or script *before* the job is
    enabled again. Count a **manual invocation of the same lane script** as one of those drivers: testing
    the launcher by hand starts a second lane over the same queue, and when the shell call times out that
    lane is killed mid-unit. Put the guard in the launcher (`pgrep -f '<lane argv>'`) rather than only
    inside the lane — a lane process started from an older revision carries no lock of its own, so an
    in-process flock cannot see it. A guard that exists only in the plan document, a chat decision or the operator's memory is
    not a guard — the job reads none of them, and the duplicate write afterwards surfaces as a mystery revert
    nobody can attribute.    **A guard that silences only when the other driver is live AND its record is unchanged is not the guard.**
    The conjunction gives back exactly the window it was written for: a live driver that has moved the record
    on (a new block, the next stage, a fresh signature) stops matching, so the lane wakes into a resource
    someone else is writing — the duplicate-writer case the comment above it claims to prevent, reached
    through the one state a running driver is most likely to be in. Condition the exclusion on the other
    driver's **liveness alone**; the record's content is no evidence about who is driving, and a driver that
    exits clears the condition itself on the next tick. Prove the liveness branch with the env-indirected
    unit name pointed at an *unrelated* active unit (any live `<x>.service`) for the silent case and at the
    real (stopped) driver for the wake case, and neutralise the gate's other suppressing knobs (dedupe
    window, peer-quiet seconds) through their own env vars — against the live unit alone the branch under
    test is unreachable, and a fixture that "fails" there is testing the wrong thing (rule 16c).
    Report the two steps separately (`guard landed`, `job enabled`), never "resumed"
    alone, and treat a resume request as incomplete until both are true.

37. **A recurring digest needs window-level idempotency; a findings-hash dedupe (rule 2) does not cover it.**
    A brief whose content is "everything since the last window" has no finding to hash, so a retry, a
    catch-up run after downtime, or a manual backfill delivers the same day twice. Persist the delivered
    window key (`<log-dir>/.last-posted` = local date, plus a `--force` flag for a deliberate re-post) and
    exit with **empty stdout** when the key already matches (empty stdout delivers nothing). Two
    consequences that bite in the same pass: a manual post must arm that marker itself, or the scheduled
    run double-delivers minutes later on day one; and write the marker only after the payload is assembled
    and only on the delivery path you are willing to have consumed — arming it before a delivery that then
    fails makes the day silently unretryable.
    **Correcting a delivered brief is a minimal edit, not a re-render.** Once the marker is armed, re-running
    the generator emits a *different* payload — a newer scoring window, items that arrived since — so the
    correction posts content the owner has never read while claiming to fix what he did. Patch only the
    broken lines (the delivered message or the stored payload) and leave the rest byte-identical, then read
    it back. If the fix genuinely changes what the brief says, it is a new post, not a correction: say so
    before sending.
    Flag set for a new channel of this kind: `--deliver <channel>`, `--failure-deliver` the ops channel (a
    broken brief must not look like a quiet day), `--no-wrap-response` so the message reads as
    channel-native content rather than a cron wrapper.
    **The header date is part of the payload: derive it in the brief's declared timezone, assert it against
    the intended date before sending, and fail closed (non-zero exit, nothing delivered) on mismatch** — a
    wrong-dated digest is worse than a missing one, and a host that drifted off the brief's zone shifts
    both the title and the window boundary silently. **And pick who posts**: a script that delivers itself
    (REST / `hermes send`) goes with the job's `deliver: local` and empty stdout — leaving the job's own
    delivery on posts a second copy of every brief — while a script that only prints keeps the job's
    `deliver`. Full recipe — including why a digest's deep links
    must have their ids persisted at **ingest** time and resolved from **live** sources at render time
    (a prebuilt index file that only a hand-run script refreshes is a stale cache: it resolves nothing for
    newer items and the brief loses its links with no error, so print the run's own resolution rate) — in
    `references/script-briefs.md`.

## Portfolio and redundancy audit

28. **A digest or top-N panel must dedupe by item identity, not by rendered text.** The same item
    rendered twice with a drifting counter ("stale 49 天" / "stale 56 天") is two different strings, so
    a ranker that dedupes strings shows one task twice, silently consumes two of the three slots, and
    hands the owner a wrong count of what he owes today. Carry a stable id (source file + task title)
    through ranking and collapse on it before truncating to N. When the panel is auto-generated and
    marked read-only, fix the generator and say so in one line — never hand-edit the generated file to
    make today look right, and never silently re-count "3 things" to the owner without checking
    distinctness first.
    **A panel with no candidates renders exactly like a healthy panel, so verify its inputs resolve —
    not just that the job ran.** Every bare-literal source path (goals dir, inbox file, board export) is
    a silent single point of failure: once the source moves, the generator still exits 0 and still prints
    a full list, because it degrades to generic placeholder text ("推进主线 Goal #1…") that reads like
    real work and hides the breakage for days while every run reports `ok`. Resolve each source as
    *env override → candidate path list (first that exists) → explicit fallback*, never a literal, and
    label the fallback inside the artifact so the degradation is visible to the next reader. Check
    candidate *content*, not only that the directory exists: an extractor filter written for checkboxes
    also matches source-tagged bullets (`- [Studio] …`) and drops every tagged item while leaving the
    untagged remainder, so the panel looks populated with its least important half. Audit by counting
    what each extractor returns per source and comparing against the raw file — before reporting the
    list to the owner as today's priorities. Before/after count recipe:
    `references/cases.md` → "Generated panel".

Optimize useful coverage, not job count. Reconstruct original intent before proposing patches or wrappers;
replace a bad design rather than preserving its rituals under one larger schedule. Full metrics recipe:
`references/cron-health-audit.md` → "Redundancy and noise audit".

1. **Inventory all scheduling entrances, then classify scope.** Read root and every valid profile's
   `cron/jobs.json`, user/system timers, system cron, and wrappers' nested tasks. Mark core, adjacent
   support, domain routine, or OS-only; enumeration is not permission to change excluded categories.
   Preserve raw records and derive a separate `store_profile` from the containing home — a nullable
   job `profile` field must not overwrite scheduler provenance. Persist batches and verify review keys
   match the inventory exactly, including excluded items.
2. **Write one intent row per in-scope job:** purpose, consumer, finding→action, tolerated outage,
   canonical source, dependencies, side effects, delivery contract, and actual execution evidence.
   Read implementations and call edges; similar names, audiences, or calendar windows do not establish
   redundant coverage. Never label a never-run or newly created job unnecessary from absent history.
3. **Measure costs separately.** Report current expected rates, fixed-window/since-creation executions,
   latency, failures, output/gate samples, delivery and attributable model usage. Reconcile schedule epochs
   before alleging excess runs; check normalized `scheduled_instant` identities before alleging duplicate
   dispatch. Keep receipt counts separate from executions and claim→start overhead separate from schedule
   lateness; validate metric field wiring before aggregating. Parse actual results, not prompt markers.
   Wall time is not CPU, local output is not an interruption, and fewer rare jobs is not measured savings.
   Label missing attribution and timer-versus-Hermes rate scope; recipe: `references/cron-health-audit.md`.
4. **Choose transformations by intent and fault domain.** Remove a redundant duty only after naming
   its substitute or explicitly accepted lost coverage. Consolidate shared failure modes/deadlines;
   preserve independent producer/verifier boundaries and scheduler-external liveness. Bound each
   aggregated step so one stalled checker cannot hide the others; avoid adding a checker pile merely
   to reduce the schedule count.
5. **Present 2–3 coherent designs before architecture edits.** Recommend one; list exact job/timer
   treatments (keep/merge/redesign/slow/retire), before→after coverage and rates, measured baseline
   versus projected gains, approval boundaries, and rollback units. Do not invent post-change savings.
   A decision form left unanswered — timed out, dismissed, or cancelled by a gateway restart — is not a
   decline: re-present the same numbered options verbatim next turn, then record the answers in a dated
   `owner-decisions-<date>.md` that names which earlier budget/cap/contract numbers it supersedes —
   later sessions re-derive gates from that file instead of re-litigating them. A multi-question form can
   return partly answered: act only on the answered questions, hold the rest, and never read a blank as
   approval.
6. **Implement only the selected scope.** Change generated schedules at their canonical definition,
   not only the host copy; stage replacement coverage before removing approved old ids. Retain scripts
   and pending approval data for rollback, then update live references.
7. **Verify the new contract, not just green status.** Check actual payload effects, scheduled worker
   runs, silence/delivery semantics, and backup-vs-live inventory drift; state what awaits its first
   scheduled run. An asynchronous audit is in progress until its artifacts and full coverage are accepted,
   not a completed redesign.

## Health audit

For a broken-job repair, isolate the failing payload/gate/worker/delivery path first; expand into portfolio
redesign only when requested or when evidence establishes a shared fault.

`hermes cron status` → `cron list --all` → `cron doctor` → `cron incidents` (resolved ≠ ongoing) →
`cron runs <id>` → inspect the matching output and payload implementation. Check payload side effects
before any manual trigger: `deliver: local` suppresses external delivery, not memory/sync/delete actions.
After an authorized repair, confirm the durable run, actual result/effects, and relevant delivery state;
compare `last_run_at` with the fix time. Silence or artifact size alone does not establish correctness.

`scripts/audit-cron-health.py` dumps every job (`--targets` adds delivery-target state).

## Consolidating a check family

Many single-purpose silent checks become fewer jobs when they share an audience and a cadence. Pattern:

- One `no_agent` aggregator script runs each check as a subprocess and prints ONE report; empty output
  when all are healthy.
- Keep periodic health read-only with respect to runtime configuration, plugins and user data; repairs
  require their own authorized action. Inspect helper IO before invoking it: `--check`, `--dry-run` and
  `--json` do not prove absence of mkdir/state writes/install/apply. Distinguish findings from repair events.
- Deduplicate stable finding identity and severity, not rendered dates, growing ages or counters; changing
  presentation must not re-alert the same unresolved fault. Keep renotify timing in one runner.
- Obtain the complete finding set through a verified read-only helper path, then let the runner own
  notification state. Nested one-shot dedupe can hide persistent findings; full-output flags alone do not
  guarantee read-only behavior.
- Keep independent cadences separate: a per-minute resource alarm and a daily invariant sweep do not
  belong in the same job.
- Sync wrappers already silent-on-success and dedupe failures 24h — aggregate them with a loop, do not
  rewrite their semantics. Fold "has not succeeded recently" into the daily job instead of a second
  periodic watchdog (if the scheduler dies, both die).
- **Scheduler liveness cannot be self-monitored.** Nothing inside cron can report that cron is dead.
  Watch `~/.hermes/cron/ticker_heartbeat` (epoch + pid) from **outside** the scheduler — a systemd user
  timer that messages only on a state change — or accept that a dead ticker is invisible.

## Proof

```bash
hermes cron status && hermes cron doctor
hermes cron runs <id>  # inspect source=builtin vs direct and final execution state
```

Read the matching `cron/output/<id>/<timestamp>.md` and the intended changed data. For an authorized
external-delivery test, use `references/cron-health-audit.md` → "Delivery self-test"; verify transport
receipt when available, or request owner confirmation. Never claim channel readback without that capability.

## References

- `references/cron-internals.md` — script-path rule, silent-watchdog contract, external liveness
  watchdog recipe (systemd timer + `hermes send`, no gateway required), restart-safe worker dying
  without the runtime env and its shim fix.
- `references/delivery-routing.md` — full audit procedure, target-resolution matrix, per-profile home
  channel, dashboard routing recipe.
- `references/script-briefs.md` — a recurring, 0-LLM brief/digest delivered to a chat channel: launcher
  entry point, idempotency marker, delivery flags, conclusion-first render shape, ids-persisted-at-ingest
  for deep links, readback verification, first-day channel hygiene.
- `templates/script-launcher.py` — copy-and-edit launcher for a `--script` job whose real logic must stay
  outside `~/.hermes/scripts/`.
- `references/cron-health-audit.md` — command reference and verification matrix; redundancy / noise audit
  queries (`executions.db`, non-silent ratio, orphan output dirs) and the merge recipe.
- `references/fleet-routine-wiring.md` — putting one plugin-backed routine (nightly consolidation, gate
  scripts, `wakeAgent: false`) on many profiles: the five pieces, staggering, per-profile cost model.
- `references/cases.md` — historical case: watchdog silent dependency fallback.
- `scripts/audit-cron-health.py` — runnable probe.
