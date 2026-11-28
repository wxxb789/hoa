# Hermes operational configuration review checklist

Session-derived checklist for reviewing and hardening a user's Hermes/OpenClaw-style configuration without turning it into a fragile one-off migration log.

## High-value review order

1. Load the Hermes Agent skill before answering or editing Hermes configuration.
2. Inventory live state first:
   - `hermes config path`, `hermes config env-path`
   - `hermes profile list`
   - `hermes gateway status`
   - `hermes cron list --all`
   - session DB/WAL sizes and `pragma integrity_check`
3. Compare old OpenClaw artifacts only as migration evidence:
   - `~/.openclaw/`
   - `~/.hermes/migration/`
   - archive before removing anything
4. Prefer safe compaction before deletion:
   - SQLite `wal_checkpoint(TRUNCATE)` is low-risk after integrity check.
   - Export sessions before pruning.
   - Do not prune just because the DB looks large; check age distribution first.
5. Split operational concerns into profiles only when it reduces risk:
   - work / personal / research / gateway profiles are useful.
   - Do not switch a running gateway to a new profile without a migration/rollback plan; profile switch changes `HERMES_HOME` and can split channel/session/cron state.
6. Turn recurring operational checks into scripts + cron:
   - owner cockpit/status script
   - monthly session export
   - impact-log reminders when career evidence capture matters

## Root-vs-profile drift and dead-weight checks

- Profiles never inherit root config — diff root against every profile for the knobs that
  change answer quality: `model.default` / `model.provider` / `model.api_mode`,
  `agent.reasoning_effort`, `fallback_providers`. Silent drift means the same question gets a
  different-quality answer per entry point (e.g. root defaulting to a free flash route while
  every profile runs the strong model).
- `fallback_providers: []` means a dead primary route kills every session pinned to it — set a
  fallback on an **independent chain** (different host/upstream), not just another transport on
  the same proxy.
- Kanban dispatch chain: `kanban.auto_decompose: true` with empty `kanban.default_assignee`
  (and `orchestrator_profile`) silently skips every auto-decomposed card
  (`skipped_unassigned`).
- Dead provider entries (`enabled: false`, no models in use) are deletion candidates — verify
  no profile or `model_aliases` entry still references the provider name before removing.

## Session export/prune pattern

Before pruning:

```bash
mkdir -p ~/.hermes/backups/sessions
hermes sessions export ~/.hermes/backups/sessions/sessions-all-$(date +%Y%m%d-%H%M%S).jsonl
```

Then inspect age distribution in `state.db` before choosing a threshold. If all data is recent, do not prune. Schedule monthly export first; prune later when old data actually exists.

## Gateway profile pitfall

A dedicated `discord` profile can be useful for experimentation, but a systemd gateway installed with:

```text
Environment="HERMES_HOME=/home/<user>/.hermes"
```

is using the default profile. Moving it to `~/.hermes/profiles/discord` changes the state root, not just configuration. Treat that as a migration, not a cosmetic setting.
