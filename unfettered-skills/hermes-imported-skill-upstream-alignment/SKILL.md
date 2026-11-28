---
name: hermes-imported-skill-upstream-alignment
description: "Use when aligning imported skills with their upstream."
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Imported Skill Upstream Alignment

Use this when the user asks to:
- review/update local imported skills
- align GitHub-backed skills to upstream
- remove or replace an obsolete skill
- standardize routing from one skill to another across active docs/agents

This is especially useful for `~/.hermes/skills/imports/*`.

## Core rules

1. **Backup before touching anything.**
2. **Treat git-backed and non-git skills differently.**
3. **Prefer active runtime docs over archived history.** Do not mass-rewrite `~/claw/tasks` or `~/claw/research` unless the user explicitly asks.
4. **If the user wants pure upstream, do not keep local patches.** Reset hard and clean.
5. **Verify with searches, not vibes.**

## Workflow

### 1) Inventory the skill source type

For the target skill(s), determine:
- is it a git checkout with `.git`?
- what is the remote?
- is the working tree dirty?
- what active skills/docs reference it?

Use:
- `skill_view(name)` to inspect the skill contract
- `search_files()` for references in `~/.hermes/skills`
- `search_files()` in `~/claw` task docs (`tasks/*/status.md`, `references/agents/`) and top-level `AGENTS.md` for active docs
- terminal/git only for repo-backed skills

### 2) Separate active vs archived references

Search broadly first, then narrow scope.

Typical active locations:
- `~/.hermes/skills/**/*.md`
- `~/claw/tasks/**/status.md` (run-time task records)
- top-level `~/claw/AGENTS.md`

Typical archive/noise locations:
- `~/claw/tasks/**`
- `~/claw/research/**`

Default rule: **update active runtime docs first; leave archives alone** unless user explicitly asks for historical cleanup.

### 3) Backup before any destructive change

Create a dated backup directory under `~/claw/tasks/YYYY-MM-DD/<task>/` and save:
- full copy/tarball of the skill directory being replaced/removed
- copies of every SKILL.md or runtime doc you will edit
- optional pre-change status/head files for git-backed skills

For destructive removals, keep both:
- folder copy
- `.tgz` archive

### 4) If the skill is git-backed and user wants upstream alignment

Use git, not manual file patching:

```bash
git fetch origin
git reset --hard origin/main
git clean -fd
```

Notes:
- `reset --hard` is correct when the user explicitly wants **pure upstream**.
- If you temporarily patched docs but the user later says “use upstream version directly”, remove your local edits with reset/clean.
- Capture evidence before reset if local changes existed.

### 5) If the skill is a local imported skill (non-git) and should be removed/replaced

Procedure:
1. backup the skill directory
2. identify active docs that route to it
3. patch those docs to point to the replacement skill
4. delete the obsolete skill directory

Do **not** delete first and figure it out later. That is how future-you earns trust issues.

### 6) Patch active routing docs precisely

Prefer targeted file patches over broad rewrites.

Examples of routing edits:
- replace references like `x-reader` → `x-tweet-fetcher`
- update usage wording to match the replacement skill’s real capabilities
- if the replacement supports richer extraction, document that explicitly (e.g. replies/media/timelines)

When replacing one skill with another, do not do a blind string swap if behavior differs. Update the guidance text too.

### 6.5) For non-git imported skills, verify docs against the actual local files

Do not trust the SKILL doc blindly just because the skill exists locally.

Check:
- whether the files named in `SKILL.md` actually exist
- whether hardcoded paths still point at old OpenClaw locations
- whether the documented command still runs (syntax/help is enough for low-risk verification)
- whether the real runtime path should be `~/.hermes/...`, `~/claw/...`, or a legacy `~/.openclaw/...` location

Typical low-risk fixes:
- replace hardcoded install paths with `{baseDir}`
- replace old OpenClaw config instructions with Hermes env / `~/.hermes/.env`
- narrow misleading docs when runtime data still lives in a legacy location but owner-facing artifacts moved elsewhere

### 6.6) If the stale problem lives in code, migrate with legacy-first fallback before full cutover

For imported non-git skills, some staleness is not just docs — the runtime code may hardcode old OpenClaw paths.

Use this pattern when the legacy data is still real and you do **not** want to break existing state:

