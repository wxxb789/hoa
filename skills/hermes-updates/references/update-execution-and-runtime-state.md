# Update execution and runtime state (this install)

Depth for running an owner-requested upgrade and for reading checkout/dependency state afterwards.
Pairs with SKILL.md → "Owner-requested upgrade of a live gateway install" and "Unattended
upstream-main updates".

## Pre-state worth capturing

```bash
hermes --version                                     # vX+NNNN.g<sha> (release date) · upstream <sha>
cd ~/.hermes/hermes-agent
git status --short --branch; git rev-parse HEAD; git rev-parse origin/main
git for-each-ref refs/hermes-update-backups/ --format='%(refname) %(objectname:short)'
systemctl --user is-active hermes-gateway.service
```

`hermes --version`'s `(YYYY.M.D)` is the release's date, not the checkout's — a checkout updated
hours ago still prints an older date. Compare `· upstream <sha>` to `git rev-parse origin/main`.

## Manual upgrade of a live gateway install

1. Snapshot: `updates.pre_update_backup` is `false` here, so make it explicit.

   ```bash
   cd ~/.hermes/hermes-agent && venv/bin/python -c "from hermes_cli.backup import create_quick_snapshot; \
   print(create_quick_snapshot(label='manual-upgrade-latest', keep=3, max_file_size=1 << 30))"
   ```

   Restore later with `hermes_cli.backup.restore_quick_snapshot(<id>)`; the directory is
   `~/.hermes/state-snapshots/<id>`.
2. Stop the gateway, then `venv/bin/hermes update --yes --no-backup --branch main` from
   `~/.hermes/hermes-agent`. The updater owns code, Python deps, Node, the TUI build, the web build,
   bundled-skill sync and config migration; `--no-backup` is only correct because step 1 exists.
3. Restore the shallow window (below), re-apply the local tail the unattended updater owns, start the
   gateway, then run the post-check loop. `venv/bin/hermes update` runs NEITHER tail step that
   `hermes-auto-update.py` + the post-check perform, so do them by hand or the post-check fails:
   - `python3 ~/.hermes/scripts/hermes-toolchain-shim.py` — a fresh dependency environment drops the
     toolchain `.pth`, so `post-update-check` reports `cron worker python env: BROKEN` (same class as
     the restart-safe cron-worker breakage).
   - `python3 ~/.hermes/scripts/config-snapshot.py` — a config-version migration (the updater prints
     `Updating config format (vN → vN+1)`) marks the snapshot stale.

### The gateway start needs its own call

Stopping the service may pass an approval gate while *starting* it raises one. A compound command
whose tail is `systemctl --user start <unit>` is refused as a whole when that prompt times out, so:

- the `stop` issued by an earlier call stays in effect → messaging is offline;
- none of the other work in that command ran, not even the read-only checks.

Issue the start alone, verify with `systemctl --user is-active` plus fresh journal connection
markers, and if it is refused, tell the owner the gateway is down in the same message. Never retry
or rephrase a blocked command, and never leave a stopped gateway unannounced. A refused approval is
a NO for the moment, not forever: once the owner explicitly authorizes (`go ahead`, `do it
yourself`), issuing that same start command again is consent, not a retry of a refusal.

## Checkout state: shallow window and divergence

- The unattended updater asserts a depth-10 shallow checkout: `git rev-parse --is-shallow-repository`
  is `true` and `git rev-list --count HEAD` is `10`. A manual upgrade leaves the repo with full
  history (tens of thousands of commits, no `.git/shallow`), which fails those assertions.
- Restore it after any update, manual or automatic:
  `git fetch --depth=10 --prune --no-tags origin main`, then re-check both invariants.
- `hermes update --check` is not read-only for the checkout: it prunes and re-creates shallow grafts,
  and its "N commits behind" is computed against that depth-limited graph. An observed run reported
  "79 commits behind" while `git rev-list --count HEAD..origin/main` was 1. Use the deployed version
  string and `git log HEAD..origin/main` for real counts.
