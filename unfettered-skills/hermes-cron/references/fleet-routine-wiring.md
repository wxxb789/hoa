# Wiring one plugin-backed routine across a fleet

Use when a routine must exist on many profiles at once (nightly memory consolidation, a
per-bot digest, a per-bot audit) and the work must stay free when the bot had no activity.

## The five pieces

A plugin-provided routine (e.g. `hermes-dreaming`) is not one cron job. Per profile:

1. **Plugin present** in `profiles/<p>/plugins/<plugin>/`. Profiles created with
   `--clone-from` usually have it; older profiles do not. Copy it without `docs/` and `tests/`
   (`shutil.copytree(..., ignore=ignore_patterns("docs", "tests", "*.png"))`) — the runtime
   needs `plugin.json` + `skills/`.
2. **Enabled** in `plugins.enabled` (`hermes -p <p> config set plugins.enabled '["…","hermes-dreaming"]'`).
3. **Gate script** copied into `profiles/<p>/scripts/` — cron resolves `--script` under the
   *profile's* scripts dir first, so `dream-precheck.py` must physically exist there.
4. **Job** with `--script <gate>.py`, `--skill <namespace>:<skill>`, `--deliver local`.
   Take the skill string from an existing working job (`agent-plugin-<name>-<hash>:<skill>`);
   the hash is per install, never guess it.
5. **`enabled_toolsets: ["memory"]`** so a wake only loads the tools the routine needs.
   `hermes cron create` has **no** `--enabled-toolsets` flag: patch the field into
   `profiles/<p>/cron/jobs.json` afterwards, then confirm with `cron list` / a re-read. CLI
   `cron edit` preserves fields it does not own (verified on `--schedule`), but re-check after
   any edit that rewrites the file.

## Free when idle: the wake gate

The plugin's precheck runs the deterministic phase (no model), writes its result to
`cache/<plugin>.json`, and prints **`{"wakeAgent": false}`** when nothing is actionable. Hermes
skips the agent turn entirely — the run is recorded as succeeded, nothing is spent.

So the cost model is: `N bots × nightly` **gates**, not agent turns. Gates are cheap; turns
cost money only on profiles that actually produced facts, decay, conflicts or promotions.

Verify without waiting for the schedule:

```bash
cd ~/.hermes/profiles/<p> && HERMES_HOME=$PWD python3 scripts/dream-precheck.py | tail -1
# idle profile → {"wakeAgent": false}     active profile → full JSON payload
hermes -p <p> cron run <job-id>      # ⇒ "Ran now: succeeded"; agent stayed asleep when gated
```

A payload with `new_facts_reviewed` / `md_decays` / `conflicts` > 0 means the bot *will* wake;
that is the correct behaviour, not a bug to suppress.

## Scheduling across a fleet

- **Stagger.** One wake-up hour for 12 bots saturates the model endpoints. 5-minute offsets.
- **Finish before the daily auto-update window.** The upstream updater restarts the gateway;
  a routine that starts inside that window is aborted mid-run. Schedule the fleet block before
  it (e.g. 01:30–02:30 when the update runs at 04:00).
- **`deliver local`** for consolidation jobs: they write memory files, they are not messages.
- Keep the fleet's gate scripts identical — one copy per profile, same content — so a fix is a
  loop, not archaeology.

## Pitfalls

- **A repo-materialized profile deletes host-added `[bot:<profile>]` jobs on its next `--apply`.**
  When a profile's routines are owned by a repository materializer (e.g. `materialize.py`), any
  cron job prefixed `[bot:<profile>] ` that is not declared in that repo's routines directory is
  flagged as `unexpected managed cron job` by `--check` and removed on `--apply`. Either declare
  the routine in the repo materializer or use an `[ops]` prefix so the materializer treats it as
  host-owned; verify with `materialize.py --check` immediately after wiring the fleet.
- **Pinning a routine's model + fallback touches two layers.** Setting `--model <id> --provider <p>
  --reasoning-effort <level>` on `hermes cron edit` writes `job.model` / `job.provider` /
  `job.reasoning_effort` directly into `jobs.json` (which pins the job against future default-model
  switches; `--pin` is a no-op when `model` is already set). However, Hermes has **no per-job
  fallback chain** — failover uses the profile's top-level `fallback_providers`, which applies to
  every turn on that profile, not just the cron job.
- **A plugin routine on a profile with memory disabled is half-blind**: the consolidation
  promotes into `memories/MEMORY.md` / `USER.md`, which are not injected when
  `memory.memory_enabled` is false. Either enable injection or accept that only the fact store
  side (decay, conflicts, dedupe) takes effect — say which one the owner is getting.
- **Do not enable the plugin's own scheduler jobs** in addition to the ones you create; two
  nightly consolidations on one store race each other.
- **`no_agent` jobs cannot host a wake gate** — the gate works on agent jobs (`script` output
  feeds the prompt and can suppress the turn).
- **Count gate skips, not just runs.** A fleet where every gate says `wakeAgent: false` for a
  week is telling you the bots are idle, not that the routine works.
