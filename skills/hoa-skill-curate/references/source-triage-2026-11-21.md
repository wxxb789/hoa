# Source triage (2026-11-21)

Record each candidate's source, revision/path, local install and usage evidence,
repository activity, archive state, any evidence of maintainer activity, and live
dependencies. On GitHub, repository metadata gives `pushed_at` and `archived`;
neither describes a person's activity or grants consent. Distinguish an inactive
repository, an inactive path within a live repository, and an unknown maintainer
status. For owner-authored skills with no upstream, use the owner's stated criteria
and usage ledger; a file mtime refreshed by an edit is not usage evidence.

Check scheduled prompts, runtime policy, current docs and callers; distinguish live
references from historical mentions. Look for current or upcoming reliance, including
profile links to a shared store. If anything is unclear, surface it as a decision
gap. Current owner approval is required even if every retirement signal matches.
After an approved removal, verify the loaded skill list from affected profiles, not
just the count of category entries.

For a GitHub shared-store tip screen, run `uv run scripts/upstream-freshness-check.py`.
It checks SKILL.md at moving HEAD (not the whole package or pinned revision) and
normalizes line endings and outer whitespace. Report SAME/DIFF/ERR totals and DIFF
or ERR rows; errors and untracked entries do not prove freshness. `--enabled`
excludes disabled installs; `--lock`, `--skills-root`, and `--config` select inputs.
The lock defaults to `SKILLS_LOCK` if set, otherwise the shared store lock. Exit 1
means differences or fetch errors; exit 2 includes missing lock or skill files.