- **Orphan divergence is the normal state here.** `refs/hermes-update-backups/orphan-main-<ts>-<sha>`
  accumulates one ref per update: upstream force-pushes `main` about daily, so HEAD shares no common
  ancestor with `origin/main`. `git merge-base` returns nothing in a shallow checkout, and
  `merge-base --is-ancestor` reports non-fast-forward. All of that is expected; the updater parks the
  old tip behind the rescue ref and `reset --hard`s on purpose. Do not pre-empt it with a hand reset,
  and do not describe the abandoned commits as the owner's work without checking their authors.

## Dependency environment, and why a child can lose it

The gateway runs on the PM-managed toolchain interpreter (`~/.hermes/tools/python-<ver>.../bin/python3`;
`ExecStart` → a repo launcher that re-execs it with `-I -c <bootstrap>`). That interpreter's own
site-packages holds only `pip`; Hermes' third-party deps reach the parent because the launcher path
puts the committed dependency environment on `PYTHONPATH` (consumed into `sys.path` at interpreter
startup) and the bootstrap then pops the variable from `os.environ`.

Children spawned from the sanitized subprocess env deliberately lose those `PYTHONPATH` entries. That
is harmless when the child's interpreter is the venv python (deps are native) and fatal when it is
`sys.executable` on the toolchain interpreter. The restart-safe cron worker is exactly that shape:
`sys.executable -m cron.scheduler` with a sanitized env plus a pinned repo root.

Symptom to recognise rather than debug from scratch: a script-mode job reports
`ModuleNotFoundError: No module named 'ruamel'` (or any third-party package) with the traceback inside
`cron/...`, while the gateway, the CLI and agent-mode jobs are healthy.

Diagnosis, cheapest first:

1. `hermes cron list --all` — the failing job shows `(N failures in a row)` and the worker's stderr
   tail inline. This is the only surface for a silently failing scheduled job; read it during every
   post-update review.
2. `journalctl --user -u hermes-gateway --since "<date>" | grep -n "No module named"` — the first
   occurrence separates "this update caused it" from "it predates the current version", and an
   interval equal to the job's schedule confirms it is every run, not a flake.
3. Reproduce the child's import view:
   `<toolchain python> -I -c "import os, sys; sys.path.insert(0, os.path.expanduser('~/.hermes/hermes-agent')); import hermes_yaml"`.
4. `venv/bin/python -c "import ruamel.yaml"` succeeding while step 3 fails confirms an environment
   split, not a missing package — do not "fix" it by pip-installing into the toolchain interpreter.
5. Re-test after the next update before treating it as durable; a PM/runtime rework can change how
   the dependency environment is located.

Treat a same-shaped failure in the *parent* (gateway or CLI) as an unrelated dependency-install
problem and follow the `hermes pm repair` path in SKILL.md instead.

## Verifying the unattended updater

To answer "does the auto-upgrade actually work", exercise it — never judge from a green timer.
`systemctl --user start hermes-auto-update.service` runs the real script under systemd (`Type=oneshot`,
blocks to completion; it sleeps `HERMES_AUTO_UPDATE_START_DELAY` first). Both outcomes are PASS:

- **Already current**: journal prints `already current at <sha>; no restart`, the gateway PID is
  UNCHANGED, and the script still re-applies the toolchain shim. Assert the PID before and after.
- **A real update**: journal prints the step markers (`UPDATE SUCCESS: <old> -> <new>`,
  `Discord and Feishu connected`, `ghc-proxy is healthy`, `model probe passed`), the gateway PID
  CHANGES (it stopped and restarted the unit), `refs/hermes-auto-update/rollback` is ABSENT afterwards,
  and a fresh `logs/update_receipts/update_*.json` shows `outcome: success` with every stage `success`.
  On failure the script rolls back and the rollback ref stays.

Because upstream moves during the day, "already current" is not guaranteed — a manual trigger can pull
a real update and restart the gateway. Report which path ran rather than assuming the no-op one.
