---
name: hermes-updates
description: >-
  Upgrade a live Hermes install and diagnose update drift: decide whether an update is worth a
  maintenance window, snapshot before mutation, run the official updater, and verify the runtime
  afterwards. Use for failed updates, stale unattended timers, dependency-sync gates, detached
  release checkouts, or post-update health checks. Not for model/provider configuration and not for
  editing the install's own source.
metadata:
  version: "0.1.29"
  areas: "software-development"
  targets: "hermes"
  kind: "entry"
---

# Hermes Updates

## When to Use

| You hear / see | Do |
|---|---|
| "upgrade Hermes", "update to latest", "are we behind?" | decide first → owner-requested upgrade |
| update failed / CLI will not start after update | failure-mode index |
| `no dependency environment is committed … run hermes pm repair` | `references/install-layout.md` |
| `hermes --version` looks old, unattended timer silent for days | `references/install-layout.md` → updater frozen |
| `hermes: a source update is unfinished` | advisory tail, no action needed |
| deciding whether new commits are worth taking | drift assessment (`references/upgrade-execution.md`) |

Load the runtime's own CLI reference (if the install ships one as a skill) for current command
syntax; load the operations skill when the task also moves config, sessions, or backups.

## Decide first

1. **Which channel?** `hermes update --check` prints the channel and the offered commit. Official
   checkouts default to `stable`; a release channel installs an exact commit, so a healthy checkout is
   **detached** (`git rev-parse --abbrev-ref HEAD` → `HEAD`). Never add a `main`-only guard.
2. **Behind what?** `git fetch --all --tags --prune`, then `git rev-list --left-right --count
   HEAD...origin/main`. Judge staleness from `· upstream <sha>` vs `git rev-parse origin/main`, never
   from the `(YYYY.M.D)` in `hermes --version` (that is the release's date).
3. **Worth doing now?** Classify commits by owner impact: gateway/platform → provider/model →
   cron/session → UI/TTS/Kanban. Core gateway or session files changed → maintenance window, not
   midday.

## Non-negotiables

- **Snapshot before mutation.** When `updates.pre_update_backup` is `false` (a configuration
  choice), `--no-backup` has no rollback unless you make one:
  `venv/bin/python -c "from hermes_cli.backup import create_quick_snapshot; print(create_quick_snapshot(label='manual-upgrade-latest', keep=3, max_file_size=1 << 30))"`.
- **Never edit Hermes source.** A dirty tree makes the unattended updater fail closed
  (`FATAL: working tree is dirty`).
- **Order:** stop gateway → `venv/bin/hermes update --yes --no-backup --branch main` → restore the
  shallow window (`git fetch --depth=10 --prune --no-tags origin main`) → re-apply the local tail →
  start gateway → post-check. A manual update runs **neither** local-tail step the unattended updater
  performs: re-install the toolchain shim and regenerate the config snapshot by hand, or the
  post-update check reports `cron worker python env: BROKEN` / `config snapshot: stale`.
- **One self-update path only**: the `systemd --user` timer. Never schedule `hermes update` from a
  Hermes cron job, and prefer an external shell over a gateway-served chat (its process can be
  drained).
- **Give the gateway start its own tool call.** A compound command tailed by the start is refused in
  full; the earlier stop then stands and messaging stays offline.
- **Running inside the gateway?** Restart from a detached unit — see the gateway operations skill.
- **Post-check even on "Already up to date"**: that path skips dependency reinstall, bundled-skill
  sync, web build, and config migration.
- **Verify the live runtime from `gateway_state.json`** (`pid`, `code_sha`, platform states), not a
  log slice.

## Failure-mode index

- `TypeError … unexpected keyword argument` mid-update → mixed `sys.modules`
  (`install-layout.md`).
- CLI hard-gated after update → dependency-sync failure (`install-layout.md`).
- `local <sha> (+N carried commits)`, timer silent for days → updater frozen by dirt
  (`install-layout.md`).
- `FATAL: checkout is not on main` → detached release checkout (`install-layout.md`).
- `a source update is unfinished` → advisory optional tail, clears next successful update
  (`upgrade-execution.md`).
- `install out of sync (venv … uv.lock)` / `dependency lock still held after 10.0s` → read
  `hermes pm status` first, then run `hermes pm install`. `venv_rebuild.ok: false` with
  `reason: "already in sync"` is healthy, and the lock line means a `pm/worker.py` sync is running
  concurrently — wait for it to exit and re-check instead of killing it.
- `hermes pm doctor` ends with `✗ python: realized bytes do not match recorded digest` → the
  toolchain artifact itself drifted (not the venv graph): `hermes pm repair` rebuilds the recorded
  dependency environment without changing it, then **restart the gateway** so sessions use the
  repaired env. This is a different fault from `install out of sync`, so `pm install` is not the fix.
  Expect `pm gc` to reclaim nothing while every store entry is referenced: `installs/*/environments`
  is live weight (one env per feature set), so disk recovery means dropping unused features, never gc.
- The unattended update unit failed with `RuntimeError: hermes update --check failed (1)` → the check
  itself shells out to `git ls-remote --tags origin` and a single slow moment at the origin (60s
  tag-lookup timeout) fails the whole night's run. Newer updater versions retry 3× with 120s backoff;
  confirm with a manual `hermes update --check`, then `systemctl --user reset-failed <update-unit>`
  (the next run would clear it anyway). Check `git ls-remote` against the repo the `origin` remote
  actually points to — that remote may be a mirror, not upstream.
- GitHub 429 / timed-out fetch → authenticated refetch, never `--filter=blob:none`
  (`upgrade-execution.md`).
- Interrupted maintenance / half-migrated state DB → `maintenance-window-recovery.md`.

## Proof

```bash
hermes --version; git -C "$HERMES_HOME/hermes-agent" status --short
hermes doctor; hermes config check
# run the install's post-update check (if it maintains one) and require "all good"
hermes cron list --all                              # no job gained an `error`
```

## References

- `references/upgrade-execution.md` — drift assessment, 429 recovery, no-op post-check, advisory tail,
  owner-requested upgrade, runtime-layer preference order.
- `references/install-layout.md` — shallow checkout, unattended timer, mixed `sys.modules`,
  dependency-sync gate, detached release channel, `REPO/venv` is not the runtime, host build deps.
- `references/upgrade-safe-local-ops.md` — why config/env/profile/script changes beat source patches.
- `references/update-execution-and-runtime-state.md`, `references/maintenance-window-recovery.md` —
  session detail.
- `references/cases.md` — historical cases: upgrade-safe maintenance, no-op update post-check,
  upstream drift assessment.
