# Upgrade execution and drift triage

## Upgrade-safe maintenance / source drift control

Use config/env/profile/prompt/scripts before Hermes source edits. Local source patches are upgrade
debt unless the owner explicitly wants an upstream-quality patch or an unavoidable hotfix.

### Upstream drift / update-worth assessment

When the owner asks whether the running Hermes is behind latest, or whether new upstream commits are
worth updating to, do a source-drift assessment rather than answering from version text alone:

1. Load the runtime's own CLI reference (if the install ships one) for current update commands and
   release/update semantics.
2. Inspect active install and checkout: `hermes --version`, `hermes config path`,
   `cd "$HERMES_HOME/hermes-agent"`, `git status --short --branch`, `git rev-parse HEAD`,
   `git describe --tags --always --dirty`.
3. Fetch before judging: `git fetch --all --tags --prune`.
4. Compare active source to upstream: `git rev-list --left-right --count HEAD...origin/main`,
   `git log --reverse --date=short --pretty=format:'%h%x09%ad%x09%s' HEAD..origin/main`, and
   `git diff --stat --compact-summary HEAD..origin/main`.
5. Run `hermes update --check` as a second opinion; if it fetches newer commits, rerun the git
   count/list because the first manual result may now be stale.
6. Classify commits by current owner impact: active gateway/platform path first, current
   provider/model setup, cron/session/debug, then dashboard/TUI/TTS/Kanban/future features.
7. Separate "behind release tag" from "behind upstream `main`". A checkout can be on the latest
   release tag while still dozens of commits behind `main`.
8. Recommend controlled maintenance-window updates for live gateway installs when core
   gateway/session files changed, even if the update is worth doing.

Session detail: `cases.md#upstream-drift-assessment`.

### GitHub HTTP 429 during a git-based update

A public `git fetch origin main` can be rate-limited even when the vendor API works with the owner's
token. Handle this without embedding credentials in the remote URL:

1. Verify the target SHA through the authenticated API: `gh api repos/<owner>/<repo>/commits/main --jq .sha`.
2. Fetch with a preemptive Basic auth header generated in-memory from `gh auth token`.
3. Do **not** use `--filter=blob:none` as the recovery fetch. The updater/reset may later need
   promised blobs, trigger an unauthenticated lazy fetch, and leave the checkout as a mixed working
   tree with hundreds of apparent deletions. Use a complete refetch instead:
   `git fetch --refetch --no-filter origin main` with the auth header, then verify a previously
   missing object with `git cat-file -t <oid>`.
4. Back up `$HERMES_HOME`, confirm the pre-update source was clean, and verify `origin/main` equals
   the API SHA before changing HEAD.
5. If the updater itself still performs a rate-limited fetch, use a temporary `git` wrapper on `PATH`
   only for that updater run: no-op the already-completed `git fetch origin main`, translate
   `git pull --ff-only origin main` to local `git merge --ff-only origin/main`, and pass every other
   command to the real git binary. Remove the wrapper afterwards.
6. If a partial checkout already failed while HEAD stayed old, restore source consistency with
   `git reset --hard origin/main` only after proving the original tree was clean and backups/snapshots
   exist. This does not touch config, credentials, memory, or sessions.
7. A manual reset to latest makes `hermes update` take its no-op path and may skip
   dependency/resource sync. To exercise the official full updater safely, reset a clean checkout
   temporarily to `origin/main^`, run the updater through the local-fetch wrapper so it sees exactly
   one update, and verify it returns to the target SHA. Use this only as a recovery path with backups.

Finish by matching local HEAD to the authenticated API SHA, checking a clean tree, running
`hermes config check` and `hermes doctor`, refreshing/restarting the gateway, and removing all
temporary wrappers.

### No-op `hermes update` post-check

`hermes update` returns early when git is already current. That path proves source freshness, but it
may skip dependency reinstall, bundled skill/profile sync, web build, and config migration. After any
owner-requested "upgrade to latest", always run the post-check loop even if update says "Already up to
date":

1. `hermes --version` and `git status --short` in `$HERMES_HOME/hermes-agent`.
2. `hermes doctor` and `hermes config check`.
3. If doctor/config reports a new config version, run non-interactive safe migration or
   `hermes config migrate` as appropriate; back up config/env first.
4. If source is current but dependencies/tooling are stale, resync dependencies from the checkout
   rather than re-pulling source. Treat setup-state failures as fixable install/config steps, not
   durable tool limitations.
5. Restart the gateway after dependency/config changes so the running service loads the updated
   venv/config.

Session detail: `cases.md#no-op-updates-still-need-the-post-check`.

### Unfinished update tail is advisory, not a fault

A non-fatal update whose *optional* tail fails (web UI `build`, a pinned driver install) leaves every
later launch printing ``hermes: a source update is unfinished; run `hermes update` from a shell to
finish it``, even when source, deps, and the running gateway are current and consistent. Confirm it is
advisory before acting: `hermes update --plan` is read-only and prints the install sha and the
services it would restart without complaining about a lock, and the newest
`$HERMES_HOME/logs/update_receipts/update_*.json` shows `outcome: success` with only the specific
stage marked `failed` (e.g. `build`). A stale `.git/hermes-update.lock` holding a dead PID does not
block the next run. The notice clears on the next successful `hermes update` — do not rush a large
catch-up update (especially during work hours) just to silence it; the unattended timer retries with
snapshot and rollback.

