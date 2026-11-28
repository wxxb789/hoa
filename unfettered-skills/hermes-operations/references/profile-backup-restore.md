# Restorable profile backups

A backup you have never extracted is a hypothesis. Profile homes contain absolute symlinks
(`skills/<entry> -> ../../.agents/skills/<entry>` or `../../../skills/<entry>`), so a plain
`tar czf profile.tar.gz profiles/<p>` produces an archive that **cannot be restored**: extracting with
`tarfile.extractall(filter="data")` raises `LinkOutsideDestinationError: … would link to
/home/<user>/.hermes/cache/scratch/skills/…, which is outside the destination`.

## Scheduled generation subsystem (the live path)

The scheduled backup path is a generation producer/verifier pair, not a hand-rolled tar job:

- **Modules**: `~/.hermes/scripts/hermes_health.py` (daily read-only health) and `hermes_recovery.py`
  (subcommands `produce` / `verify` / `weekly`). Jobs: monthly producer (`hermes-recovery-produce.sh`,
  03:30 on the 1st), weekly verifier (`hermes-recovery-weekly.sh`, Monday 08:00), daily health
  (`hermes_health.py`, 05:00). The cron `script` field is a bare filename, so every frozen path lives
  inside the wrappers.
- **Frozen policy** (`~/claw/backups/profiles/recovery-policy-v1.json`): mandatory for every
  produce/verify/weekly call; never reconstructed from an archive or inferred from a missing live
  store. Build it programmatically from a live inventory — walk the module's `SCHEMAS` / `BASE` /
  `DREAM` component sets with `is_file()` per home. Hand-transcribed policies drift, and a
  `cache/dream-*` glob misses `cache/dream.json` (no dash). Components other than `state.db` /
  `config.yaml` may be registered `uninitialized`, which requires an `evidence` reference (owner
  disposition + deletion receipts + auto-recreate observation).
- **`policy-stale` is a tripwire, not a fault**: when a component registered `uninitialized` later
  appears (e.g. a home auto-recreates its fact store on its next write), produce fails `policy-stale`
  on purpose. Verify the appearance is legitimate, then refresh the policy deliberately; never
  auto-downgrade the policy and never manufacture an empty store to buy a green run.
- **Generations**: one `generation-<utc-stamp>/` per produce under `~/claw/backups/profiles/`, with
  per-home `<home>.tar.gz` + portable `sessions-full.jsonl` + `manifest.json`; the `COMPLETE` marker
  is written only after all steps AND an internal verification pass succeed. The weekly verifier
  always uses the newest COMPLETE generation — a damaged newest generation fails visibly and never
  silently falls back to an older healthy one. Budget ~423MB per generation with a ~500MB root
  `state.db`.
- **Exit semantics**: produce exits non-zero when the generation is incomplete (a failed monthly
  backup SHOULD raise a cron failure incident); weekly exits 0 with changed findings on stdout —
  detection is success, silence is healthy.
- **Sizing**: each item runs in a subprocess bounded by `--item-timeout` (default 120s — raise to
  600–900 for homes with multi-hundred-MB `state.db`). A full produce takes minutes: run it in the
  background and verify the COMPLETE marker afterwards.
- **Rotation is deliberately unwired**: generations accumulate until a separately reviewed
  future-only rotation boundary is added. The new job never touches the legacy month-dirs
  (`YYYY-MM` / `YYYY-MM-DD-*`) beside it, and the retired scripts (`profile-backup-cron.sh`,
  `session-housekeeping.py`, `hermes-health-daily.py`, `memory-hygiene.py`,
  `profile-backup.py`) stay on disk unscheduled as rollback units — deleting or rescheduling them
  needs an owner decision. (`hermes-full-audit.py` left this list on 2026-11-14: it was archived
  to `~/claw/backups/scripts-archive-20261114T190911/` and is no longer on disk.)

## What to include

| Include | Why |
|---|---|
| `config.yaml`, `profile.yaml`, `SOUL.delta.md` | the actual configuration and overlay |
| `memories/` | user notes the owner cannot regenerate |
| `cron/jobs.json` | the routine set, including disabled/paused jobs |
| `.env` (chmod 600) | credentials the profile needs to boot |
| `state.db` via `sqlite3.Connection.backup()` | consistent session snapshot; a plain file copy can capture a torn WAL |
| Authoritative provider DB, e.g. `memory_store.db`, when initialized | primary facts/history/tombstones are not restored by markdown or config sync |
| `dreaming.json`, non-regenerable proposal/cursor state, `pending/memory/` when in approved scope | preserve memory lifecycle and outstanding human approvals |

