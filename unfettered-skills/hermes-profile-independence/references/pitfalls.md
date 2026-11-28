# hermes-profile-independence — pitfalls

Load this before touching a live home, deleting a backup tree, or renaming a profile.
Every item here cost a real session; none of it is theoretical.

## Pitfalls（原 SKILL.md）

- **A line that owns its contract must stop naming the other line's file inside the block.** The repo
  portability check rejects host paths in tracked files, so an invariants copy seeded from the host still
  carries `~/.hermes/contracts/...` in its markers and heading — rewrite those two lines repo-relative
  (`bots/roles/_invariants.md`) and keep the block markers intact. Contract copies legitimately name
  harness and tool tokens, so exempt *those two paths* from the token rule while the host-path rule keeps
  applying; a blanket waiver loses the check for every skill.
- **Architecture change ⇒ the checker's declarations are a second artifact.** Moving symlink farms to
  per-home copies and retiring `SOUL.delta` leaves `hermes_health.py` describing the old topology: 215
  `symlink-remains`, 29 whitelist, plus `delta … unavailable` per home — hundreds of findings that mute
  the "silence means healthy" signal. Reconcile the declarations **and** clear the stale entries from
  `cache/hermes-health-v2-state.json` in the same change, then prove `--no-state` prints nothing on a
  healthy install plus exactly one finding per injected defect.
- **Never reformat a home's `config.yaml` with a greedy multiline regex.** `(?ms)^model:\n(?:  .*\n)+`
  matches from `model:` to end of file, not to the end of the block: a 23 KB cloned config collapsed to
  110 B and only a post-write byte-size/`yaml.safe_load` check caught it. For a single home use
  `HERMES_HOME=<home> hermes config set <key> <value>`; when text surgery is unavoidable, anchor on the
  exact block text and re-parse the file afterwards.
- **`hermes chat` dispatch is a gateway child, not a process you own.** A long `--query-file --oneshot`
  run survives as a process but its turn rides the gateway, so a scheduled restart lands mid-run and the
  log ends with `Gateway disconnected; turn outcome is unknown` plus a resumable session id. The work is
  usually half-done on disk (an auto-sync may already have committed it): reopen the tree, diff against
  the spec, finish the remainder — do not re-dispatch the whole job. Dispatch long refactors through
  `systemd-run --user --collect --unit=<name> /bin/bash -lc 'hermes chat --query-file … > run.log 2>&1'`
  and record `systemctl --user is-active <name>.service`, so a restart cannot take the work with it.
- **A renamed home must be re-verified through `--check`, not by the move's exit code.** Profile
  discovery is per-directory, so a half-renamed fleet still starts: `profile-soul-deinherit --check`,
  `profile-skill-materialize --check` and `contract-drift-check` are what prove the new id is real.
- POSIX has no "read-only byte range": the head block is protected by *verification*, not by file mode.
  A markdown formatter or a full-file rewrite can still break it — `--check` must catch it daily.
- **`.archive` / `.curator_backups` inside a profile's `skills/` are per-home state; they are carried
  across the swap and can dwarf the live skill size (67 MB vs 0.6 MB live). Do not read `du` as skill weight.
  The usual cause is one `skills.tar.gz` snapshot of tens of MB replicated into every home: before
  deleting replicas, copy a single artefact outside the homes (a `~/claw/backups/skills-archive/`-style
  dir) so exactly one rollback copy survives — the replicas are what the `find -delete` should hit.
- **Usage counters travel with a copied skill tree.** `skills/.usage.json` (`use_count`,
  `last_used_at`) and `.curator_ledger.jsonl` are copied into every receiving home, so a freshly
  materialized home shows the source home's history. Never prune that home's `allowed_skills` on
  "never used" inside the first evaluation window — verify the counters are that home's own before
  quoting them, and say so when reporting a usage-based recommendation.
