# Profile roster audit and design

Use when the owner asks whether their bots/profiles are well divided, wants a roster
redesign, or asks for a new bot. The audit and the design are the same pass: gather
usage evidence first, then justify or retire each profile.

## Step 1 — Fix the objective before touching evidence

Ask what is being optimised. Two goals produce opposite recommendations:

- **Capability** ("help me finish complex tasks") — count is a free variable; profiles
  are added wherever a real boundary exists. This is the common case.
- **Simplicity** — fewer profiles matter. Only when the owner says so explicitly.

State the criterion in the answer. A redesign proposed as "you have too many bots" reads
as housekeeping; the owner's real question is whether the bots do anything.

## Step 2 — Read-only evidence pass

All read-only; open SQLite with `mode=ro`.

```bash
ls -1 ~/.hermes/profiles/            # roster, including dormant entries
```

Per profile:

- **config**: read `config.yaml` with `read_file` / `search_files` (see Pitfalls).
- **Real usage**: `state.db` → `select count(*) from sessions`, then pull `title`,
  `started_at`, `message_count`. Connectivity probes (`Reply with exactly: OK`,
  `PROBE_<profile>_OK`, `PINOK-*`) are not usage.
- **Owned routines**: `cron/jobs.json` in `~/.hermes/cron/` and each
  `profiles/<p>/cron/`. If every job lives on `default`, no bot produces anything on its
  own — the roster is decorative however good the personas are.
- **Routine labels**: `[bot:<profile>] <name>` only decides which Bot's Routines pane a
  job appears in; it does not move the job to that profile.
- **Group rooms**: `~/.hermes/shared-state.db` → `select count(*) from hosted_rooms`.
  Zero means the multi-bot war room was designed and never used.
- **Differentiation**: diff each profile's `skills.disabled` list. Identical lists mean
  every bot loads the same catalogue and differs only in prose and model id.
- **Memory**: `select count(*) from facts` per `memory_store.db`. Near-identical counts =
  the same facts cloned at profile-create time, now drifting independently.
- **Destinations**: newest file date in each profile's canonical directory (`career/`,
  `finance/`, `research/`, `gtd/`). A stale destination means the bottleneck is input
  cadence, not the absence of an agent.

## Step 3 — Justify each profile

A specialist earns its place only by differing on **at least one** dimension:

1. context (a focused slice, not the whole transcript)
2. tools (browser, code execution, DB, renderer)
3. permissions / approval boundary
4. model or inference profile
5. failure mode (a reviewer optimised to find errors, not to continue the line)
6. acceptance test (source coverage vs tests vs style-and-facts)
7. independence — runs in parallel without mutating shared state

On Hermes add two operational requirements: **a canonical destination** (the directory
holding authoritative state) and **its own recurring routine**. No destination and no
routine means it is a folder, not an agent.

Before designing a vertical, check whether the domain **already has an authoritative system
outside `~/claw`** (a vault, a repo, a policy chain). If it does, the bot adopts that chain —
reads its policy layer first, writes only the artifacts the chain defines, and never opens a
second source of truth beside it. Rebuilding a system the owner already maintains is the most
expensive way to get a bot that argues with its own records.

Equivalent shipping-product rule: create a separate bot when goal, tool set, working
style, approval boundary, or recurring schedule differs materially. If one sentence
cannot name the difference, the answer is a skill or a routine.

## Step 4 — Name the failure modes instead of describing them

- **Hollow bot** — no routine, no destination, sessions are connectivity probes.
- **Front door doing the building** — one profile routes daily work *and* does long
  engineering; each activity pollutes the other's context.
- **Org-chart cosplay** — role names (CEO/CFO/researcher) over the same model, tools,
  memory and acceptance test: renaming changes tone, not competence.
- **Roster as menu** — the owner must pick an agent before expressing the goal. Agent
  selection is implementation work; the system should route it.
- **Empty war room** — multi-bot group chat with zero sessions; parallel agents burn
  budget on coordination and acknowledgements.
- **Memory sprawl** — N near-identical fact stores; no bot learns from the others and
  the copies diverge.

## Step 5 — Target shape

```
front door (routing, memory owner, goals, GTD)
  + builder (repos, worktrees, long engineering context, no daily chat)
  + a few verticals (destination + routines + approval boundary + acceptance test)
  + goals above all of it
  + task threads inside it
  + ephemeral workers for fan-out (subagent / kanban lane / one-shot strong model)
```

- **Goals are first-class objects, above profiles**: outcome, why, horizon, status, plan,
  next actions, dependencies, evidence, approval requirement. Keep 3–5 active. Verticals
  hang off goals; profiles are not the unit of progress.
