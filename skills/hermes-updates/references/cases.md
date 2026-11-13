# hermes-updates — case notes

<!-- install-root: `$HERMES_HOME` below means the install root; it defaults to `~/.hermes` -->

Compressed case notes: signal, cause, fix, proof — 5–8 lines each. The rules live in `SKILL.md`;
treat these commands as leads to re-verify against the current build.

## Upgrade-safe maintenance without source patches

- **Signals**: Discord slash sync hit `Maximum number of application commands reached (100)`; a source-level fix was attempted and rejected — source drift is upgrade debt.
- **Resolution**: `DISCORD_COMMAND_SYNC_POLICY=off` in `$HERMES_HOME/.env` → `systemctl --user restart hermes-gateway` → log shows `Skipping Discord slash command sync (policy=off)`; trade-off: the native command picker stops updating, everything else works.
- **Rule**: config/env/profile/script before source; keep the ledger in `$HERMES_HOME/LOCAL_OVERRIDES.md`; `git status --short` stays clean unless preparing an upstream patch.
- **Silent jobs**: health/cockpit scripts print nothing when healthy (`owner-cockpit.py`, `--full` for a manual report).
- **Sessions**: export + `--dry-run` first; deletion needs `HERMES_SESSION_PRUNE_CONFIRM=yes`.
- **Proof**: `config-snapshot.py --check` + `post-update-check.py` (clean tree, sync policy, gateway active, expected jobs, cockpit silent, maintenance dry-run OK, snapshot current).

## No-op updates still need the post-check

- **Signal**: `hermes update --yes --backup` said "Already up to date", yet config version drift and a missing root `agent-browser` remained.
- **Cause**: the no-op path skips dependency resync, config migration and the web build — "source current" ≠ "runtime current".
- **Do**: `hermes --version` + `git status --short` + `hermes doctor` → update → then regardless: `hermes doctor`, `hermes config check`, `python $HERMES_HOME/scripts/post-update-check.py`.
- **Repairs**: back up `config.yaml` + `.env` before migration; reinstall deps from the checkout/lockfile instead of re-pulling; `agent-browser` repair is `npm install --workspaces=false agent-browser@<v>` then `git checkout -- package-lock.json`.
- **Restart without killing the turn**: `systemd-run --user --on-active=15s --collect /usr/bin/systemctl --user restart hermes-gateway.service`.

## Upstream drift assessment

- **Trap**: `hermes --version` can say "up to date" (release channel) while the checkout is behind `origin/main` — compare the checkout, not the label.
- **Measure**: `git fetch --all --tags --prune` → `git rev-list --left-right --count HEAD...origin/main` → `git log --reverse --date=short --pretty=format:'%h %ad %s' HEAD..origin/main` → `git diff --stat HEAD..origin/main`; rerun the count after `hermes update --check`, whose fetch invalidates the earlier number.
- **Classify by owner impact**: active path (platforms in use, provider/model switching, cron/session) · only-if-used (Desktop/TUI/TTS/Kanban) · inert capability (e.g. multiplexing while the flag is off).
- **Recommend**: update now when fixes hit the active path and the tree is clean; otherwise take a maintenance window (`update --backup` → restart → platform round-trips → `clarify` buttons → status/logs).
- **Report**: verdict, exact behind/ahead count, 5–8 commits grouped by value, an explicit recommendation, and a path to the full list.
