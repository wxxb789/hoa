# Install layout, checkout shape, updater failure modes


## Main-only shallow Hermes checkout

Use this when a runtime checkout should track only upstream `main` while minimizing Git disk use.

Facts and policy:
- Git has no recognized `fetch.depth` config key. Do not write a placebo setting.
- Narrow the refspec with `remote.origin.fetch=+refs/heads/main:refs/remotes/origin/main`, set `remote.origin.tagOpt=--no-tags`, enable pruning, and keep `branch.main` tracking `origin/main` with `pull.ff=only`.
- A shallow repo remains shallow, but ordinary fetches can accumulate commits above the old boundary. Define an explicit local alias such as `git sync-main` that runs `git fetch --depth=10 --prune --no-tags origin main`, switches to `main`, and resets hard to `origin/main`.
- Hermes' own passive shallow update checks may use `--depth 1`; this saves more disk but can reduce the retained window. `git sync-main` restores the requested depth-10 window.

For a previously full, partial-clone checkout:
1. Check for local changes and `refs/stash` before destructive cleanup. Stashes are user data; get confirmation before deleting.
2. Remove stale remote-tracking refs and tags only when the user requested main-only operation.
3. If `git gc` fails with `bad tree object`, old refs/stashes may point to fork-only objects while `origin` is the only promisor. Stale index or commit-graph caches can add noise. Do not keep retrying GC blindly.
4. The clean recovery is to clone a fresh `--filter=blob:none --depth=10 --single-branch --branch main --no-tags` repository into a temporary sibling, verify it, then atomically replace only the old `.git` directory. This preserves the runtime working tree, ignored `venv/`, and Hermes state outside `.git`.
5. Before cloning, `unset GIT_NO_LAZY_FETCH`; a diagnostic export can persist across terminal calls and cause checkout failure after an otherwise successful partial clone.
6. Reapply local remotes/config, reset to `origin/main`, then delete the old `.git` only after verifying clean status, shallow=true, depth=10, HEAD==origin/main, two origin refs (`HEAD`, `main`), zero tags/stash, and successful `git fsck --connectivity-only` plus `git gc`.
7. Restart the gateway after source HEAD changes so systemd loads the new code; verify messaging connections from fresh logs.

### Unattended upstream-main updates

Use an external `systemd --user` timer, not Hermes cron: the gateway-hosted cron scheduler must not be responsible for replacing and restarting its own runtime.

Safe pattern for a live messaging gateway:
1. Schedule in the owner's explicit timezone. Prefer `Persistent=false` when a missed-run catch-up during work hours would be disruptive.
2. If another dependency restarts at the same minute (for example a local model proxy), order after its unit, add a short startup delay, and verify its real health endpoint before updating.
3. Acquire a file lock, require a clean `main` checkout, and fetch only `origin/main` with the intended shallow depth/tags policy.
4. If HEAD already equals `origin/main`, exit 0 without touching the gateway. Verify this by checking that the gateway PID is unchanged in a manual systemd-run test.
5. Before mutation, keep the old commit alive under a temporary rollback ref and create an official quick snapshot with `hermes_cli.backup.create_quick_snapshot(label='auto-update', keep=1, max_file_size=1 << 30)`. The helper uses SQLite's backup API and captures config, credentials, cron/pairing state, and profile state according to Hermes' current snapshot contract.
6. Stop the gateway only after an update is confirmed. Run the official `hermes update --yes --no-backup --branch main` from the stopped runtime; `--no-backup` is correct here because the script already created and recorded the official quick snapshot.
7. Restore the desired shallow window with a scoped depth fetch. If upstream moved again during dependency installation, rerun the official updater so the venv always matches the final HEAD; bound retries.
8. Verify clean tree, shallow/depth invariant, config check, gateway active state, fresh Discord/Feishu connection markers, the local proxy health endpoint, and one real model probe.
9. On failure, stop mutation and inspect the update receipt, committed dependency selection, and state/schema migration status before choosing recovery. A source rollback ref and SQLite snapshot are separate recovery assets, not proof of a compatible downgrade. Before state migration, recover only a verified compatible code/dependency/state set using the install's current dependency manager. After migration, prefer repairing the new version; downgrade only after proving old-code compatibility or verifying a complete consistent pre-migration restore. If compatibility cannot be established, preserve evidence and report the gateway state rather than blindly resetting the SHA and starting it. Remove the rollback ref only after verified recovery.
10. Validate the actual unit with `systemd-analyze --user verify`, manually run both update and no-update paths, then inspect `journalctl`, timer next-run state, HEAD==origin/main, depth, rollback-ref absence, and gateway health.