- **Task threads**: a complex task owns `plan.md`, evidence, outputs and status under
  `tasks/YYYY-MM-DD/<task>/` and does not inherit the parent transcript. This is what
  makes long work resumable and reviewable.
- **Ephemeral workers are not profiles.** Parallel research, multi-model drafting and
  blind review belong in subagents / kanban lanes; they leave no roster debt.
- **A single project's matrix splits on write surface + acceptance, not on pipeline stages.**
  Give each bot exclusive paths and its own acceptance gate; anything that produces one shard of
  one deliverable stays a card or subagent. Read the project's own execution contracts before
  proposing the shape — they usually fix the two decisions that determine it: acceptance cannot be
  delegated to a separate agent, and verification must run inside the same orchestration envelope
  as the research. A verifier on its own schedule therefore breaks the contract, while a verifier
  *card* dispatched with the same batch does not.
- **Model choice is a design signal**: a strong model where output quality is the
  deliverable (career narrative, financial judgement), fast models for orchestration, and
  a different family for adversarial review — the same model reviewing itself shares its
  own blind spots.

## Step 6 — Contracts every routine must carry

owner profile / trigger / timezone / input source / output destination / success
condition / failure behaviour / stale-data behaviour / approval boundary / notification
policy.

Silence by default: a routine that pings on every run trains the owner to ignore it.
Notify only for a decision, a threshold, or a change since the last run.

Approvals are capabilities, not sentences in a prompt: encode connector × action × scope
× duration × one-shot-or-recurring, and separate read / draft / send / irreversible.

## Step 7 — Governance

- **Retirement policy**: 30 days without meaningful use → disable; duplicates another
  workflow → merge; no canonical destination → redesign; upkeep exceeds value → delete.
- **Weekly usage audit**: sessions, artifacts and idle days per profile; idle profiles
  become retirement candidates automatically.
- **Tool/skill budget**: past roughly 30–50 tools, selection quality degrades — trim each
  profile's catalogue instead of loading the whole library everywhere.
- **One correction = rule, second occurrence = hard rule.** Rules that must hold go into
  the harness or config; practices live in skills and are followed most of the time.

## Reference implementations (commercial personal agents, 2026)

| Product | Model | Durable object | Memory | Multi-agent |
|---|---|---|---|---|
| Grok Bots (xAI/Cursor) | named roster | Bot = identity + job + private memory + owned routines + tools | per-Bot, a few facts shared | Bot↔Bot handoff, 2–6 bot group chats; **bots are not a security boundary** (shared cloud computer, sessions, credentials) |
| ChatGPT Dots (OpenAI) | one chief of staff | one primary Dot; work lives in task threads with their own conversation/files/results | layered: conversation / shared memory / Dot notes | background workers invisible to the user |
| Meta Muse | life OS | one agent; **Goals** is a first-class view | user-visible editable memory files inside the VM | internal subagent swarm, not user-facing |

What they converge on:

- Continuity beats explicit specialisation: the main conversation is canonical, side
  chats and task threads are branches.
- Memory wants **one owner** with layered scopes; multiple named agents create competing
  biographies — duplicated facts, stale preferences, unclear deletion boundaries.
- Routing is the system's job. User studies find people prefer a single-agent interface,
  and automatic orchestration lands within about 1% of human agent selection.
- Memory is not authoritative for changing facts — reopen the source system.

What not to copy:

- Shared credentials across agents presented as isolation.
- A user-visible agent menu as the primary interaction.
- Multi-bot group chat as the working surface: agents acknowledge each other, burn
  budget, and the owner still arbitrates. Use blind parallel review, with the rule that an
  agent speaks only when it owns the next step or is blocked.

## Step 8 — Execute the split

Order matters; each step is cheap and reversible until the last one.

```bash
hermes profile create <name> --clone-from default --description "<job, not persona>"
hermes -p <name> config set model.default <id>
hermes -p <name> config set model.provider <provider>      # clears inherited base_url/api_mode
hermes -p <name> config set model.api_mode <mode>
hermes -p <name> config set model.base_url <url>
hermes -p <name> -z "reply with exactly: <TOKEN>"          # end-to-end probe, not config read-back
```

- `--clone-from` deliberately does **not** copy messaging channels (a second copy of a bot token makes
  two gateways fight over one bot), and it copies skills as copies / wrong-target symlinks
  (`../../.agents/skills/<x>`). Reconcile right after creation or the new profile's catalogue is drift.
- `config set model.provider` reports that it cleared the clone's `base_url`/`api_mode`; set provider
  first, then endpoint and api_mode, then read the block back. A config read-back is not proof — the
  `-z` probe is.
