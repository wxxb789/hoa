# Retiring a previous agent platform


## Retiring a previous agent platform

When the owner retires a previous agent platform (e.g. a pre-Hermes OpenClaw setup) and wants everything related removed:

1. Inventory before deleting: platform-named dirs/files under `~/.hermes` and the artifact space, migration dirs, doc mentions (GTD, shared rails, LOCAL_OVERRIDES), env key names, cron jobs, hub records. Classify each hit as **platform residue** (names, paths, dead references, empty dirs) versus **migrated tools still in use** — check `~/.hermes/skills/.usage.json` before touching a skill category; when only the category name carries the platform brand, rename it instead of deleting the skills.
2. Renaming a skill category is one atomic pass: hub `~/.hermes/skills/.hub/lock.json` `install_path`s under the old path, profile symlinks (`profiles/*/skills/<category>`), external shared symlinks (e.g. `~/.agents/skills/*`), and hardcoded old paths inside other skills' bodies (`grep -rln '<old-path>' ~/.hermes/skills`).
3. Back up everything to be deleted into one dated set under `~/.hermes/backups/<platform>-purge-<date>/`, verify each tarball with `gzip -t` and spot-check key paths via `tar tzf` BEFORE deleting — the tarball is the only rollback.
4. Fix live docs in the same pass (shared rails, GTD entries, LOCAL_OVERRIDES, memory) to reference the current runtime instead of the retired platform, and record the retirement with its rollback path.
5. Leave alone: upstream skill bodies that merely mention the platform as a third-party integration, Hermes' own `onboarding.seen` flags, and hub index caches (auto-refreshed).
6. Verify from both homes: `hermes skills list` and `hermes --profile <p> skills list` resolve the renamed category, `sync-profile-skills.py` reports 0 drift, `skill_view` loads a renamed skill, and `find <artifact-space> -iname '*<platform>*'` returns nothing unintended.
7. When the owner later orders the purge backups deleted, comply fully and scrub every rollback pointer (override docs, memory) in the same pass — mark the retirement as locally irreversible so future sessions do not hunt for archives that no longer exist. Keep unrelated backup sets separate and standing; a platform purge does not license deleting other backups.
