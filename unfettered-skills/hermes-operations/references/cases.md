# hermes-operations — case notes

Compressed case notes: signal, cause, fix, proof — 5–8 lines each. The rules live in `SKILL.md`;
treat these commands as leads to re-verify against the current build.

## Config review and OpenClaw migration cleanup

- **Signal**: an ops review that needed DB/WAL numbers and a profile-layout answer.
- **WAL path**: size `state.db{,-wal,-shm}` → `pragma integrity_check` → `pragma wal_checkpoint(TRUNCATE)` → `hermes sessions stats`.
- **Migration**: archive both `~/.openclaw` and `~/.hermes/migration` under `~/.hermes/backups/openclaw/`.
- **Pitfalls**: `cronjob` rejects absolute script paths (bare filename under `~/.hermes/scripts/`); Discord "max application commands" is the 100-command cap, not a broken gateway; never delete old `~/.hermes/tmp` worktrees without an explicit scope — archive first.
- **Proof**: `hermes profile list`, `hermes cron list --all`, `hermes doctor`, `hermes config check` + archive path/size + integrity result.

## Bundled vs hub skill updates

- **Question shape**: do built-in skills follow Hermes releases, or update on their own?
- **Classes**: bundled (repo `skills/`, refreshed by `hermes update` + startup sync, manifest-guarded) · hub / official-optional (`hermes skills check` / `update`) · local + agent-created (never overwritten) · `skills.external_dirs` (owned by that directory).
- **Manifest rules** (`tools/skills_sync.py`): new skill → copy + record hash; local copy == origin hash → safe update; differs → user-modified, skip; missing on disk → respect the deletion; dropped upstream → drop the entry; `.no-bundled-skills` / `.curator_suppressed` → no re-seed.
- **Commands**: `hermes skills list-modified` · `diff <name>` · `reset <name>` · `reset <name> --restore`; hub: `check` / `update`; opt-out: `hermes skills opt-out [--remove]`, re-enable `opt-in --sync`.
- **Pitfall**: `hermes skills update` is the *hub* path; bundled skills only move with `hermes update` under the manifest guard.

## Third-party GitHub skill install (Agent Reach)

- **Order**: load `hermes-agent` → inspect upstream (`git ls-remote <repo> HEAD`, README + candidate `SKILL.md`; a repo `CLAUDE.md` is repo-local, not global) → back up `tar -C ~ -czf <art>/backups/hermes-skills-before-<name>-<ts>.tar.gz .hermes/skills`.
- **Install**: `hermes skills inspect <raw SKILL.md URL>` → `hermes skills install <url> --category <c> --yes` → verify with `skill_view`, including `linked_files` (raw-URL installs may carry only `SKILL.md`).
- **Support files missing**: do not patch a hub-protected skill in place — install from a file-preserving source, or write a local wrapper that points at the upstream package.
- **CLI layer** (when the repo ships one): `uv tool install --force <archive.zip>` → `agent-reach install --env=auto` → `agent-reach version`, `agent-reach doctor --json`, `command -v agent-reach mcporter yt-dlp gh node`.
- **Pitfalls**: "skill installed" ≠ "runtime installed"; no `sudo`, and no cookie/login-backed channels (X, Reddit, 小红书, 雪球, LinkedIn) without an explicit owner decision; drop temp clones once evidence is saved.
- **Evidence**: `~/claw/tasks/YYYY-MM-DD/<task>/evidence/` — install summary, binary paths, doctor output.
