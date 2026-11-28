# Config efficiency review

Use this reference when reviewing Hermes/OpenClaw configuration for lower cost or lower operational overhead without sacrificing the user's primary model quality.

## Procedure

1. Establish the read-only boundary.
   - Inspect active paths with `hermes config path`, `hermes config env-path`, `hermes profile list`, `hermes gateway status --deep`, `hermes cron list --all`, and `hermes doctor`.
   - Never print `.env`, auth files, cookies, JWTs, or inline credential values; report presence/absence only.
   - Do not restart a live gateway, delete state, prune sessions, or remove migration archives during review.
   - If the owner authorizes implementation, split it into no-restart config work and a separately confirmed maintenance window; back up root/profile configs before writing.
   - Use `hermes config set/unset` for protected Hermes config files, then verify the resulting values with a redacting parser; a successful write or an unknown-key warning is not proof that runtime code consumes the field.

2. Inventory the live configuration and every served profile.
   - Read the root config and each `profiles/*/config.yaml` through a redacting parser.
   - Compare `model`, `providers`, `auxiliary`, `compression`, `prompt_caching`, `delegation`, `platform_toolsets`, `sessions`, and `smart_model_routing`.
   - Treat a profile-local value as active behavior; do not assume the root config wins under multiplexing.
   - Record config snapshots and owner override docs as evidence, not as authoritative live state.

3. Validate runtime claims.
   - Search the active source for the key, dispatch path, provider resolver, and profile/config merge path.
   - Run the smallest live probe that exercises the same path: provider construction for provider changes; `hermes config check` for schema; a dry-run for cron; `/health` and `/v1/models` for a local proxy.
   - A model alias that resolves to a model name is NOT proof the route works. Probe the alias end-to-end (`hermes chat -q "Reply with exactly: ok" --model <alias>`) and read the resulting session row: `api_call_count=0` plus a canned not-processed reply means a dead route despite the resolved name. Distinguish transport-level rejection (direct `POST /v1/responses` vs `POST /v1/messages` against the local proxy) from model deprecation.
   - Check every profile's `providers:` table actually defines each provider its `model_aliases` reference — profiles never inherit root providers, so an alias pointing at `custom:<name>` undefined in that profile fails only on use.
   - Separate documented, implemented, and live-verified behavior in the report.
   - Do not enable a stale toggle merely because an old pre-migration snapshot or setup wizard wrote it.

4. Measure before optimizing.
   - Use Python stdlib `sqlite3` read-only connections (`file:<path>?mode=ro`, `uri=True`) when the CLI is unavailable or the normal session command is unhealthy.
   - Aggregate sessions by source/model/provider and inspect `api_call_count`, input/output/reasoning tokens, cache-read/write tokens, and cost status.
   - Treat dollar cost as unknown when the provider reports `unknown` or the local proxy does not expose pricing; use token volume, cache share, retries, and concurrency as honest proxies.
   - Split main-turn vs auxiliary spend via the `session_model_usage` table's `task` column (`''` = main turns; `title_generation`/`vision`/`background_review` = auxiliary). Auxiliary is usually a rounding error — optimize the main-model path first.
   - Diff the live proxy `/v1/models` catalog against configured provider model tables; models configured but absent from the live catalog are dead entries.
   - Query tool usage by platform before removing optional toolsets; preserve tools that are low-frequency but demonstrably used for vision, browser, cron, or file work.

5. Preserve quality-sensitive paths.
   - Keep a working primary model, reasoning policy, compression path, and prompt-cache TTL while testing cost controls.
   - Prefer limiting delegation iterations/concurrency and removing unused optional tool schemas over downgrading the primary model.
   - Keep prompt caching enabled when cache-read share is high; system-prompt, tool-list, and profile changes can reduce cache reuse.
   - Do not enable smart routing without current source evidence and a quality-gated evaluation set.