### Owner-requested upgrade of a live gateway install

Same shape as the unattended path, run by hand. Post-check depth, checkout-state invariants and the
dependency-environment mechanism: `references/update-execution-and-runtime-state.md`.

1. Record pre-state: `hermes --version`, `git status --short --branch` plus `git rev-parse HEAD` in
   `$HERMES_HOME/hermes-agent`, `systemctl --user is-active hermes-gateway.service`. Before stopping
   the gateway, verify that the maintenance process is outside its service cgroup and process
   ownership; separate tool calls alone do not prove isolation. Use an independently supervised
   external maintainer when the session is gateway-served, because stopping that service can otherwise
   kill the process responsible for recovery. Capture the committed dependency selection and
   state/schema version alongside the source SHA for compatibility checks.
2. Create the snapshot explicitly. When `updates.pre_update_backup` is `false` (a configuration
   choice), a manual `--no-backup` run has no rollback path unless you make one:
   `venv/bin/python -c "from hermes_cli.backup import create_quick_snapshot; print(create_quick_snapshot(label='manual-upgrade-latest', keep=3, max_file_size=1 << 30))"`.
3. Order: stop the gateway → `venv/bin/hermes update --yes --no-backup --branch main` → restore the
   shallow window (`git fetch --depth=10 --prune --no-tags origin main`) → re-apply the local tail the
   unattended updater owns → start the gateway → post-check loop (`hermes doctor`, `hermes config
   check`, `hermes cron list --all`, the install's post-update check). A manual update runs NEITHER of
   the local tail steps the unattended updater performs: a fresh dependency environment drops the
   toolchain shim `.pth`, and a config-version migration marks the snapshot stale. Run the install's
   toolchain-shim helper and config-snapshot helper by hand after the updater returns, or the
   post-update check reports `cron worker python env: BROKEN` and `config snapshot: stale`.
4. **Give the gateway start its own tool call.** `systemctl --user stop` and `systemctl --user start`
   do not behave alike at the approval gate: a compound command tailed by the start is refused in
   full, so the stop from an *earlier* call stands and messaging stays offline while nothing else (not
   even read-only verification) ran. Never bundle the start behind other work, and if it is refused,
   say plainly that the gateway is down.
5. Judge staleness from `· upstream <sha>` against `git rev-parse origin/main`, never from the
   `(YYYY.M.D)` in `hermes --version` — that is the release's date, not the checkout's, and it reads
   "stale" on a checkout that is hours old.

Orphan divergence can be routine on a checkout tracking a force-pushed upstream: every update parks
the old tip at `refs/hermes-update-backups/orphan-main-<ts>-<sha>` before `reset --hard`. Do not "fix"
it by hand, and do not read a `merge-base` failure (unavailable in a shallow checkout) as local work at
risk. Whether upstream force-pushes daily is a per-project fact — confirm from the reflog/refs before
generalising it.

Runtime-layer preference order:

1. Agent/user instructions and local docs
2. `SOUL.md` / runtime identity where relevant
3. `$HERMES_HOME/config.yaml`
4. `$HERMES_HOME/.env`
5. Profiles under `$HERMES_HOME/profiles/`
6. Scripts under `$HERMES_HOME/scripts/`
7. Cron jobs / webhook jobs / gateway service settings
8. Hermes source only for upstream candidates or explicit hotfixes

Required source-drift triage:

1. Inspect `cd "$HERMES_HOME/hermes-agent" && git status --short` and the diff.
2. Classify each local change as:
   - upstream candidate: general, tested, intended for PR
   - local preference: convert to config/env/script and revert source
   - stale experiment: revert
3. Keep/update the install's local overrides manifest for runtime differences with why, path,
   upgrade-safety, rollback, verification command, and trade-offs.
4. Verify source is clean unless explicitly preparing upstream work.

Concrete upgrade-safe patterns:

- A chat platform's command-registration cap: prefer an `.env` policy such as
  `<PLATFORM>_COMMAND_SYNC_POLICY=off` over local source edits; verify gateway logs say the sync is
  skipped.
- Silent health automation: watchdog cron scripts should print nothing when healthy; manual `--full`
  modes can provide complete reports.
- Session pruning: export first, dry-run, and require an explicit confirmation gate such as
  `HERMES_SESSION_PRUNE_CONFIRM=yes` before deletion.
- Profile boundaries: do not casually move production gateway state between profiles; a gateway
  profile cutover needs a checklist and rollback because `HERMES_HOME` changes state roots.
- Evidence capture: write raw evidence to a low-friction inbox before polishing narratives; evidence
  capture beats elegance.

Session detail: `cases.md#upgrade-safe-maintenance-without-source-patches`.