| Exclude | Why |
|---|---|
| `skills/` | symlinks into root `skills/`; `profile-layer-reconcile.py` rebuilds them |
| Regenerable plugin code, caches, checkpoints, sandboxes and redundant exports | exclude only after separating code/cache from non-regenerable proposals, cursors and approval state |

## Procedure (manual / legacy fallback)

```bash
python3 ~/.hermes/scripts/profile-backup.py <profile> [...]     # or --all
python3 ~/.hermes/scripts/profile-backup.py --verify <archive>  # drill: extract + read state.db
```

For the scheduled path, run the wrappers in `~/.hermes/scripts/` (or `hermes_recovery.py` directly
with the frozen policy) instead — this manual flow is the fallback for one-off, pre-cutover, or
single-profile backups.

1. **Declare recovery scope before copying.** Record required components, provider/cache policy and
   initialization state independently of successful copies. Require explicit consent for expanded
   credential/fact/approval coverage. Protect staging directories and whole archives, not only `.env`.
2. **Snapshot and package.** Use SQLite backup APIs for initialized databases; record snapshot failures
   as failures, never omit them from the required manifest. Include file list, component states, source
   and snapshot identity. Preserve all existing approval records; do not restore over live homes.
3. **Verify independently in private scratch.** Assert required files exist, integrity checks pass and
   `state.db` answers `select count(*) from sessions`; initialized fact stores must answer their own
   schema/read checks. Return failure when any required DB is missing/unreadable. A green tar extraction,
   empty manifest, warning-only `db_ok=false`, or producer success is insufficient.
4. **Probe the verifier itself.** Build task-local synthetic archives with a declared-required missing
   DB, corrupt DB, and valid DB control; call the same production `verify()`/`--verify` path. Expect
   reject/reject/accept. Set `sys.dont_write_bytecode = True` before importing live helpers and keep all
   fixtures/extraction under the configured scratch/task directory; never copy real private data merely
   to demonstrate a verifier defect. A reproduced false green is a finding, not a repaired verifier.
5. **Combine required stages with AND.** If packaging and portable session export share a schedule,
   preserve separate artifacts and `{step, ok, artifact, error}` results. A required skip/timeout/failure
   cannot be hidden by a later success. Healthy monitors may have empty stdout; artifact producers are
   judged by required artifacts and status, not silence alone.
6. **Retain and observe.** Keep approved cadence/rotation, remove only approved old generations after
   verifying the new one, and do not equate config push with data recovery. A separately executed verifier
   owns its verdict; reusing an existing job is possible. Report first scheduled proof and RPO limits
   separately from synthetic-test results.

Do not infer lost facts from an absent never-initialized store, nor infer the provider is disabled from
legacy markdown-cache flags alone. Record disabled/uninitialized components explicitly; losing a store
known to have existed fails closed. Do not create empty replacement DBs to manufacture recovery success.
Preserve an exact private config backup for rollback; redacted reports are not restorable configs.

## Missing stores and WAL preservation

- Establish initialization history from the exact home's durable tool-result database path, prior snapshots and deletion receipts; current absence or zero facts does not prove never-initialized. Separate deliberate prior retirement from current provider intent. A restored empty database proves structural recovery, not recovery of historical facts.
- Preserve orphan WAL/SHM before opening or recreating a missing main DB. Inspect open file generations, then copy stable sources to private evidence with inode/size/mtime and before/after hashes. Never remove source sidecars by default. Stop for separate writer/quiescence authorization when generations are changing or ordering is ambiguous. **Sanctioned removal** requires ALL of: the main DB is absent (nothing left to checkpoint), quiescence confirmed (`fuser` reports no open handles), a private-scratch reconstruction proved the sidecar's recoverable content is empty, the owner granted this exact live write naming the owning home, and both files are backed up with recorded sha256 — then record the grant and the rollback (restore the copies) in the task ledger.
- Reconstruct from a WAL only in private scratch, only after validating header/frame checksums, salts, the last committed frame and complete page coverage. Require SQLite integrity/schema checks; missing pages are a blocker, not permission to invent them. A valid scratch candidate is not permission to install it into a live profile.
- Key backup names by owning home as well as filename. Flattening several profiles' `memory_store.db` into one directory overwrites earlier copies and destroys attribution; an unattributed surviving copy is not a valid restore source for every home.

## The boot drill (integrity verification is not a restore proof)

`verify()` proves the archive is complete and internally consistent. It says nothing about whether the
home can serve a turn. Run the boot drill on a real generation before reporting a restore path as
working:

