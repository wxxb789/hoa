# Cockpit config backup / chezmoi sync


## Cockpit config backup / sync (chezmoi / dotfiles)

When the owner wants to back up or sync the Hermes **setup** (config, skills, systemd units, contract docs) to a git repo — "configs/setups only, no data" — treat it as a config-plane extraction, not a `cp -r`. Workflow, plane lists and chezmoi naming rules: `references/chezmoi-cockpit-backup.md`.

- Sync config/identity/units and **local** skills; never data. Exclude `.env`, `auth.json`, `.copilot_jwt.json`, `vault/`, `memories/`, `sessions/`, `logs/`, `*.db*`, `state/`, `state-snapshots/`, `cache/`, `backups/`, `checkpoints/`, `installs/`, `tools/`, `node/`, cron run output, and every volatile `*_cache.json` / `*_cache.etag`. `config.yaml` is usually **secret-free** (keys resolve from `.env` via `key_env` / `${VAR}`) so it is safe to commit — scan it before trusting that.
- Classify skills before syncing anything. **Builtin** (source `~/.hermes/hermes-agent/skills/`, tracked by `~/.hermes/skills/.bundled_manifest`) and **hub-managed** (`~/.agents/.skill-lock.json`, symlinked into `~/.hermes/skills`) are **not** synced — Hermes ships the first and the hub reinstalls the second from the lock. Back up only the remaining local/imported skills plus the lock file. Runnable classifier: `scripts/classify-skills.py`.
- Build the source by **reverse-generating from live with a script**, not `chezmoi add` — `add` dereferences symlinks, chmods, and cannot express the union of `~/.hermes/skills` + `~/.agents/skills` (two real skill trees joined by symlinks).
- Pitfall: a chezmoi source that still manages a **retired** platform's paths **recreates** them on `chezmoi apply`. `chezmoi status` showing `DA`/`DB` for targets that no longer exist is the tell. Rebuild the managed set before applying; never apply a stale source onto live.
- Pitfall: the `dot_` prefix is **only** for dot targets. `dot_claw` targets `~/.claw`, not `~/claw` — a non-dot target keeps its bare name (`claw`). A wrong prefix silently manages a path nobody uses, and `chezmoi status` shows it as an `A` on a directory you never meant to create.
- Pitfall: `~/.hermes` is mode 0700 — name the source dir `private_dot_hermes` or chezmoi normalises it to 0755 and loosens a genuinely private tree. `private_` applies to that entry only, **not** to children: children render at chezmoi's `umask` default (002 → 0664/0775), which fights Hermes' own 0600/0700 and yields hundreds of `M` entries plus a mass chmod on apply. Set `umask: 0o077` in `home/.chezmoi.yaml.tmpl`; because that file is the *template* for `~/.config/chezmoi/chezmoi.yaml`, you must run `chezmoi init` (not just edit it) or it prints `config file template has changed` and changes nothing.
- `cron/jobs.json` mixes declarative definitions with volatile runtime fields, so it cannot be managed as a plain file. Commit a **sanitized** definition set as chezmoi **data** (`.chezmoidata/` is not applied) and manage the target with a chezmoi `modify_` script that merges the live runtime fields back on apply. Full recipe: `references/chezmoi-cockpit-backup.md`.
- `.chezmoiignore` is functional, not documentation: it filters the **source state** too, so any pattern matching a managed file silently un-manages it — negate (`!path`) everything you intend to manage under a broad ignore.
- `~/.hermes/config.yaml` is rewritten by Hermes at runtime, so 1-2 `M` entries between syncs is normal drift, not breakage: re-run the generator before every commit instead of chasing it.
- Pitfall: emptying the retired repo is a destructive, gated step — a shell `rm`/`mv` timeout is a NO, and `find … -exec rm` can hit the hardline blocklist outright. Take a `git tag backup/pre-rebuild-<ts>` + `tar czf` snapshot first, get explicit consent, and clear the tree with a path-asserted Python `shutil.rmtree` under `execute_code`; never retry a blocked command (see Action-Gate note under the update sections).

## The sanctioned sync pipeline (<private-repo> / chezmoi)

Config-plane changes on this host are committed by the cockpit autosync, not by hand:
`~/.hermes/scripts/dotclaw-autosync.sh` = regenerate source from live (`tools/sync-from-live.py`) →
`chezmoi apply --force` → `tools/verify.sh` gates → `git add` → safety gates → commit → fast-forward push.
A `dotclaw-autosync.timer` (every 6h) runs it; a manual run is the normal close-out after config work.

