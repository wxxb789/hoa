# Cron health audit and delivery routing


## Cron job health audit (every job: alive vs broken)

When the owner asks whether their cron jobs still work, use the built-in tooling — do not hand-roll a
verdict from `hermes cron list` alone.

1. `hermes cron status` (scheduler host, ticker heartbeat, next run) and `hermes cron list --all`
   (per job: schedule, deliver target, last-run status, execution id).
2. `hermes cron doctor` — the official health check. It flags last-run failures and results that were
   never delivered, and prints the repair command. `✓ Cron doctor found no issues` is the pass line.
3. `hermes cron incidents` — durable incidents (`detected` / `resolved` / `closed`; they auto-resolve
   after the next success, so a stale incident is not proof of ongoing breakage). `hermes cron runs <id>`
   — attempts tagged `source=builtin` (scheduler/worker path) or `source=direct` (CLI-triggered), and
   `unknown` when the scheduler restarted mid-run.
4. Re-run each broken job with `hermes cron run <id>`, then confirm the durable run record **and** the
   output artifact (`~/.hermes/cron/output/<id>/*.md`). A CLI-triggered run proves the payload, **not**
   the restart-safe worker path — that path is proven by a short-interval job's own scheduled runs.
5. Compare `last_run_at` with when the underlying fault was fixed: a green "last run ok" that predates
   the fix proves nothing. For silent-when-healthy scripts, compare the newest output artifact's size
   against earlier healthy runs instead of reading silence as failure.

Pitfalls:
- **`deliver: origin` with a null `origin` fails silently at delivery time** while the job still reports
  `ok` — the home-channel fallback dies in the profile-scoping reader. Enumerate real targets with
  `cron.scheduler_delivery.cron_delivery_targets()` (`home_target_set` per platform; `bot-chat:<profile>`
  needs no config, a bare platform needs its `*_HOME_CHANNEL` env var **in the job-owning profile's
  `.env`**, not just root). Change with `hermes cron edit <id> --deliver <target>` / `--failure-deliver
  <target>` (`local` suppresses failure notices).
- Prove delivery with a throwaway one-shot self-test job, not with the job fields alone:
  `hermes cron create '1m' --name cron-delivery-selftest --no-agent --script cron-delivery-selftest.py
  --deliver <target> --repeat 1` (script ships at `~/.hermes/scripts/cron-delivery-selftest.py`), then ask
  the owner to confirm receipt — successful deliveries are not journaled.
- A delivery target is an owner preference: ask; if no answer arrives, leave the job's execution
  untouched and say so — output artifacts keep landing on disk meanwhile.

Field dump + runnable probe: `scripts/audit-cron-health.py` (`--targets` also lists the delivery targets and their home-channel state).
Command reference, delivery-target resolution and verification matrix: `references/cron-health-audit.md`.

## Cron delivery: the home channel is per-profile

- `deliver: origin` with an empty `origin` falls back to the platform home channel, which is read through
  the **job-owning profile's** secret scope (`cron/scheduler_delivery.py::_home_env_lookup` → `get_secret`).
  A home channel set only in the root `.env` does not cover jobs owned by another profile — set
  `<PLATFORM>_HOME_CHANNEL` in every profile that owns jobs (`hermes --profile <p> config set
  DISCORD_HOME_CHANNEL <id>` routes to that profile's `.env`).
- A missing/unreadable home target raises `UnscopedSecretError` ("could not read this profile's
  MATRIX_HOME_ROOM …") while the run still reports `last_status: ok` — delivery state lives in
  `last_delivery_error` / `last_delivery_unverified` and in `hermes cron doctor`.
- Verify a target with a real one-shot job instead of reading config:
  `hermes cron create '1m' --name cron-delivery-selftest --no-agent --script cron-delivery-selftest.py
  --deliver <target> --repeat 1` (script ships in `~/.hermes/scripts/`), then delete the job.
- `cron_delivery_targets()` lists deliverable targets and whether each home channel is set;
  `bot-chat:<profile>` needs no home channel at all. Call it **with `.env` loaded**
  (`load_dotenv(~/.hermes/.env)` or a shell that sources it): invoked from a bare interpreter it reads
  no secrets, reports `home_target_set: False` for every platform and silently omits platforms whose
  home var it cannot see — which reads exactly like "home channel missing" and invites a false report.

### Route ops/system output to a dedicated channel

When the owner is annoyed by system noise in a DM, split the jobs by audience instead of silencing them:

- **Ops/system jobs** (resource watchdog, profile/memory reconcilers, contract drift, weekly audit, repo-sync watchdogs) → `deliver='discord:<ops_channel_id>'`.
- **Personal jobs** (daily brief, water/task nudges, career impact) keep `deliver='discord'` (home = DM).
- Use the explicit channel id, not `discord:#name`: name resolution needs the channel to already be in `~/.hermes/channel_directory.json`, which only updates after the bot sees traffic there.
- The target channel does **not** need to be in `discord.allowed_channels` — outbound delivery uses the bot token directly, and leaving it out keeps a one-way dashboard from triggering agent turns.
- Creating the channel needs Manage Channels on the bot; without it, ask the owner to create it and hand back the id (`GET /users/@me/guilds` → `GET /guilds/<id>/channels`).
- Verify, don't assume: `hermes send -t discord:<id> "test"`, read it back via `GET /channels/<id>/messages`, then let one real cron run land and confirm it appears there.
- Update jobs with `cronjob_manage(action='update', job_id=..., deliver=...)` and back up `~/.hermes/cron/jobs.json` first.
