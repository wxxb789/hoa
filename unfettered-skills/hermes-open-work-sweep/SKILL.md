---
name: hermes-open-work-sweep
description: Use when the owner asks what work is still outstanding.
version: "0.1.0"
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [work-management, productivity, gtd, backlog, audit]
    related_skills: [owner-decision-requests, hermes-kanban, hermes-cron]
  version: "0.1.0"
  areas: "work-management,productivity"
  targets: "runtime-agnostic"
  summary: "sweep every commitment surface, classify and rank the gaps, hand back one pick"
  summary_zh: "盘点承诺而未完成的事：扫承诺面 → 分类排序 → 结尾给一个可选的下一步"
  kind: "mechanism"
  consumes: "owner-question"
  produces: "gap-list, next-pick"
---

# Open work sweep

A plan, a board card, a `next:` line and a scheduled job are all promises. This is the pass that finds
which promises have quietly stopped being kept. The deliverable is a **ranked gap list with evidence
paths and one question at the end** — not a restatement of the owner's notes and not a new plan.

## When to Use

| You hear / see | Do |
|---|---|
| "还有什么本应该做但是还没做的" / "what is outstanding" / "what did we drop" | full sweep, §1 |
| a weekly reset, or the turn before proposing next week's plan | full sweep, then rank by what feeds a live goal (§3) |
| "why has X not moved" about one item | narrow sweep: that item's own surface plus the goal it feeds |
| a thread / board post / project is about to be closed: "what is left before we close this?" | closeout mode, §5 — partition every strand, then dispatch |
| "开始今天的 Top 3" / "start today's top N" | start mode, §6 — each item's agent-side work *for today* is verified before you claim to have started it |
| the owner wants the pending **questions** re-asked | not here — `owner-decision-requests` §5b |

**Not for**: deciding one question, executing the work the sweep finds, or grading a delivery
(`delegated-work-acceptance` for a handoff that came back "done").

## Procedure

### 1. Sweep the commitment surfaces (batch the reads — they are independent)