- **Never hand-edit `home/private_dot_hermes/`** — it is generated. Edit live, then run the script.
- Gates you must not "fix away": staged credential/data files are refused (`.env`, `auth.json`, `*.db`,
  `*.jsonl`, `*.log`), and **>25 deletions in one sync is refused** (that means the generator or live
  tree is wrong).
- `verify.sh` checks four things: secret patterns in source, data-plane files, nested `.git`/`node_modules`,
  and `chezmoi status` clean. When it fails, fix the generator or the live tree — not the assertion.
  Two standing false-positive sources: plugin test fixtures (skipped via `/tests/`) and the AWS docs
  example key `<aws-example-key>` (allowlisted).
- `cron/jobs.json` is never committed raw: definitions live in `.chezmoidata/cron-jobs.json` and a
  `modify_` script merges runtime fields back on apply.

## Repo auto-sync (git-as-sync data repos): diagnosing a stuck sync

<notes-repo> / <research-repo> sync via per-repo wrappers run by `repo-sync.sh` (topical skill:
`git-auto-sync-pipelines` where enabled). A wrapper fails CLOSED at preflight when untracked
files appear outside the wrapper's `ALLOWED_ROOTS` — one stray log blocks every subsequent cycle
until it is removed, while the `[ops] repo auto-sync` cron job itself keeps `last_status: ok`
(the loop prints each wrapper's failure; the job does not fail) and `suppressed duplicate alert`
lines keep the failure quiet. Diagnosis path, in order:

1. `cat ~/.hermes/cache/sync-state/<repo>.fail` — present = failing since the epoch shown;
   `.ok` = never failed.
2. `tail ~/.hermes/logs/<repo>-sync.log` — the exact preflight/gate reason, e.g.
   `paths outside allowed roots: <file>`.
3. Re-run the gates directly in the repo (unittest discover exactly as the wrapper does,
   vault.status, markdownlint) to separate "gate red" from "preflight blocked".

Rules that prevent the whole class:

- **A script or batch job that runs against a synced repo must write ALL output (logs, tail
  summaries, scratch) outside the repo** — redirect to the owning task dir. A stray log in the
  repo root blocks the sync of every legitimate change with it (fail-closed by design), and the
  backlog grows silently while duplicate alerts are suppressed.
- Removing the stray file does not sync by itself: verify the gates green, then run the wrapper
  (or wait a cycle) and confirm a fresh `committed <sha>` + `OK pushed` line in the log.

## Data plane: a profile archive is only a backup after it extracts

Config-plane sync (above) is not a state backup. Profile archives are the other half, and they
fail silently in a specific way:

- **Never `tar` a profile tree as-is.** A profile contains symlinks pointing outside itself
  (`skills/<x> → ../../../skills/<x>`, sometimes `~/.agents/skills` or a cache dir). Extraction with
  `filter="data"` refuses them (`LinkOutsideDestinationError`) and leaves you with an archive that
  cannot be restored — the failure surfaces only on the day you need it. Exclude `skills/`
  (regenerable: `profile-layer-reconcile.py` relinks from root) and never follow symlinks.
- **Copy `state.db` through SQLite, not `shutil.copy`.** `.backup()` on a read-only connection yields a
  consistent image; copying a live WAL database captures a torn one. Include `config.yaml`,
  `profile.yaml`, `SOUL.delta.md`, `memories/`, `cron/jobs.json` and `.env` (mode 0600), plus a
  `manifest.json` listing every file — that manifest is what the drill checks.
- **Run the extract drill in the same action that writes the archive.** Extract to a temp dir, assert
  every manifest entry exists, open `state.db` read-only and run `select count(*) from sessions`.
  A backup that was never extracted is a hypothesis, not a backup; report per-profile pass/fail
  (`N/N restorable`), not "backup done".
- **Rotate or it is a disk leak.** A 13-profile fleet writes roughly 250 MB per monthly run; keep the
  last 3 months and prune the rest inside the same script.
- **Deleting a profile leaves state-registry residue.** `hermes profile delete` leaves a
  `profiles/.deleted/<p>` tombstone (and sometimes an empty `profiles/<p>/` after an interrupted
  delete); the running gateway can keep logging "could not capture the retired WAL generation of …"
  until it restarts. Clean the empty dir, let audit scripts skip dot-directories, and schedule the
  restart as a normal maintenance step rather than chasing the log line.
