# Repo-owned bot definitions (profiles as build artifacts)

Use when a project needs several bots and its git repo must stay self-contained: definitions
versioned, runtime reproducible on another machine, no hand-maintained profile drift.

## Model

- The repo holds bot *definitions*: job, identity overlay, model, skill allowlist, tool limits,
  approval boundary, routines. It is the single source of truth.
- `~/.hermes/profiles/<name>/` is a build output of those files. It is replaceable.
- Sync is one-way: repo → runtime. Sessions, memory stores and cron execution history never flow
  back into repo bytes.
- Consequence to state up front: editing a live profile is drift, not a change. Changes go into the
  repo and are re-materialized (with a backup first).

## Layout

```text
bots/
  README.md                 # roster, ownership boundary, add/retire procedure
  matrix.yaml               # the only roster: name / job / writes / model / enabled
  <name>/
    bot.yaml                # title, section, model, skills, tool limits, approval
    SOUL.delta.md           # identity overlay (never SOUL.md)
    routines/<id>.yaml      # one file per scheduled job
  materialize.py            # the only writer into runtime
```

Keep the materializer stdlib-only and inside the repo so another machine can rebuild the whole
matrix without a second toolchain.

## Field contract (repo field → Hermes primitive)

| repo field | runtime target |
|---|---|
| `name` | profile directory / `hermes -p <name>` |
| `title`, `section` | `profile.yaml` → `ui_meta['hermes-bots']`, bump `_ui_meta_revisions` |
| `job`, `approval` | `profiles/<n>/SOUL.delta.md` |
| `model` | `config.yaml` model block via `hermes -p <n> config set` |
| `workdir` | four anchors, not just `terminal.cwd`: config `terminal.cwd` (new Desktop/gateway sessions), the active `projects.db` project, every stored `sessions.cwd`, and each job's `--workdir`; the local backend forces CLI one-shots to `os.getcwd()`, so pass `--in` |
| `memory: agent_memory` | `memory.provider=holographic`, `plugins.hermes-memory-store.{auto_extract,cron_writes}=true`; repo stays authoritative, memory is working context |
| `memory: repo_only` | `memory.memory_enabled=false`, `memory.user_profile_enabled=false`, `memory.provider=""`, `plugins.hermes-memory-store.{auto_extract,cron_writes}=false`, plus `memory` in `agent.disabled_toolsets` |
| `skills` | symlink allowlist into `profiles/<n>/skills/`; `skills.disabled` for trimming |
| `tools` | toolset restrictions; Hermes exposes toolsets, not a per-tool allowlist, so a read-only role is verified by diffing the checkout after each run |
| `routines/*.yaml` | cron jobs named `[bot:<name>] <routine-id>`; `trigger: manual` creates none |

Every routine file must carry the full contract, not just a schedule: id / schedule / timezone /
workdir / prompt path / deliver target / silence rule / success condition / failure behaviour /
approval boundary. A routine without a silence rule becomes noise; one without a failure rule
reports success it did not observe.

Hermes stores no per-job timezone: the job inherits `config.timezone`. Check a routine's declared
timezone against the profile config, and treat `trigger: manual` as "no cron job at all" — the
prompt stays as an on-demand playbook.

## Materializer behaviour

- `--check` — read-only diff of runtime against repo. Silent when healthy (so an `--no-agent` cron
  can run it daily and only speak on drift), non-zero exit on drift.
- `--dry-run` — print the plan, write nothing.
- `--apply` — back up every file it overwrites, then write.
- `--create-missing` — explicit opt-in; profile creation is an approval event, not a sync side effect.
- `--apply` removes a managed `[bot:<name>]` job whose routine no longer exists (via `hermes cron
  remove`) and runs the host's profile-SOUL generator, so a delta change cannot leave `SOUL.md` stale.
- Refuse to write when a repo file contains a home path or a key-like token; fail with `file:line`.
  Self-containment dies the first time a machine path gets committed.

## Invariants

1. Edit repo → `--check` → `--apply`. Never patch the live profile.
2. A daily drift job runs `--check` and stays silent unless something moved.
3. Every new top-level repo surface must be added to the repo's auto-sync allowlist (a
   `ALLOWED_ROOTS` list in the sync script, for example). A surface that is not allowlisted is
   never committed: the repo silently stops being the source of truth while looking fine locally.