Keep operational scripts under `~/.hermes/scripts/` and units under `~/.config/systemd/user/`. Log to journald; do not silently claim success from timer enablement alone.

### Unattended updater silently frozen by source drift

A dirty worktree does not just block one update — the unattended updater **fails closed and stays failed**. A truncated `.npmrc` blocked every 04:00 run for nine days while nothing surfaced except a journal line:

1. Suspect it whenever `hermes --version` prints `local <sha> (+N carried commits)` or the date looks stale; `hermes update --check` is not the only signal.
2. Read `journalctl --user -u hermes-auto-update --no-pager | tail -40` — look for `FATAL: working tree is dirty; refusing unattended update`.
3. Classify the offending path (upstream candidate / local preference / stale drift) before reverting; a plain `git checkout -- <path>` is only correct once you know it is drift.
4. After clearing the tree, verify the next run rather than assuming the fix landed; the timer keeps its own schedule.

### `Mixed sys.modules` when the updater pulls code into its own process

When `hermes update` runs while the checkout is behind, the process that pulls the new code still holds the old modules. A signature changed upstream then surfaces as a confusing `TypeError` (observed: `_find_stale_dashboard_pids() got an unexpected keyword argument 'scope_home'`) and the update aborts — usually after rolling back correctly. It is **not** an upstream bug: verify by checking that the definition and the call site agree on `origin/main` (`git grep` both).

Recovery that works, because every step is a fresh process:

1. `systemctl --user stop <gateway unit>` (never mutate the tree under a running gateway).
2. `git fetch --depth=10 --prune --no-tags origin main && git reset --hard origin/main`.
3. Reinstall deps exactly as the updater does: `VIRTUAL_ENV=$PWD/venv PATH=$PWD/venv/bin:$PATH uv pip install -e ".[all]"`.
4. `venv/bin/python -c "from tools.skills_sync import sync_skills; print(sync_skills(quiet=True))"`.
5. Re-run `venv/bin/hermes update --yes --no-backup --branch main` — this no-op path is what performs the pending **config-version migration** and toolset additions.
6. `hermes config check`, start the gateway, then verify `gateway_state.json` (`code_version`, `served_profiles`, platform states) and one model probe.

Hermes itself detects the stale-module condition and prints `Gateways may still be serving pre-update modules (mixed sys.modules)`; treat that message as an instruction to restart, not as cosmetic.

### Update that fails in dependency sync hard-gates the whole CLI

When `hermes update` pulls source but its dependency sync fails, the install is not left where it
was: every launcher-mediated `hermes` command except the `pm` subcommands refuses to start with
`no dependency environment is committed for this install; run `hermes pm repair``. Diagnose with
`hermes pm ...`, plain file reads, `git`, `ps`, and `journalctl` — `hermes doctor`, `hermes --version`,
and `hermes update` itself are all behind the same gate and cannot help you here.

Evidence trail, most useful first:
1. `hermes pm status` and `~/.hermes/logs/update_receipts/latest.json` plus the newest `update_*.json`
   — read `outcome`, `stop_reason`, `steps[].detail`, and the `pre_update` / `post_update` shas.
2. `~/.hermes/logs/update.log` tail — where the run stopped, and the last line that printed OK.
3. `journalctl --user -u hermes-gateway --since "2 hours ago" | grep -iE 'update|dependenc|uv sync'`.
   Each new CLI or gateway start retries the pending dependency completion, so the same failure
   repeats on every startup with the reason inline.
4. `ps -eo pid,ppid,etime,cmd | grep -E 'pm/worker|gateway run'` and `~/.hermes/.hermes-update-in-progress`.

Pitfalls:
- `.hermes-update-in-progress` is created and deleted by each completion attempt, so it can appear
  and vanish between two commands. Its absence does NOT mean no update is pending — trust the
  receipts and the process list.
- A failed dependency step leaves a **mixed runtime**: the gateway usually stays up, running the NEW
  source against the OLD committed dependency set, and journals exactly that (`running with the
  previous dependencies`, `Gateways may still be serving pre-update modules`). "Gateway active" is
  not "install healthy".