1. identify the hardcoded legacy paths in code
2. confirm whether those legacy paths still exist on this machine
3. add resolver helpers instead of hard-swapping paths immediately
4. prefer:
   - legacy path if it exists
   - Hermes-native fallback if legacy path is absent
5. update the SKILL doc to explain the compatibility behavior explicitly

Good targets for resolver helpers:
- data directories
- dependent skill file paths
- config file locations

Example migration shape in Python:

```python
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
LEGACY_DATA_DIR = Path.home() / ".openclaw/workspace-gray/portfolio/data"
HERMES_DATA_DIR = HERMES_HOME / "skills" / "imports" / "portfolio-tracker" / "data"


def resolve_data_dir() -> Path:
    if LEGACY_DATA_DIR.exists():
        return LEGACY_DATA_DIR
    return HERMES_DATA_DIR
```

This keeps current installs working while making future Hermes-native migration possible.

### 6.7) Verification for runtime-path migrations

After patching code, verify both realities:

- **current-machine reality** — the skill still runs with the existing legacy path
- **future fallback reality** — simulate legacy-path absence and confirm the Hermes fallback initializes correctly

Useful checks:
- run the script normally (`list`, `help`, or a minimal add/remove cycle)
- confirm exit code is zero
- in a temp directory, monkeypatch the legacy path constants and verify fallback files are created

Do not call a runtime migration done just because the diff looks right. Prove both the live path and the fallback path work.

### 6.8) If a Python skill vendors dependencies under `lib/`, verify ABI compatibility — not just package presence

A common trap: the skill's `lib/` directory may already contain compiled wheels for the **wrong Python minor version** (for example `cpython-312` `.so` files while Hermes is running Python 3.11). In that case:

- `pip install --target ... package` may appear to succeed
- but imports still fail because stale compiled artifacts remain in place
- error messages often mention something like `_multiarray_umath.cpython-312-...so` being incompatible with `cpython-311`

Workflow:
1. inspect the actual import error, not just the top-level package name
2. check the wheel tags / `.so` filenames under `lib/`
3. if stale compiled artifacts are present, reinstall with `--upgrade --target <lib>` using the same Python interpreter Hermes actually uses
4. re-test direct imports from that `lib/` path before trusting the skill CLI

Useful checks:
- `python3 - <<'PY' ... sys.path.insert(0, '<lib>'); import numpy, pandas, yfinance ... PY`
- read `WHEEL` files under `*.dist-info/` to confirm `cp311` vs `cp312`
- search for `.so` filenames containing the wrong ABI tag

Key lesson from `finance-data`: the first vendor pass added `yfinance`, but imports still failed because old `numpy/pandas` `cpython-312` binaries were still sitting in `lib/`. Re-running with `--upgrade` fixed the actual problem.

### 7) Verification checklist

After edits/removal, verify all of the following:

- `search_files("old-skill-name", path="~/.hermes/skills", file_glob="*.md")` returns zero active matches
- the old skill directory no longer exists
- active docs now reference the new skill
- if applicable, the replacement skill still loads cleanly with `skill_view(new-skill)`
- if git-backed, `git status --short` is clean after alignment

## Proven pattern from x-reader → x-tweet-fetcher

This exact approach worked well for:
- removing local imported skill `x-reader`
- rerouting active skill docs to `x-tweet-fetcher`
- keeping archived `~/claw/tasks` and `~/claw/research` references untouched
- verifying active references were zero before calling it done

Key active docs that needed patching in that migration:
- `~/.hermes/skills/imports/researcher/SKILL.md`
- `~/.hermes/skills/imports/standup-prep/SKILL.md`
- `~/.hermes/skills/imports/notebooklm-deep-research/SKILL.md`

Key lesson: broad search across `~/claw` produces lots of archived hits, so **scope discipline matters**.

## Pitfalls

- **Do not assume every imported skill is git-backed.** Some are just local folders with homepage metadata.
- **Do not rewrite archived research/tasks by default.** It creates churn with little runtime value.
- **Do not patch upstream-managed git skills if the user asked for clean upstream.** Reset them instead.
- **Do not verify by memory.** Always run post-change searches.

## Completion output

Report succinctly:
- what was backed up
- what was aligned/removed
- which active docs were patched
- what verification proved completion