```bash
G=~/claw/backups/profiles/generation-<ts>
S=~/.hermes/profiles/drill-restored        # MUST live under profiles/ — see the trap below
rm -rf "$S" && mkdir -p "$S" && tar xzf "$G/<home>.tar.gz" -C "$S"
printf 'name: drill-restored\ntitle: drill\npaused: false\n' > "$S/profile.yaml"
hermes -p drill-restored chat -q "Reply with exactly: DRILL_OK" --oneshot -t clarify -Q
# integrity, against the generation's own manifest:
python3 - <<'PY'
import hashlib, json, pathlib
h = pathlib.Path.home()/".hermes/profiles/drill-restored"
m = json.loads((h/"manifest.json").read_text())
print({r: hashlib.sha256((h/r).read_bytes()).hexdigest() == m["files"][r] for r in ("SOUL.md", ".env")})
PY
rm -rf "$S"
```

Pass criteria, all three: the model answers `DRILL_OK`, `SOUL.md`/`.env` hash-equal the manifest, and the
restored `state.db` answers `select count(*) from sessions` with the pre-drill count plus one. A restored
home that answers with its **own** configured model (not the front door's) is extra proof that config
came along.

- **Profile identity comes from the directory position, not from metadata.** A home extracted anywhere
  else and driven with `HERMES_HOME=<dir> hermes chat …` fails as `Gateway could not start … one gateway
  per host serves every profile`: the CLI resolves it to `default`, sees the host gateway already serving
  that name, and refuses to serve a second one. `profile.yaml: name:` and a `HERMES_PROFILE` override do
  not change it — only `~/.hermes/profiles/<name>` does.
- **Deleting the drill home leaves a phantom profile.** `hermes profile list` keeps the row, and
  `gateway_state.json: served_profiles` keeps the name until the gateway is restarted; the daily digest
  then reports `acquisition … unknown` for it every day. Do the drill when a restart window already
  exists, or plan one (restarting production is an owner decision, not a cleanup step).

## Cleaning up old backup trees (only-copy test, recorded deletions)

Backup dirs accumulate one-off snapshots that no rotation owns. Size is not the criterion; **supersession**
is. Delete only when a live or strictly newer artifact covers it, and keep anything that is the only copy:

| Delete | Why it is provably redundant |
|---|---|
| A pre-upgrade copy of a tree whose canonical owner is now a repo (skills → hoa / bundled checkout) | the repo is the source of truth and regenerable |
| One-off `YYYY-MM` / `YYYY-MM-DD-*` home snapshots duplicated inside themselves | two retained generations cover current state |
| Tarballs of deliberately retired bots/homes | retirement is decided and recorded; nothing restores to them |
| A cache-like payload inside a backup (a browser profile dir, package caches) | not a recoverable asset at all |

| Keep | Why |
|---|---|
| Retired homes' state DBs when their data was merged rather than copied | the merge is not re-derivable |
| Raw evidence belonging to reports that were promoted into the vault | promotion keeps conclusions, not the evidence tree |
| The single `skills.tar.gz` rollback copy replicated across homes | dedupe the replicas, never the last one |

Procedure: `grep -rn <path> ~/.hermes/scripts ~/.hermes/skills ~/claw --include=*.py --include=*.sh
--include=*.md` (no reference ⇒ no consumer) → measure `du -sm` → delete → record the path, size and the
superseding artifact in a `DELETIONS.md` beside the batch → verify with `df` before/after, not with `du`
alone. Batches live in `~/claw/backups/cleanup-YYYYMMDD/`, which also holds the rollback copies of
anything moved rather than deleted, so one retention rule covers both.

**Retention is a job or it regrows.** `~/.hermes/scripts/daily-hygiene.py` deletes `cleanup-YYYYMMDD`
sets older than `--keep-days` (default 30) and prunes duplicate skill trees; the daily digest calls it. It
must stay outside `hermes_health.py`: that checker is read-only by contract, and a mutation inside it
makes every verdict it reports suspect. The digest announces a deletion (irreversible action needs an
audit line) and stays silent when it only pruned a regenerable copy.

## Pitfalls

- **A tree that only grows is not a backup strategy.** Every batch needs a retention rule and every
generation needs a verifier; without both, the disk fills with copies nobody has proven restorable, and
the newest one silently becomes the only candidate.- `tarfile` with `filter="data"` is what *exposes* the symlink problem; switching to
  `filter="fully_trusted"` to make extraction "work" hides a broken archive instead of fixing it.
- Backing up `state.db` with `cp` while the gateway runs copies a mid-checkpoint file; use the SQLite
  backup API (or `VACUUM INTO`) even for read-only sources.
- Deleting a profile does not delete its backup: keep the tarball until the retirement is no longer
  reversible.
- `~/.hermes` size is dominated by `installs/`, `cache/uv` and `cache/scratch`, not by profiles — measure
  `du -sm ~/.hermes/*` before proposing to trim profile homes.