6. Handle session-store failures separately from optimization.
   - If Hermes reports a deleted `state.db-wal` or `state.db-shm` generation, stop gateway, dashboard/WebUI, cron writers, and other DB users in a maintenance window.
   - Run `pragma integrity_check` before and after; checkpoint with SQLite (`pragma wal_checkpoint(TRUNCATE)`) after all writers are stopped.
   - Reopen the DB, then verify `hermes sessions stats`, `hermes insights`, gateway status, and fresh platform connection markers.
   - Never `rm` WAL/SHM sidecars directly; the deleted inode may still be held open by a live process.

7. Compare pre-migration platform artifacts without re-importing them.
   - Inspect surviving old-platform homes, migration dirs, and dated config backups as historical evidence only.
   - Identify the latest complete archive and duplicate snapshots before proposing cleanup.
   - Treat generated plugin registries and old filesystem/security settings from the retired platform as non-authoritative.
   - Archive before destructive cleanup and require an explicit retention scope.

8. Verify and report.
   - Run `hermes config check`, `hermes doctor`, `hermes gateway status --deep`, the relevant proxy/model probe, and the configured post-update/health checks.
   - For multiplexed installs, verify the root and each served profile separately; provider construction should exercise the same auxiliary/main path being changed.
   - Keep health-check job expectations aligned with live cron and owner docs; do not create a notification job merely to satisfy a stale checker.
   - Report unresolved warnings separately from changes and recommendations.
   - Give the owner the next three actions, blast radius, rollback, and the exact confirmation needed for red actions.

## Decision table

| Finding | Default action | Why |
|---|---|---|
| High cache-read share | Preserve cache TTL and stable prompt/tool shape | Cache reuse is already reducing uncached input work |
| Very high delegation iteration/concurrency budget | Lower the default budget; keep per-task escalation available | Bounds runaway cost without downgrading normal turns |
| Profile provider/auxiliary drift | Normalize after a probe and backup | Root edits do not necessarily affect served profiles |
| Optional tool unused in measured platform history | Remove only from that platform/profile | Reduces schema overhead without global capability loss |
| Unknown/zero provider cost | Do not claim dollar savings | Local proxy or subscription billing hides marginal price |
| Deprecated empty config key | Remove after backup and config check | Eliminates warning without changing intended behavior |
| Session DB deleted-WAL/SHM warning | Maintenance-window recovery first | Observability and persistence are unreliable until fixed |
| Old pre-migration platform archive | Retain one rollback-grade copy until the new setup is proven, then review duplicates | Historical config is evidence, not live state |
| Alias resolves but probe shows `api_call_count=0` | Treat as a dead route; remove or repoint in root AND every profile | A resolved model name masks a broken transport or deprecated slug |
| Provider model absent from live `/v1/models` | Drop from provider tables after backup | Dead catalog entries invite future failed calls |
| High cache-read share + large skills prompt | Prefer gradual curator archiving over bulk skill deletion | Every skills-prompt change invalidates the whole prompt cache |

## Reusable pitfalls

- Use Hermes' config CLI for protected files — generic patch/write operations can be refused even when the requested change is valid.
- Compare all served profiles before changing the root config — multiplexed profile-local overrides can keep using a different provider or auxiliary route.
- Probe the endpoint Hermes actually uses — `/api/v1/models` can be an unsupported health probe while `/v1/models` and `/health` are healthy.
- Preserve cache before reducing prompt/tool weight — a smaller prompt that invalidates a high-hit cache can cost more overall.
- Treat cost status as evidence, not decoration — `unknown`/`none` means report token and call metrics, not invented dollars.
- Search source before enabling a config toggle — setup-wizard persistence is not proof of runtime dispatch.
- Stop every DB writer before WAL recovery — deleting a sidecar while its inode is open creates a second-generation conflict.
- Keep migration cleanup separate from runtime optimization — deleting old state is irreversible and does not lower per-call token cost.
- Probe model aliases end-to-end before trusting them — a name that resolves can still be a dead route; `api_call_count=0` in the probe session is the tell.
- Bulk skill removal invalidates the skills-prompt cache — when cache-read share is high, a one-shot purge can cost more than it saves; prefer gradual curation.