- The gate does not roll the source back, so `git log` can show the new HEAD while the CLI is dead.

Recovery order:
1. Read the sync failure detail before touching anything. If it names a missing build tool, satisfy
   that first: a dependency that compiles a C/C++ extension is the usual cause (`python-olm`, pulled
   in by `mautrix[encryption]` via the `matrix` extra), and the compiler it demands is not
   necessarily the platform default — `clang++` was required on a host that already had gcc/g++. Read
   the named binary literally instead of assuming "a compiler is installed".
2. Two fixes: install the named build tool, or drop the extra that pulls the package. Prefer
   installing the build tool — it leaves the recorded dependency graph unchanged, and a dropped
   extra silently removes a feature the owner may use.
3. `hermes pm repair` — rebuilds the recorded dependency environment without changing its graph.
   This is the command the gate itself prints.
4. `hermes update` — pulls the remaining commits and restarts the gateway so no process keeps
   serving the mixed state.
5. Verify with the post-check loop above (`hermes --version`, `hermes doctor`, `git status --short`,
   `python3 ~/.hermes/scripts/post-update-check.py`), not with the updater's own exit line.

- The unattended `hermes-auto-update.timer` retries this whole path at its next run, so a failed
  manual upgrade heals itself once the build dependency exists. Offer that as the zero-effort option
  — but say plainly that the CLI stays gated until then.
- Steps 2-4 rebuild the venv and restart the gateway. They need the owner's explicit go-ahead, and a
  command-approval prompt that times out is a NO: report the diagnosis, the exact commands you intend
  to run, the rollback path (previous `installs/<id>/pm-runtime/generations/` entry, package-removal
  for any compiler you installed), and wait. Never retry or rephrase the blocked command.

### Release channels leave a DETACHED checkout — a `main`-only guard goes silent

A source install selects its channel per install (`hermes update --check` prints it;
`--set-channel` persists it under `update.installs.<id>`; official checkouts default to
`stable`). A *release* channel installs an exact release commit, so a healthy checkout is
detached: `git rev-parse --abbrev-ref HEAD` answers `HEAD`, not `main`.

Any automation that requires `main` therefore fails closed forever, with no user-visible
trace beyond a failed systemd unit and one journal line. Measured here: **ten days** of
nightly `FATAL: checkout is not on main` while the code sat 4086 commits behind.

- Fix the guard, never the channel: accept `main` **or** `HEAD`, and refuse only a real
  foreign branch.
- Resolve the update target from `hermes update --check` (parse `available: … (<sha>)`,
  treat `Up to date` as current) — not from `origin/main`, which a release checkout never
  equals. Raise on an unparseable result instead of guessing "no update".
- Run the official updater as `hermes update --yes --no-backup --channel <ch>
  --no-gateway-restart`, then stop/start the gateway yourself and verify. Do not let it
  own the fleet restart while debugging — its own post-update gateway verification is the
  check that misfired (reported both channels connected as missing) and rolled a good
  update back, which is what detached the checkout in the first place.
- Post-checks that survive a channel switch: tree clean, `HEAD` startswith the release
  sha, `update --check` no longer offers an update. Drop `origin/main` equality and the
  old shallow/depth-10 assertions — a release checkout is neither.

### `REPO/venv` is not the runtime (PM installs)

On package-manager installs `~/.hermes/hermes-agent/venv` can be a legacy shim whose
interpreter imports `installs/<id>/environments/<hash>/workspace`, a **stale mirror** of
the checkout (observed: 375 differing files under `agent/`, `hermes --version` still
printing the new version off the stale `VERSION` file). Helpers run through it execute
old code — snapshots, bundled-skill sync and model probes all silently used it.

- Run python helpers with the newest `~/.hermes/tools/python-*/bin/python3` and
  `PYTHONPATH=<repo>`; the launcher pops `PYTHONPATH` itself, so `hermes` CLI calls are
  unaffected by the export.
- Call the `~/.local/bin/hermes` launcher for `hermes …`; never `<repo>/venv/bin/hermes`.
- Rebuild dependencies with `hermes pm repair` (keeps the recorded graph). Do **not**
  `uv pip install -e .` with `VIRTUAL_ENV=<repo>/venv` — that writes into the stale shim.
- Prove it: `PYTHONPATH=<repo> <toolchain-python> -c "import hermes_cli; print(hermes_cli.__file__)"`
  must point inside the checkout, not `installs/.../workspace`.