- **N homes means N versions of the shared identity prose.** The generic (non-role) section of every
  SOUL is a hand-maintained copy: hash it per home before editing a rule that is supposed to be common
  (`md5` of the body between the core-invariants block and the role heading) — divergent hashes mean the
  rule already exists in several wordings, so fix the mechanism (contract block, rule 3) or edit every
  home and re-compare, rather than patching the one home in front of you.
- `hermes skills list` reads disk per HERMES_HOME, so it verifies materialization without restarting
  the gateway; the gateway only needs a restart to drop its cached prompt/skill snapshot.
- `<private-repo>` sync must include `profiles/*/SOUL.md` and `skills.lock.json`; a sync list that only
  carries `SOUL.delta.md` silently leaves the authoritative identity unversioned.
- **Each `--apply` used to leave a fresh `skills.bak.<ts>` behind**; with `.archive` inside it that is
  tens of MB per run. Prune older rollback trees inside the swap so exactly one remains.
- **After `hermes skills update`, prove where the bytes landed.** The hub can unpack into a directory
  named after a path segment (`skills/imports/skill/`) instead of `imports/<skill-name>/`; the command
  still reports success. Check `find ~/.hermes/skills -name SKILL.md -newermt '-30 minutes'` and move
  the content into place, then re-run the materializer.
- **A home-topology change invalidates the recovery policy.** Its frozen inventory fails closed as
  `policy-stale`; rebuild it from live (`build-recovery-policy*.py` in the core-jobs task dir) rather
  than editing the JSON, then point the produce/verify wrappers at the new file.
- **`readlink -f` a skill before editing it.** An entry under `~/.hermes/skills/devops/` can be a symlink into `~/repos/hoa`; editing it silently edits the canonical public copy, so the change belongs in a hoa branch + PR (with the gates below), not in the host tree.
- **A hoa PR needs two artifacts or CI fails twice.** `python3 scripts/version.py bump` (VERSION unchanged from `origin/main` ⇒ red), then a `CHANGELOG.md` entry for that increment — checked *after* the bump, so a bump-only commit still fails. Do both in one commit.
- **A bulk literal replacement can inject shell syntax into a language that does not expand it.**
  `os.path.expanduser("${SKILLS_HUB:-~/.agents}/...")` is a literal string, so the documented default never
  applies and the script raises `FileNotFoundError` only at run time. After any mechanical `${VAR:-default}`
  pass, `ast.parse` is not enough — execute the entry point and read real output. Code review (Codex)
  caught the second instance in a heredoc snippet after the script itself had been fixed.
- **Never `git reset --hard`, `git clean -fd`, or a branch switch in a working tree you do not solely own.**
  Uncommitted work from another session is not in the object database: `git fsck --lost-found` returns no
  blob for it and it is gone for good. Read `git status` first, preserve with
  `git stash push -m "<why>" -- <path>`, and *verify* with `git stash list` before touching the tree —
  `-q` hides exactly the error that leaves the change unprotected.
- **Symlinking the host skill library into a live dev checkout dangles on every branch switch.**
  `os.walk(top, followlinks=True)` yields nothing for a dangling directory link without raising, so the
  materializer can "successfully" copy an empty skill. Assert `islink(p) and not exists(p)` in `--check`,
  and never edit through the link expecting a local-only change — it writes the canonical repo.
- **Publishing a ported skill is irreversible and needs its own gate.** Provenance (runtime bundled
  manifest, same-name public repos), a local private-word scan before `git push`, and the catalog's
  version/changelog/index order: `references/skill-publication-gate.md`.