4. Repo records definitions, not runtime state.
5. **"Repo is the source of truth" is not "memory is forbidden".** Those are two claims and the owner
   will separate them. `agent_memory` is a legitimate binding mode: the profile keeps the holographic
   provider with auto-extraction, and the contract says any consequential claim is re-read from the
   repository before it is acted on. `repo_only` is reserved for roles that must hold no memory at all.
   Write whichever mode the owner chose into the binding field, and put the SSOT sentence in both the
   repo `AGENTS.md` and the bot README — a contract that says "research facts never enter agent memory"
   when the bindings say `agent_memory` is a contradiction a future session will "fix" in the wrong
   direction.
6. `enabled: false` retires a role by pausing its jobs, never by deleting them; history stays.

## Changing the contract

A binding field is not the contract — the contract is every surface that describes it. When a mode
changes (e.g. `repo_only` → `agent_memory`), land all of these in one commit and then re-materialize:

1. `bots/bindings/<harness>/*.yaml` — the field itself.
2. `materialize.py` — `--apply` writes the new state, `--check` asserts it (a check that still
   enforces the old mode turns the daily drift job red the moment the bindings change).
3. `bots/README.md`, `bots/_schema.md`, `bots/bindings/README.md` — the rule text and the field table.
4. The repo `AGENTS.md` (the portable contract) **and** the host instruction file that summarises the
   profile layer — the two are read by different agents and drift apart silently.
5. The repo log — append the change; never rewrite earlier entries. A log that stops at the previous
   decision is how a future session concludes the old mode is still current.

Ordering: repo first (`--check` green, tests green), then `--apply`, then the summary docs. Docs before
code leaves a window where the contract and the runtime disagree, and that window is exactly when a
second agent regenerates from the wrong assumption.

## Pitfalls

- **Roster changes break count assertions, not behaviour.** The materializer test suite pins the roster
  size in several places (number of `create profile` lines, the role tuple, `len(roles)`, number of
  `profile missing` lines). Adding or restoring a role fails the suite on a number even though nothing is
  wrong — grep the test file for the old count and update every occurrence in the same change; run the
  suite via the repo's own entry point (`python3 tests/run.py`), not `pytest` (the harness may not be
  installed in the runtime venv).
- **Restoring a retired role is a git restore, not a rebuild.** `git checkout <rev> -- bots/roles/<r>
  bots/bindings/hermes/<r>.yaml`, re-add the matrix entry, update the counts, then `--apply`. Rebuilding
  the role from memory produces a plausible contract that no longer matches its tests.
- **`materialize --apply` runs for minutes and takes the install lock.** Do not run it concurrently with
  other `hermes -p …` loops (they log `dependency lock still held after 10.0s` and continue in an
  unknown state) and do not run it inside a foreground tool timeout that will kill it mid-write —
  background it with a completion notice, then verify with `--check`.
- `hermes profile create` copies skills as standalone copies or wrong-target symlinks and drops
  messaging channels. Reconcile and materialize immediately after creation.
- Profile `SOUL.md` is generated from root `SOUL.md` + `SOUL.delta.md`; writing `SOUL.md` directly is
  undone by the daily reconciler. The delta is the editable layer.
- Do not hand-edit `cron/jobs.json`. Create/edit through the CLI and match jobs by their
  `[bot:<name>]` prefix so re-materializing is idempotent instead of duplicating jobs.
- A profile's cron `--script` resolves under that profile's own `scripts/` dir; keep install-level
  watchdogs on the always-on scheduler and only attribute them by name prefix.
- `enabled: true` in a repo config is not a running schedule. A monitor registry can list live
  monitors while zero cron jobs reference the tool — grep the cron store for the tool name before
  reporting a routine as active.
- Do not create a profile per fan-out lane. Lanes are cards/subagents; a bot needs a persistent job,
  a write surface and an acceptance gate of its own.
- **Check the fields that decide behavior.** A drift check that compares schedule/prompt but not the
  job's `script`, `enabled` state, or the profile timezone reports healthy for a job that runs
  different code at a different hour.
- **`SOUL.delta.md` is not the whole identity.** The host composes `SOUL.md` from root SOUL + an
  overlay marker + the delta. Verify the marker and that `SOUL.md` ends with the delta; an apply that
  only writes the delta leaves the bot on the old identity until the next sync.
