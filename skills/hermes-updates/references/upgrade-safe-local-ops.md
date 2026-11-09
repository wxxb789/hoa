# Hermes upgrade-safe local operations

Session lesson: when troubleshooting or configuring a locally installed Hermes runtime that should
stay aligned with official upstream, prefer config/env/profile/script/user-prompt changes over
source-code patches.

## Trigger

Use this pattern when:

- the target system is Hermes Agent itself or another frequently-upgraded local runtime;
- the user wants to preserve compatibility with official upgrades;
- a workaround can be expressed through `.env`, `config.yaml`, profiles, cron jobs, scripts, or
  operational docs.

## Decision order

1. Root-cause the issue as usual.
2. Check whether an existing config/env/user-prompt/profile switch can solve or mitigate it.
3. If yes, implement the upgrade-safe override and document it.
4. Only patch source when:
   - preparing an upstream-quality PR/commit;
   - no config escape hatch exists;
   - the issue is a blocker and the user accepts local fork drift.
5. If a temporary source patch was made, either upstream it or revert it before declaring the local
   runtime upgrade-safe.

## Required artifact: local overrides manifest

For Hermes, maintain a local overrides manifest next to the install (the exact path and filename are
an install choice).

It should record:

- config/env/profile/script/cron overrides;
- why each exists;
- whether it is upgrade-safe;
- rollback steps;
- verification commands after `hermes update`.

## Example: chat-platform command sync cap

Symptom:

- Gateway logs `400 Bad Request (error code: 30032): Maximum number of application commands reached`.

Upgrade-safe mitigation:

- Set `<PLATFORM>_COMMAND_SYNC_POLICY=off` in `$HERMES_HOME/.env`.
- Restart the gateway.
- Verify logs contain `Skipping <platform> slash command sync (policy=off)`.

Avoid a long-term local source patch unless the intent is to submit upstream. A source-level fix might
reorder sync to delete stale commands before creating new ones, but this local patch will drift on
upgrade if not upstreamed.

## Plugins are pinned checkouts — never patch their scripts

`$HERMES_HOME/plugins/<name>/` is a git checkout at a **detached** catalog commit
(`.hermes-catalog.json` pins the version). Unlike `hermes-agent`, a plugin update re-checks-out the
pinned commit, so a local edit to a plugin script is dropped **silently** — no dirty-tree guard, no
failure, the tuning just stops existing. Check with
`git -C "$HERMES_HOME/plugins/<name>" status --short` and `git rev-parse --abbrev-ref HEAD`
(`HEAD` = detached = expected).

Therefore tune a plugin through layers it cannot overwrite:

1. its config file (`$HERMES_HOME/<plugin>.json`);
2. the cron job's **custom prompt** (`hermes cron edit <id> --prompt "$(cat new-prompt.txt)"`) —
   the plugin installer labels it `custom/unknown prompt — preserved`, so it survives both plugin and
   installer reruns;
3. a wrapper script in `$HERMES_HOME/scripts/`, if the plugin exposes one.

The plugin installer's `--rebind` mode rewrites only `skill`/`skills` on existing jobs and never
touches a custom prompt — it is the right fix for a stale skill binding after a plugin rename.

## Health/watchdog pattern

For recurring maintenance scripts:

- default to silent when healthy;
- emit stdout only on actionable problems;
- provide `--full` for manual reports.

This keeps cron/no-agent jobs useful without creating notification fatigue.

## Session maintenance pattern

For session databases:

- export before pruning;
- report candidate counts by age/source first;
- require explicit env confirmation before deletion, e.g. `HERMES_SESSION_PRUNE_CONFIRM=yes`.

Do not turn a backup/cleanup task into silent data deletion. Future-you has enough enemies.