- **Empty category scaffolding is intended; a nested real skill is the drift.** Profile distribution
  ships category metadata as `skills/<category>/DESCRIPTION.md` (no SKILL.md) so the skill picker can
  label groups; bundled `sync_skills` re-adds such dirs at CLI/gateway start. Do **not** delete them: the
  materializer now treats a dir with no `SKILL.md` at or under it as a container — skipped by
  `--check`'s stale scan and carried across the atomic swap (`apply_plan`'s `containers`). Before that
  fix every home reported `[DRIFT] … N unmanaged entr(ies)` with `0 stale dropped`, i.e. a permanent red
  light nobody could clear. What *is* drift is a nested real skill under a category dir
  (`<home>/skills/autonomous-ai-agents/hermes-agent/`): bundled sync writes the bundled **category**
  layout while the materializer writes flat names, so the two coexist and the same skill is indexed twice.
  Diff it against the flat copy (the flat one is the materialized one in `skills.lock.json`), move the
  nested dir into a backup, re-run `--check`. If it returns after the next CLI start, the bundled
  manifest hash no longer matches upstream — raise it as a structural fix rather than deleting daily.
  Automated path: `profile-skill-materialize.py --prune-duplicates` moves only the *skill* under the
  category dir (the dir keeps its `DESCRIPTION.md`) into `~/claw/backups/cleanup-<date>/nested-dups/`,
  and `daily-hygiene.py` runs it from the 05:00 health job — so the moved copy inherits the 30-day
  retention instead of growing a second backup tree. Never wire the prune into `hermes_health.py`
  itself: that checker is read-only by contract, and a mutation inside it makes its findings suspect.
- **A cloned home's `config.skills.disabled` silently disables skills its own `allowed_skills` enables.**
  A clone inherits the source's full denylist (hundreds of names); where the two lists overlap, the skill
  is materialized on disk and still not loaded. Diff the lists after any create/clone and remove the
  overlap, then prove it with `HERMES_HOME=… hermes skills list | tail -1` reading `N enabled, 0 disabled`
  — the drift checkers validate the tree against `allowed_skills` and never notice the config-level veto.
- **A fault-injection test on a live home must be undone by the generator, not by copying bytes back.**
  A verification pass that truncated a head block by one byte left the home in drift when the run ended;
  the next session inherited a broken identity that every checker reported. After any injected defect,
  restore with `materialize.py --apply --only <home>` (or the host materializer) and re-verify the head
  block prefix — and when accepting another agent's "negative test passed" claim, re-run the probe and
  re-read the live file yourself, because the claim does not cover the undo.
- **`pathlib.rglob` does not descend into symlinked directories**, so a scan for `SKILL.md` under the
  host pool silently skips every hoa-linked skill and then reports that *every* home is missing *every*
  shared skill. Use `os.walk(root, followlinks=True)` for the name set; use the non-following walk only
  to collect `is_symlink() and not exists()` as dangling links. When a fleet-wide alarm claims all homes
  lost all skills, suspect the scanner first and re-run the materializer's own `--check` before reporting.
- Full ordered procedure, verification set and rollback: `references/profile-refactor-checklist.md`.
- Runnable whole-fleet inventory (cwd → which `AGENTS.md` a bot really loads, SOUL split into
  contract / generic / role with a per-home generic hash, allowed-skill counts, live vs archive skill
  bytes): `scripts/audit-profile-lines.py` — run it before proposing any instruction restructure, and
  again after each separation step.

## Restore drill

Packaged: `bash ~/.hermes/scripts/restore-drill.sh [<generation-dir>] [<home> …]` with helper
`lib/drill_check.py`; report lands in `~/.hermes/logs/recovery/drill-*.md`. Each row carries boot result,
`SOUL.md`/`.env` sha256 against `manifest.json`, session count and elapsed time. A full fleet run is
~15 minutes and is the only evidence that a generation can actually be *started* — extracting tarballs and
checking hashes proves the archive is intact, not that a home boots.

- **The copy must live under `~/.hermes/profiles/<name>`.** Untarring elsewhere and pointing
  `HERMES_HOME` at it fails with `Gateway could not start … one gateway per host serves every profile`:
  profile identity comes from the directory name, and neither `profile.yaml: name` nor `HERMES_PROFILE`
  overrides it. Untar → `mv` into `profiles/` → `hermes -p <name> chat -q "Reply with exactly: DRILL_OK"
  --oneshot -t clarify -Q`.
