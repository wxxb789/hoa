# Profile de-inheritance: ordered procedure

Use when converting a generation/symlink based multi-profile install into independent homes, or
when auditing that the conversion is still intact. Each step is verifiable; do not skip the
verification to save a round trip.

## 0. Baseline (no writes)

```bash
# per-home backups, verified on the spot
python3 ~/.hermes/scripts/profile-backup.py --all --out ~/claw/backups/profiles/pre-refactor-<ts>
# config plane snapshot (config, SOUL, AGENTS, cron defs, per-home profile.yaml)
tar czf ~/claw/backups/pre-refactor-<ts>/config-plane.tar.gz \
  config.yaml SOUL.md AGENTS.md memories/*.md cron/jobs.json \
  profiles/*/profile.yaml profiles/*/config.yaml profiles/*/SOUL.md profiles/*/cron/jobs.json
```

`profile-backup.py` prints `解包 OK · 缺 0 · state.db 可读` per archive — treat only that
evidence as a usable backup.

## 1. Retire the old writers first

Any scheduled job that rewrites SOUL.md or skill links will undo the migration at the next tick.
Before touching a home:

1. run `grep -rln '<generator>.py' scripts/` and patch every caller,
2. move the generators to `scripts/retired/`,
3. re-grep the cron job files (`cron/jobs.json`, `profiles/*/cron/jobs.json`) for the retired names.

Check mode matters: a reconciler that auto-repairs a layer must lose that repair once the layer is
owned, because "repair" there means "overwrite the bot's own text".

## 2. Identity

```bash
python3 ~/.hermes/scripts/profile-soul-deinherit.py            # plan: bytes per home
python3 ~/.hermes/scripts/profile-soul-deinherit.py --apply --only <home>
python3 ~/.hermes/scripts/profile-soul-deinherit.py --check
```

Composition per home: invariants head block at **byte 0**, an `owned-by-this-home` marker, the H1
renamed to that bot, the frozen body, then the role section. Republican-owned homes are instead
compiled from the repo (host head block + repo shared behaviour + role file) — do not seed them
locally.

Verify: `--check` exits 0 for every home and each file still contains its role section
(`tail -20 profiles/<p>/SOUL.md`).

## 3. Skills

```bash
python3 ~/.hermes/scripts/profile-skill-materialize.py --dry-run   # count + size estimate
python3 ~/.hermes/scripts/profile-skill-materialize.py --apply
python3 ~/.hermes/scripts/profile-skill-materialize.py --check
```

Then prove the invariant directly, independent of the script:

```bash
for p in ~/.hermes/profiles/*/; do
  echo -n "$(basename $p): "
  find "$p/skills" -maxdepth 1 -type l | wc -l            # must be 0
  ls "$p/skills" | wc -l                                   # must equal allowed_skills
  ls -d "$p"/skills.bak.* 2>/dev/null | wc -l               # exactly 1
 done
```

A surviving symlink means that home was not migrated or a sync re-added one; the health check
should flag it as `symlink-remains`.

## 4. Gateway

The gateway caches a skill/prompt snapshot; new sessions read disk, so materialization is
verifiable without a restart (`HERMES_HOME=<home> hermes skills list`). Restart only to drop the
cached snapshot, and do it from outside the gateway cgroup (see the `hermes-gateway` skill) — the
in-process guard blocks the naive command.

## 5. Backup topology

A home-count change makes the frozen recovery policy fail closed. Rebuild it from live inventory
with the existing builder script (change only the output path), point the produce and verify
wrappers at the new policy file, then run one real produce and read
`production-verification.json`. The independent weekly verifier is silent on success by contract —
silence plus exit 0 is a pass, not a missing run.

## 6. Rollback

| Step | Rollback |
|---|---|
| identity | `<home>/retired/SOUL.generated-<ts>.md` |
| skills | reverse the two renames: `mv skills skills.new && mv skills.bak.<ts> skills` |
| config plane | `tar xzf config-plane.tar.gz` |
| data | `profile-backup.py --verify <archive>` before restoring anything |
