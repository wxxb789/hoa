# Publishing a skill into a public catalog

Ordered procedure. Every step exists because skipping it produced a real defect: a bundled upstream
skill published as our own, a same-name collision with a public repo, and two CI round trips spent on
version/changelog bookkeeping.

## 1. Prove the content is ours before it leaves the machine

```bash
# runtime-shipped skills: name:hash, one per line
python3 - <<'PY'
import os, hashlib
for line in open(os.path.expanduser("~/.hermes/skills/.bundled_manifest")):
    name, _, digest = line.strip().rpartition(":")
    ...
PY
```

- A name in that manifest is upstream work. A hash that differs from your file means *locally modified
  upstream*. Neither belongs in your catalog — exclude it and say why in the PR/close comment.
- Compare same-named skills against the public repos that carry them
  (`api.github.com/repos/<owner>/<repo>/git/trees/main?recursive=1`, then
  `raw.githubusercontent.com/<owner>/<repo>/main/<path>`). Our own thin skills are a few hundred bytes;
  a large body whose paragraphs match is someone else's text. Diff, do not guess.
- Same name, different content ⇒ **rename on the way in** (`improve-codebase-architecture` →
  `arch-improvement-plan`) so two catalogs never disagree about what a name means. Keep the mapping in
  the port script as `repo name → host skill dir`, not in your head.
- Third-party `author:`/`license:` in the frontmatter (someone else's org, a variant repo) is enough to
  stop: publish only what we authored, or get explicit permission with attribution.

## 2. Scan the outgoing diff locally — the remote CI is not a guard

A public push is irreversible: closing the PR or deleting the branch leaves the objects fetchable.

```bash
python3 ~/.hermes/scripts/public-repo-push-gate.py --range origin/main..HEAD
```

It refuses on home paths, private words (user/host/repo names), snowflake channel ids, provider names,
and credential shapes. A hit means the *source* text is wrong — fix the skill, regenerate, re-run. Do not
whitelist the pattern away.

## 3. Catalog gates, locally, in this order

```bash
python3 scripts/check_frontmatter.py          # name == dir, description, metadata block
python3 scripts/version.py bump                # a PR that leaves VERSION alone fails
python3 scripts/version.py sync                # bump alone leaves every other skill's metadata.version behind
python3 scripts/generate_index.py --check      # index drift after any frontmatter change
python3 scripts/check_changelog.py --base origin/main
```

`bump` without `sync` is the classic red: "version/index drift in skills/<a>/SKILL.md, skills/<b>/SKILL.md…".
Frontmatter the catalog validates: `name`, `description`, `metadata.{areas,targets,version,summary,summary_zh,kind}`.
`areas` and `targets` are closed vocabularies — read them from `scripts/generate_index.py` (`AREAS`,
`TARGETS`) instead of inventing values; a source skill authored for one runtime usually has a nested
`metadata.<runtime>` block that must be flattened.

## 4. One PR per skill, serial

A single repo-wide `VERSION` means parallel PRs compute the same next version and then conflict on the
same line; every merge forces every other branch to rebase and re-run CI. Serialize: port, gates, PR,
wait, merge, pull, next. If a batch must be parallel, the feature PRs stay out of `VERSION`/`CHANGELOG`
and one release PR carries the version.

## 5. Merge on evidence, not on silence

- CI green is the objective gate. An automated reviewer that reports `has_unresolved_findings: null` with
  zero comments has *not reviewed* — that is absence of evidence, not a pass; say so rather than claiming
  "no findings".
- Read the findings that do arrive, including ones on documentation snippets: a P1 in a heredoc example
  is the same defect as one in the script, and a user will copy the example.

## 6. After the merge

The host library must not keep a second copy: the entry under `~/.hermes/skills/...` becomes a link to
(or a re-materialization from) the catalog copy, and both control planes re-run their materializers —
missing the NRS one leaves the `*-nrs` homes on the old skill.