- **Profile id: unique per run and lowercase.** `drill-<home>-<stamp>`. A leftover phantom from an earlier
  drill makes the same name refuse to serve, which reads exactly like a corrupt backup; and the CLI
  lowercases ids, so a directory carrying `T` answers `Profile … does not exist`.
- **Disarm cron inside the copy before booting.** A restored `default` home carries the live
  `cron/jobs.json`; rename it (`jobs.json.drill-off`) or the drill fires production jobs.
- **The script now cleans up after itself, including on interrupt.** A `trap cleanup EXIT INT TERM` removes
  every `drill-*-<this run's lowercase stamp>` it created and deletes the profile registration with it, so
  Ctrl-C, a `timeout`, a failed boot or a mid-run abort no longer leaves draft homes behind. Inspect a copy
  deliberately with `--keep` (the trap then prints the paths instead of removing them). Residue is still
  worth a check after a crashed run: `ls -d ~/.hermes/profiles/drill-*` — empty directories from an older
  script version are inert (no `profile.yaml`, so no `profile list` row) but they make `ls` noisy and every
  fleet-walking script needs a `drill-` skip.
- **A provider error is not a bad backup.** Bake one retry in: several boots in a row against one proxy
  produce `request_failed`, and recording that as "this backup cannot start" corrupts the whole verdict.
- **A bare `rm -rf` of the copy does not delete the profile, and a restart does not either** (the drill
  script's trap covers this by calling `hermes profile delete` itself). The id stays in
  `served_profiles`, `hermes profile list` keeps showing it, the daily check reports `acquisition …
  unknown`, and the gateway re-creates a skeleton dir under `profiles/` (a few hundred KB, so `du` reads
  it as harmless). `systemctl restart` carries `served_profiles` across unchanged — the belief that a
  restart purges it is wrong and was measured wrong. Remove it through the CLI:
  `hermes profile delete <id> --yes`, then confirm `hermes profile list | grep -c drill` is 0. Never edit
  `gateway_state.json` / `spawn-ledger.json` by hand: the live process rewrites both and the record ends
  up disagreeing with the host.

## Rename fallout in the shared pool

Rule 10 is the procedure; this is the assumption behind it. A rename that only moves files inside `hoa`
leaves the host pool's link dangling and every consuming home one skill poorer, with no error anywhere in
the rename — the only signal is `skill-applyback-guard.py` saying `source missing`. Treat "they renamed a
skill" as a cross-repo change: sync the host link, sweep dangling links, update `allowed_skills`,
re-materialize — in the same pass, before reporting that refactor as landed. Expect it more than once
while a family is being redesigned, and ask the owning session for a `old → new` map instead of
discovering each rename through a broken home.

## Sweep the family when you fix a checker

Fixing the materializer's container false positive left `skill-applyback-guard.py` still failing the same
category dirs (`present on disk but absent from lock`) — the red light moved rather than went out. When a
checker's verdict changes, grep the sibling checkers for the same predicate (`SKILL.md`-presence tests,
"unmanaged entry" wording, `is_container` helpers) and fix them in the same edit: two checkers
disagreeing about one tree is worse than one checker being wrong.

## Package-manager caches

Not a profile concern: trees and prune flags live in `hermes-operations` →
`references/host-remediation.md` → "Package caches". Each tool prunes whatever tree it decides on, so
pass the directory explicitly and measure before/after.

## A rename in the source must be chased in three places, not one

When a skill is renamed or absorbed upstream (`hoa`), the host library link is only the first of three
references. The other two live inside every home and fail silently:

- **`profile.yaml:allowed_skills`** — the name that decides what a home materializes. A name that no
  longer exists drops the skill from that home without any error.
- **`config.yaml:skills.disabled`** — the deny list still carries the OLD name, so the rename silently
  *enables* the skill in every home that had it disabled (the deny entry stops matching). Grep the old
  name across `profiles/*/config.yaml`, not just the host tree.
