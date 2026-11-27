# Hermes Discord slash command sync: 100-command cap

Session-derived debugging note for Hermes gateway / Discord application command reconciliation.

## Symptom

Gateway logs show Discord slash command sync failing after connect:

```text
discord.errors.HTTPException: 400 Bad Request (error code: 30032): Maximum number of application commands reached (100)
```

## Root cause pattern

Discord enforces a hard 100 global application-command cap per app. A diff-based sync can still fail even when desired state has <=100 commands if it mutates in the wrong order:

1. Create/upsert new desired commands first.
2. Delete stale existing commands later.

When the app is already at 100 commands, step 1 fails before step 2 can free capacity.

## Durable fix pattern

For bounded-capacity external registries, reconcile in capacity-safe order:

1. Fetch existing remote state.
2. Diff desired vs existing.
3. Apply updates/recreates for existing matching keys as needed.
4. Delete stale remote entries first.
5. Create new desired entries last.

For Hermes Discord specifically, `_safe_sync_slash_commands()` should collect missing desired commands into `pending_creates`, delete entries left in `existing_by_key`, then upsert pending creates.

## Regression test shape

Simulate the remote app at cap:

- 100 existing commands
- 1 desired new command
- 1 stale command among existing

Assert mutation order:

```text
first mutation: delete stale command
last mutation: upsert new command
```

This catches the failure mode better than only asserting final created/deleted counts.

## Test hygiene pitfall

Hermes gateway tests may inherit real `DISCORD_ALLOWED_CHANNELS` from the developer environment. If a Discord message-routing test unexpectedly captures zero events, rerun the targeted test with that env var unset before diagnosing product logic:

```bash
env -u DISCORD_ALLOWED_CHANNELS ./venv/bin/python -m pytest tests/gateway/test_discord_connect.py tests/gateway/test_discord_slash_commands.py -q -o addopts=""
```

Capture the fix pattern, not the transient environment state.