| Surface | Read | What a hit looks like |
|---|---|---|
| GTD panel + queues | `~/claw/gtd/today.md` (generated, read-only), `inbox.md`, `blocked-waiting.md`, `waiting_on_me.md` | open items; a queue entry still marked "awaiting approval" after the approval landed |
| Task board | `python3 ~/.hermes/scripts/discord-forum-post.py list`, then `read <thread_id>` for every card you will judge (mechanics → `references/discord-tasks-board.md`) | `review` = built, never accepted; `wip` = still open at face value — age it from `read`'s newest message, **not** from the listing's `last_message`, which returns the thread's archive-status change time, not a message time |
| The conversation in hand | `python3 ~/.hermes/scripts/discord-forum-post.py read <thread_id>` — read the **owner's** messages, not only the agent's | an owner message with nothing after it: a question never answered, or an authorization ("go ahead", "clean up X") never acted on. No card, cron job or queue tracks these, and the usual cause is the turn that received them dying mid-work |
| Scheduler + install health | `hermes cron list`, `hermes cron incidents`, newest `[ops] hermes health daily` output under `~/.hermes/cron/output/<id>/` | paused orphans; unresolved incidents; a health conclusion line naming drift that awaits a one-word answer |
| Declared cadences vs registered jobs | every job name an instruction file, a status doc or a helper's docstring claims is scheduled (grep the doc for the job name), then the full job list in `~/.hermes/cron/jobs.json` | a documented cadence with no job behind it = a promise kept by a doc only; also expired one-shot dates, sub-hourly task jobs, and paused jobs whose `last_run` is over a week old |
| Day's dispatch dirs | `ls -dt ~/claw/tasks/<date>/*/` then each `status.md` | a dir holding only `brief.md`/`prompt*.md` = dispatched, never delivered |
| Long-running driver state | `find ~/claw/tasks -maxdepth 4 \( -name 'BLOCKED.md' -o -name '*-state.json' \)` plus each series state file | a `BLOCKED.md` whose mtime is days old is a **claim**, not a stall: check the driver's own ledger/log for progress *after* that timestamp — a refusal is often followed by a successful retry of the same goal and then later goals. Only a ledger that stops mid-tranche is the finding |
| Delegated runs | `~/claw/tools/omp-run.sh status <slug>` (or the run's `state.json`) | `exit: null` + `ended_at: null` + `tmux_alive: false` = abandoned, not running |
| Goals and standing evidence lines | `<notes-vault>/gtd/goals/*.md` `next:` lines + mtimes; `<notes-vault>/<work-tag-a>/projects/*/weekly-*-log.md` and `evidence/inbox.md`; review/ledger mtimes under `garden/fin/` | a `next:` older than the week; an evidence log whose last entry is months old, or an inbox at zero with an old mtime — and note the daily panel's Top-N is **derived** from those `next:` lines, so closing an item means rewriting the line it was rendered from and regenerating, or the next render re-offers finished work |
| Where the work must land | `git status -sb` + `git diff --stat` in the skill/asset repos | finished work uncommitted on a branch = an unfinished landing |
| Repo truth vs. docs | the file a doc points at | a blocker list, AGENTS line or status header describing a state that no longer holds |

### 2. Classify every find — the owner acts differently on each class

1. **Blocked on one word from the owner** (an approval, a pick, a yes/no) — cheapest to close, put first.
2. **Stalled with nobody noticing** (dead delegated run, a capture line that stopped, an uncommitted
   landing — including a run whose own record says `done` while its answer names a backgrounded job it
   never collected) — most dangerous, because no job ever reported it.
3. **Standing debt** (externally blocked fetches, queued target-level approvals, a goal whose blocker is
   another goal).
4. **Defects found while sweeping** — including defects in the tools that generate the surfaces themselves.
5. **Orphan byproducts** — an artifact created *in passing* while executing something else (a PR opened by a
   session that was working through a decision list, a doc split off mid-task). It has no queue, no owner
   and no acceptance criterion, so nothing will ever close it. Classify these apart from a stalled lane:
   that session is not dead, it simply moved to the next item — and the fix is to give the artifact an
   owner, not to look for a corpse.

### 3. Rank by cost of continued ignorance, not by age

What feeds a live goal or another agent's decision outranks what merely looks old. A stopped evidence
line under an active promotion goal beats a five-day-old board thread; a scheduler loading the wrong
skills beats a stale doc. State the ranking rule you used in one line so the order is arguable.

### 4. Report

- Headline = the surfaces you swept, so the owner can tell a thin sweep from a broad one.
- ≤3 items per class, each as: **what** → `evidence path or command` → the smallest next step.
- Fix nothing silently while sweeping; anything you did fix gets its own line with proof, and stale
  bookkeeping the sweep falsified is corrected in the same pass (a recovered decision still marked
  pending is now a lie the next session re-litigates).
- End with **one question carrying numbered picks** ("I would do ① and ② — which?"), plus the
  2-minute first step for the top item. An open-ended "what should I do?" hands the ranking back.
- **"Is it done yet?" about one dispatched workstream is answered per deliverable, from live state.**
  Give each strand its own verdict — remote state (open/merged), CI counts, unresolved threads, the
  mechanical merge gate's `verdict` line, the runner's `exit` — rather than a summary of the task's own
  timeline, and name explicitly any timeline claim you could not re-derive. `gh pr view --json comments`
  returns **issue** comments and never the inline review threads, so the one thread blocking the merge is
  invisible there: read the connection directly — `gh api graphql -f query='{repository(owner:"<o>",
  name:"<r>"){pullRequest(number:<n>){reviewThreads(first:50){nodes{id isResolved path line
  comments(first:1){nodes{author{login} body}}}}}}}'` — and count `isResolved: false` yourself. One open
  thread blocks a merge that the checks, the marker and the runner's `exit` all report as ready.
- **"Is the owning session dead?" is answered from three records, never from the absence of one.** Find
  who authored the artifact, then read: (a) that session's last message in the session store —
  `~/.hermes/state.db`, `messages m JOIN sessions s ON s.id=m.session_id WHERE m.content LIKE '%<marker>%'`
  returns session id, role, timestamp, title; (b) the driver's own ledger/state file in the task dir;
  (c) process liveness (`systemctl --user status <unit>`, the run's recorded pid). A title showing the
  session went on to other work is *alive and done with this*, not dead; a driver that wrote its own
  refusal artifact and exited stopped **by design** — report "the gate stopped it", never "it crashed".
- **"Has it started at all?" is answered from the promise's own named parts: the driver, the unit, the
  ledger.** A kickoff or plan post is intent, not state — it names the artifacts it *intends* to create
  (a driver script in the task dir, a detached unit, a run ledger keyed by repo). Check each one exists
  on disk and in `systemctl --user list-units --all`, then `grep -i '<project>' <run-ledger>.tsv`: zero
  rows means **no worker has ever run for that tree**, however many task dirs, prompt files and empty
  `goals/` or `templates/` dirs sit beside it. Report the delta explicitly ("the plan names a driver;
  no such file exists; nothing will pick this work up") — an idle project read as autonomous is the one
  wrong answer that burns a night.

### 5. Closeout mode: partition, then dispatch — never keep working in the closing thread

When the unit being closed has a finished primary task but the conversation accreted other strands:

1. **Lead with the primary task's remainder — and verify it is zero before you say so.** Say it first, or
   unrelated live work makes a finished task read as open and the owner keeps it on their list for nothing.
   Derive the remainder, do not remember it: list the audit/findings ledger's items and match each against
   the plan's batch assignments. **A finding that no batch names was never scheduled — it is the one kind of
   "done" that is false**, and it is invisible to every per-batch acceptance run, because each batch passed
   its own fixtures while the item sat unassigned. So audit the plan's completeness, not its claims: count
   the findings, count the batches, name the delta. Treat a finding whose *suggested* change landed only
   partially (a general reading implemented as one special case) as still open — the recommendation, not
   just the file it named, is the acceptance criterion.
2. **Partition every other strand**: *owner-side* (a decision/approval only they can give) vs *bot-side*
   (work with an owning bot). Assign the owner by **write surface** (repos/CI/skills → the builder bot;
   money → the finance bot; long-context production → the studio bot), not by who happened to notice it.
3. **Dispatch the bot-side strands as detached units, each with a tracking surface that outlives the
   thread** — a fresh post whose first line carries owner / acceptance criteria / progress command /
   artifact paths. A dispatch nobody can look up is a dropped task the moment the thread archives.
   If a running driver's notification target **is** the thread being closed, that alone makes the thread
   unclosable: repoint the driver's thread constant to the new post first, and note that the
   already-running process keeps its old value until it relaunches.
   When the strand's own repo already has a **live lane** editing the same files, dispatch nothing:
   post the handoff into that lane's thread saying what the work is, which phase gate it must pass, and
   the file overlap that makes two lanes wrong — then state in the report that the post is **a record,
   not a wake-up** (one agent's message never starts another's session; only the owner naming it, or a
   kanban card assigned to its profile, does). Post long bodies from a file (`comment <thread>
   "$(cat f.md)"`): backticks and `$` inside a double-quoted shell string get command-substituted, so
   the body lands mangled or the shell dies on `wip: command not found`.
4. **Then the thread is closable**: name what is left with the owner and nothing else. Extra work found
   in a sweep of a closing thread does not get done in that thread.
5. **Then close it — closing is an action, not a report.** Post one closing note (what lives where, how
   you surface a block, that unarchiving restores history), then archive it: the host's Discord script
   takes `archive <thread_id>` — a `PATCH /channels/{id}` with `archived: true` — and that works on
   ordinary threads, not only forum posts. Verify from the returned channel object
   (`thread_metadata.archived: true`, `locked: false`; unlocked means the owner reopens by typing) and
   report that read-back, not the intent. Never answer "can I close it?" with "I have no
   channel-management API" before checking what the host's own bot-token scripts already do — a false
   capability claim costs the owner a round trip and they have to ask twice. Do not spend a
   confirmation round either once the owner has said close it. A card parked at `wip` because its work
   finished and nobody booked it closes the same way — retag `done`, then archive — and remember
   `tag <id> <names...>` sends `applied_tags` as the **complete** list (one `PATCH`): it replaces rather
   than adds. Verify from the channel object, not the command's exit status
   (`references/discord-tasks-board.md`).

### 6. Start mode: the day's Top-N is a rendering, not a worklist

"Start today's top 3" asks you to *begin*, so the first pass is a check of each item's agent-side work for
**today**, not a plan.

1. Read each item back to its source: the goal's `next:` line, the artifact it names, and that artifact's state
   (branch ahead/behind remote, uncommitted work, the report's own list of what still needs the owner).
2. Split every item into *what I can do now* and *what needs one word from the owner*, then **do the first part
   before replying**. An item whose entire remainder is an owner decision is reported as exactly that, with the
   question — never with a substitute task invented to fill the slot.
3. Say **"no action today"** when the artifact shows the item's real action sits on a future cadence (a weekly
   snapshot, a monthly review). The panel re-renders the same `next:` line every day, so a cadence item reads as
   today's work indefinitely.
4. If the cadence that item belongs to has **no job behind it**, that missing trigger is itself a finding —
   report it with the same weight as the item.
5. Reply shape stays the owner's: numbered items, per item one verdict + evidence path + the single blocking
   decision, and every question answerable by number alone.

## Pitfalls

- **Dispatch evidence lives in the task dir, not in the unit list.** `systemd-run --collect` units are
  removed once they exit, so `systemctl --user list-units --all` showing nothing is not "it never ran";
  and a `-r2` unit/log beside the original plus an artifact whose mtime is newer than the failure means a
  sibling session already resumed it. Read those before classifying a strand as stalled — otherwise you
  report live work as abandoned, and a re-dispatch double-runs it against a shared tree.
- **An authorization or a question can be dropped by the turn that received it, and only the thread
  remembers.** A turn killed mid-work — the ordinary case is one foreground command outliving the turn
  budget, which ends it as `session turn lease lost` — leaves the owner's message sitting there with no
  reply and no action, and the next session starts from a clean context with no idea consent was already
  given. So when the owner asks "怎么样了" about work a thread owns, re-read that thread's messages
  **including theirs** and check each against the world (does the disk / file / board actually show the
  authorized action happening?). Consent already typed is work to finish this turn, never a question to
  re-ask, and the report leads with the gap honestly — "your message of HH:MM was never acted on" — instead
  of presenting the remainder as fresh work. Recover the scope from the authorization's own words, execute
  it, and close with before → after proof.
- **A zero inbox is not an empty queue.** Check the writer's mtime: an evidence/decision inbox last
  written months ago means the capture line stopped, and that is the finding — not "nothing pending".
- **A tag is not activity, and the listing's `last_message` is not a last message.** `list` fills that
  key from `thread_metadata.archive_timestamp` — when the thread's archive status last changed — so a
  stall age taken from it can overstate by weeks, and it moves forward the moment you archive the card.
  Age a card from its newest *message* (`read <thread_id>`); never quote a stall duration that came from
  the listing. `review` means the build is done and unaccepted; `wip` can sit for a week while the
  watchdog keeps nudging.
- **A card's open question has to be read in full before you answer it.** `discord-forum-post.py read`
  caps each message body (~1200 chars), so an options list arrives cut mid-sentence and the answer keys on
  half a question; lift the cap for that one message (`channels/<thread>/messages?limit=N` against the
  Discord API with the bot token from `~/.hermes/.env`) whenever a status line or a decision depends on it.
- **`hermes cron incidents` prints resolved rows by default.** Count only unresolved/ongoing, or the
  report reads as a stack of live fires.
- **A run directory that exists is not a run that is alive.** Judge delegated work by
  `exit`/`ended_at`/process liveness, never by the presence of `state.json` or an event log.
- **Convert to one timezone before judging staleness.** Run state (`state.json:started_at`) and a card's
  message times (`read`'s `at`) are UTC while file mtimes are local, so a UTC start read as local time
  turns a thirty-minute-old live run into an "idle for eight hours, no session" zombie. Compare in a
  single zone, then confirm the verdict with process liveness or a growing event file.
- **Find the manifest before declaring there is none.** A lock that tracks a directory often sits one level
  *above* it (`~/.agents/.skill-lock.json` for `~/.agents/skills/`), so looking inside the tracked
  directory yields "no lock file" and manufactures an "nothing here is monitored" finding; search upward
  (`find <parent> -name '*lock*'`) before reporting the line as unmonitored.
- **Re-measure at answer time.** Elapsed time, tool-call count, commit count and `exit.code` come from the
  run's files *now*; a status line copied from the previous check is a claim about the past, and a job that
  died between two pings otherwise keeps reading as "still working". A tree returning different numbers on
  two consecutive reads is **not** a stale reading — it is a second writer: attribute the session
  (`hermes-operations` rule 30) and report the collision instead of joining the repo.
- **A status timeline is a claim surface, not the state.** It was written by whoever was mid-flight:
  artifact paths it names may not exist on disk, and a recorded exit code describes an earlier attempt
  (a gate logged as blocked is green minutes later, once the missing evidence comment lands). Re-derive
  each headline before repeating it; a claim you could not re-derive is reported as *unverified*.
- **A status file that keeps growing proves a child runner is alive, not that a coordinator is.** A
  `hermes chat` coordinator dies with its gateway while detached `systemd-run` child units keep running
  and appending their own lines, so the file looks healthy over orphaned work. Look for a live agent
  session separately (that profile's own agent log, a resumed session id) before telling the owner "in
  progress" or re-dispatching: growing file + no session = a strand that needs a new driver.
- **A closing thread can be a running driver's only output channel.** Before answering "can I close
  this?", `grep -rl '<thread_id>' ~/claw/tasks` and repoint every hit to a durable post — a thread closed
  over a live driver turns every later notification, including the blocked one, into silence.
- **A stale refusal note is corrected, not deleted.** When a `BLOCKED.md` or a status header is
  falsified by the driver's own ledger — later goals merged, the log running past the refusal's mtime —
  rename it with a `.resolved-<slug>-<date>` suffix and append one correction line naming the evidence
  (ledger path, the merge commit it records). Deleting destroys the record of what was believed;
  leaving the name `BLOCKED.md` re-reports a dead strand on every sweep. If the falsified claim was in
  your own previous report, lead the next report with the correction — a stale blocker sold as live
  costs the owner a decision they already made.
- **A run record left at `running` with no live pid is a false blocker for other trees.** Any
  orchestrator that refuses to start a lane while its repo has a "running" run will refuse forever.
  Read the state file *back* after any recovery command — the launcher's own `status`/`result` does not
  always finalize a record that never captured a pid — and when the record sits in another session's
  task dir, report the false-block risk to that lane: it is their bookkeeping, not yours to edit.
- **Board state is a notification, not the state.** A driver that stops itself (writes `BLOCKED.md` / a
  refusal artifact and exits) notifies nobody, so the thread keeps reading `wip` and a gated stall looks
  like a dead session. When the sweep finds the refusal artifact, reconcile the board in the same pass:
  post the block with reason, evidence paths and the resume command, retag it (`tag <id> blocked`), and
  read the thread back to prove both landed. A back-filled notice is part of the finding, not extra work.
- **A card is a promise; the artifact decides whether it was kept** — and the mirror case is the common
  one: the work landed and nobody booked it, so a finished deliverable reads for weeks as a stall. Before
  reporting a `wip` card as outstanding, re-derive its deliverables from where they land — package
  registry dist-tags, git tags, the release list, open-PR count, the version in the manifest — not from
  the card's own status lines. Read the landed side from `origin/main` after `git fetch`: a local worktree
  is routinely a commit or ten behind, and a version or pin read from it then contradicts the merge that
  actually happened (`git show origin/main:<path>`; `git rev-list --left-right --count main...origin/main`).
  A card whose every deliverable has landed is **bookkeeping debt, not stalled work** — close it, and
  never re-dispatch a lane for it. The mirror case is the more expensive one: **a card closed on
  mechanism-level proof while its acceptance criterion names the owner's real use over time** (two days of
  live input, a scheduled run actually landing) is a false completion, and a sweeper that inherits it finds
  nothing to re-offer — the work vanishes from every surface while the property being promised was never
  observed. Prove the mechanism, attach the evidence, and park it at `review` naming the run that must be
  waited for; only that run closes it.
- **A card recovered from a dead worker is not finished, and lifting its block re-exposes it to the
  dispatcher.** A crash leaves the card `blocked` with a diagnostic, so `unblock` returns it to `ready` and a
  live dispatcher can claim it and re-run the whole scope over work that is already done. Check for a running
  dispatcher first, then move it on in the same pass (`unblock` → `request-review`); a sweep that lifts the
  block and walks away has just queued duplicate work, and the duplicate report will look like the original
  failing twice.
- **An overdue item is a claim about the cadence, and the newest artifact dates it.** Before doing what
  the item names, read the artifact's own timestamps and results — newest snapshot's `captured_at` /
  platform-data date / N-of-N checks, the weekly report's mtime, the last line of its log — because a
  later scheduled run often already satisfied it while the surface kept rendering the old row. Satisfied
  ⇒ the work owed is the record that re-offers it: rewrite the `next:` line (or inbox row) it derives
  from, regenerate the panel, and say so in the report. Re-running a satisfied job is duplicate work;
  leaving the line re-litigates it next session.
- **A lane dispatched without a watcher is unobserved, not in progress.** A chat-facing session gets no
  further turns until the owner speaks, so "poll at the next turn boundary" leaves a lane that died at
  minute 10 silent for hours. Register a poll-and-notify watcher in the same call as the launch, and
  judge liveness by the recorded pid (`kill -0`) plus a still-growing event log — a run record left at
  `state: running` keeps saying so after the process is dead.
- **A numbered series is not one flat count.** When the answer is "X of N goals done", classify before you
  count: accepted · in-flight (a live lane/PR whose merge gate is still open) · ready-and-runnable ·
  provisional (cannot be dispatched until it is refined — it is not "pending work") · deferred (its
  environment is absent, e.g. an entitlement this host lacks). Collapsing provisional or deferred into
  "remaining" overstates what is left and hides the refinement that must happen first; collapsing in-flight
  into "done" hides the merge that has not landed. Give the classes, the count per class, and name what
  releases each blocked class.
- **Do not answer with a plan.** The sweep's product is the gap list, the classification and one pick;
  a plan smuggled into the answer hides which promises are actually broken.

## Related

- Pending **decisions** are reconstructed in `owner-decision-requests` §5b — that pass resolves the
  question set, this one finds the unfinished work.
- Board mechanics (decompose, dispatch, recover a stuck card) → `hermes-kanban`.
- Discord card mechanics — the `.py` field map, tag-replaces semantics, the readback recipe →
  `references/discord-tasks-board.md`.
- Health/drift surfaces and their fix owners → `hermes-operations`, `hermes-cron`.