- Leftover materialized dirs are pruned by the next `--apply`, but the two YAML references are not:
  fix them with a backup, then verify with `grep -c '<old-name>' profiles/*/config.yaml` = 0.

A port that lands in the host library can also collide with the local copy it was ported *from*: the
symlink goes to `<areas>/<name>` while the original real dir stays at its old path, leaving two host
skills with one leaf name. Retire the local copy (move it to a backup dir) once `diff` shows the ported
body is the same skill; scan for the whole class with `os.walk(..., followlinks=True)` while skipping
`node_modules` — `rglob` follows no symlinks and will report zero duplicates.

## `python3` in a shell is not the interpreter these scripts need

`python3` on the shell PATH resolves through `mise` and its managed CPython ships pip and nothing
else, while the hermes venv and `/usr/bin/python3` have `pyyaml`. Scripts under `~/.hermes/scripts/`
that import `yaml` therefore died with `ModuleNotFoundError` when run by hand — a false red that looks
exactly like drift. Four launchers, and only one of them was broken:

- **Hermes cron ignores the shebang on purpose** (`cron/scheduler_script.py:_posix_cron_script_argv`)
  and runs every `.py` script on the managed dependency venv's interpreter, so scheduled jobs were
  always fine.
- systemd units name `/usr/bin/python3`; shell wrappers source `lib/py.sh` (`$HERMES_PY`).
- A hand-run `python3 script.py` was the broken path.

Fix in place: `lib/interp.py`'s `ensure_runtime("yaml")`, called before the `yaml` import in the
check scripts, re-execs once onto the first interpreter that can import it (marker env var stops
recursion). Ordering matters — the guard must sit *before* `import yaml`, and after `pathlib`, or the
missing import raises first (`NameError: name 'Path' is not defined` is the symptom of getting that
backwards). Prefer this over pinning a shebang: cron throws shebangs away, and over `uv run`, which
would need a second environment layer for scripts that import the runtime's own `lib/` and `pm`.

## Restore drill cost: budget for it before scheduling one

- **The drill creates disk pressure while proving recoverability.** Every drilled home boots as a
  brand-new profile, and a new profile's first start runs a dependency install, so
  `~/.hermes/installs/<hash>/environments/` gains one tree per drilled home (~0.5–1.4 GB each; hardlinks
  share most bytes, so the tree count matters more than the sum). A full-fleet run is N trees; schedule it
  after a cleanup, not before one, and prune install environments in the same pass — the growth mechanics
  and the keep-rule are in `hermes-operations` → `references/host-remediation.md` → "Install
  environments".
- **Building a home file-by-file inside `profiles/` is the trap that makes a good backup look rotted**
  (verdict: `profile_parked … database disk image is malformed`, from a *cached* open failure). Rule 14
  in SKILL.md is the requirement and the diagnosis; re-read it before any restore, clone or migration
  rather than re-deriving the race.
- A drill that ends with a residual `drill-*` id is a cleanup bug, not a backup verdict: check
  `hermes profile list | grep -c drill` after every run (see "Restore drill" above for the CLI-only
  removal).
- **A managed copy used to lose the source's executable bit**, which shows up far from its cause: a
  launcher or adapter under `profiles/<p>/skills/**` answers `Permission denied` while the same file in
  the source repo is `-rwxr-xr-x`, because the materializer stamped every managed file `0444`. Diagnose
  with `stat -c '%a %n' <home>/skills/.../<file>` and compare against the source tree before blaming the
  caller. Fixed 2026-11-15: a source with any exec bit now materializes `0555`, plain files stay `0444`,
  and `--check` compares mode as well as content — so a mode-only drift (including a home materialized
  under the old rule) is now reported instead of hidden. Regression guard:
  `~/.hermes/scripts/tests/test-profile-skill-materialize-mode.py`.