- Persona: write `profiles/<name>/SOUL.delta.md` (never `SOUL.md`) plus `profile.yaml`
  `ui_meta.hermes-bots` title/section, then run the reconciler with **no flag**.
- Trim the catalogue with a JSON array: `hermes -p <name> config set skills.disabled '["a","b"]'`.
  It warns *"not a recognized config key — saved anyway"*; verify with `hermes -p <name> skills list`,
  whose footer prints `N enabled, M disabled`.
- **Job attribution beats job migration.** Cron `--script` paths resolve under the *profile's own*
  `scripts/` dir, so `hermes -p <name> cron create --script x.py` fails with *Script file not found*
  unless the file is copied. Worse, install-level audit scripts shell out to `hermes` and would inherit
  the new profile's `HERMES_HOME`, auditing the wrong home. Keep install watchdogs on the always-on
  scheduler and rename them `[bot:<profile>] <name>` — the prefix only chooses which Bot's Routines pane
  shows the job.
- A multiplexed gateway ticks every profile's cron store (all `cron/ticker_heartbeat` files share one
  mtime), so a profile's cron directory is live without starting a second gateway.
- Finish with `python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run` (silent = healthy) and the
  drift checker; a green pair plus the two probes is the acceptance proof. `-z "reply with exactly: <TOKEN>"`
  exercises identity, provider and routing but says nothing about tools — follow it with a probe that must
  call one, e.g. `hermes -p <name> -z "Run the shell command: date +%F_%H:%M and report only its output."`;
  a builder that cannot execute a shell command is a chatbot with a job title. Read `gateway_state.json`
  for pid and per-platform state instead of restarting the gateway — a profile that shares the existing
  scheduler needs no restart, and a restart you did not need is an outage you did cause.
- **Pre-flight beats rebuild.** An earlier session may have created the profile and stopped half-way: run
  `ls ~/.hermes/profiles/<name>`, read the model block in `config.yaml`, check
  `hermes -p <name> skills list | tail -1` (footer = `N enabled, M disabled`), and grep `cron/jobs.json`
  for jobs already carrying `[bot:<name>]`. When those exist, the remaining work is acceptance, not
  creation — re-running `hermes profile create` risks overwriting a hand-written `SOUL.delta.md`.
- **Hand back a run-log, not an adjective.** `tasks/YYYY-MM-DD/<split>/run-log.md` records the probe
  outputs, the model block, skill counts, the exact job ids attributed, what was deliberately *not*
  migrated, and the rollback command. That is what makes the split auditable a month later.

## Pitfalls

- **Read profile config with `read_file` / `search_files`, not a `python3 - <<EOF`
  heredoc.** A heredoc that opens `~/.hermes/config.yaml` can trip the gateway's
  destructive-command guard and be refused before it runs; `read_file` and
  `execute_code` read the same files without the false positive.
- **Count sessions only after filtering titles.** Probe sessions inflate adoption numbers
  and make a dead profile look used.
- **A stale destination is not proof the agent is useless** — it usually means the capture
  routine was never wired. Fix input cadence before adding or deleting a bot.
- **Do not propose a redesign from config alone.** Config shows intent; sessions, cron
  ownership and artifacts show what happened, and they routinely disagree.
- **Quantify workload in the unit the bot actually processes.** Counting files instead of work
  units can inflate an apparent backlog several-fold (raw file count vs source-batch directories),
  and a bot justified by a wrong number is retired within a month. Count the unit the routine
  advances and cite the measurement next to the proposal.
- **Renaming a profile moves sessions, memory and cron.** Change the roster title and
  section in `profile.yaml` (`ui_meta.hermes-bots`) first; rename the directory only with
  an explicit migration and a rollback path.
- **Directory-scanning routines must exclude the directory's own scaffolding.** A
  `goals/README.md` parses as a goal with no `id`, so the daily brief reports a phantom
  "goal with no next" and writes an id-less row into `today.md`. Require an `id:` field and
  skip `README.md` / `*.tmpl` / `_*.md`; the same guard applies to any script that globs a
  document directory.
- **Goal files must stay machine-readable.** Routines parse them without a YAML lib: keep a
  flat `key: value` header (`id / outcome / why / horizon / status / next / deps / evidence /
  approval / owner_bot`), prose only below the first blank line. Every reader must treat a
  `next` starting with `TODO` as "no next", or scripts echo the literal TODO back as the
  proposed action.

## Generated profiles (repo-owned roles)

Definitions, materializer behavior and drift pitfalls live in
`references/repo-owned-bot-definitions.md`; start there instead of hand-building profiles.