- **A persistent Bot Chat is not a fresh context.** `/new` in a bot chat compacts the same
  conversation, so an independent verifier must run as a bounded new run (cron or `-z`), and its
  receipt records the model family and revision it actually inspected.
- **Read-only is a policy unless the host enforces it.** Hermes offers toolset enable/disable, not a
  per-tool allowlist; verify a read-only role by diffing the checkout after the run.
- **`memory_enabled: false` does not disable an external memory provider.** If a cloned profile keeps
  `memory.provider: holographic` (or `plugins.hermes-memory-store.auto_extract: true`), Hermes still
  initializes the provider, injects `fact_store`, and auto-extracts facts after turns and cron runs.
  That is the wanted behaviour under `agent_memory`; under `repo_only` it is a leak — clear the provider,
  disable both plugin flags, and remove cloned `memories/MEMORY.md` and `USER.md`. Whichever mode the
  binding declares, `--check` must assert all three keys: a mode that only half-applies is worse than
  either extreme.
- **A host-level reconciler will re-add the provider you just cleared.** An install-wide job that
  enforces `memory.provider: holographic` on every profile (this install: `memory-provider-reconcile.py`)
  fights the repo contract daily: it writes the provider back, `materialize.py --check` then reports
  drift, and the two checks each accuse the other's output. Make the host reconciler skip profiles with
  `memory.memory_enabled: false` — the generic signal, not a name prefix — then run both checks until
  both are silent. Repairing only one side leaves a permanent morning oscillation and a dashboard that
  is red for a healthy system.
- **`--apply` is not a one-field fix.** It writes every drifted field *and* creates/removes the
  `[bot:<name>]` cron job per routine, so using it to clear one key can silently add a schedule set.
  Run `--plan` first; when only one field drifted, make that targeted edit and re-run `--check`.
- **`--clone-from default` copies the source profile's `terminal.cwd` and `kanban` targets.** Cron
  jobs use their own `--workdir`, so scheduled runs look healthy while interactive sessions start in
  the wrong directory and fail to load the repository's `AGENTS.md`. Pinning `terminal.cwd` is only
  one of four anchors: a session that already exists resumes at its stored `sessions.cwd`, and the
  Desktop project picker reads `projects.db`. Materialize all of them — `terminal.cwd`, an active
  `projects.db` project whose `primary_path` is the repo root, every stored session row, and each
  job's `workdir` — then drift-check them, or the bot keeps reading `~/claw` from its old Bot Chat
  while `--check` reports healthy.
- **A host-side job on a generated profile is deleted by the next `--apply` unless the generator
  declares it.** The materializer treats any `[bot:<name>]` job absent from the repo's routines as
  `unexpected managed cron job` and removes it. So a fleet-wide routine added from the host (memory
  consolidation, a monitor gate) must either be declared in the repo or be created *by* the
  materializer: add it to the expected-job set in `--check`, create/repair it in `--apply`, and
  assert every field it owns (schedule, script, deliver, workdir, model, provider, effort) — a check
  that only counts jobs lets the generator silently rewrite the model back on the next sync.
- **Coordinate single-writer leases with pre-agent gates and repo auto-sync.** A monitor gate that
  checks `git status` without checking the active run lease wakes the agent to report a false
  `BLOCKED: dirty worktree` whenever another role is mid-write, and a periodic git auto-sync that
  ignores the lease commits half-finished batches. Check the run lease first in both places.
- **Do not assign heavy synthesis or packet assembly to a fast front-door model.** Keep the front
  door on intake, scope freeze, and final acceptance; route cross-lane synthesis and writing-packet
  assembly to the synthesis role pinned to a strong reasoning model.
- **Keep portable surface scanners aligned with the contract.** If the contract forbids harness names
  and tool names in `roles/` as well as host paths (`C:\` is a relative directory name on POSIX and
  silently creates a `C:/home/<user>` tree under the checkout), scan for both in the pre-commit check.

## Acceptance

- `materialize.py --check` silent, `profile-layer-reconcile.py --dry-run` silent.
- One identity probe and one tool probe per new bot (`reply with exactly: <TOKEN>`, then a command
  that must actually execute).
- These prove provisioning only. The matrix is accepted when one real task completes end to end and
  its artifact passes its own acceptance gate; a green `--check` plus probes is not that.
- `git status` shows only the intended definition files; `hermes cron list` shows exactly one job per
  routine, with the `[bot:<name>]` prefix.
