# `skills` CLI installs: layout, provenance, warning triage

Covers the vercel-labs `skills` CLI, which is the installer behind the shared skills store and
the `npx skills add|update|use|list` commands. Check the installed version before trusting any
behavioral note here: `npx --yes skills@latest` means the bundle changes under you — locate the
cached package (`~/.npm/_npx/*/node_modules/skills/package.json` carries `version` and
`repository`) and read its `dist/cli.mjs` when a detail matters.

## Layout

| Path | Role |
|---|---|
| `~/.npm/_npx/<hash>/node_modules/skills/` | The cached CLI bundle itself (no global bin) |
| `~/.agents/skills/<name>/` | The shared skill store — real directories |
| `~/.agents/.skill-lock.json` | Install manifest: every installed skill plus its source |
| `<runtime-home>/skills/<category>/<name>` | Symlink farm into the store for one runtime |
| `~/.config/<agent>/skills`, `.claude/skills`, `.pi/skills`, … | Farms for other agent CLIs |
| `$TMPDIR/skills-XXXXXX/` | A throwaway **git clone** of a source repo, `mkdtemp`-created per install/update |

Store directories are load-bearing: a store with no CLI of its own (the CLI ran through `npx`)
still feeds every farm symlink. Never classify it as orphaned without counting inbound links.

## Manifest fields

`~/.agents/.skill-lock.json` → `{version, skills, dismissed, lastSelectedAgents}`;
`skills.<name>` → `{source, sourceType, sourceUrl, skillPath, skillFolderHash, installedAt,
updatedAt}`.

- `source` is `owner/repo` — group by it to count skills per upstream repo.
- `skillPath` is the path *inside* the source repo, i.e. the identity used for update diffs.
- `updatedAt` moves when a re-run actually changed content, so a no-op `update` leaves it
  untouched. Do not read a stale `updatedAt` as "the installer failed".

## Frontmatter gate

Every `SKILL.md` found during a scan must carry frontmatter `name` **and** `description`. A file
with only `name:` is reported and skipped:

```
⚠ Skipped <path> — missing required frontmatter field(s): description
```

The scan walks the **entire cloned tree**, following the repo's own layout rather than a
curated skill list, and `--skill <name>` filters what gets *installed*, not what gets *scanned*.
A repo with test fixtures shipped in its tree therefore always produces these lines.

## Triage table

| Warned path | Meaning | Action |
|---|---|---|
| `<tmp>/skills-*/tests/fixtures/**` | Upstream fixture, deliberately incomplete | Cosmetic. Verify, then explain, then stop |
| `<tmp>/skills-*/skills/<name>` | A real skill in the source repo is malformed | Report to the upstream author; the local install of that skill is absent |
| Warned name present in the lock file | The skip did not take effect as expected | Real defect — investigate before claiming success |
| Warned name absent from the lock file | Correctly skipped, nothing installed | Expected outcome for fixtures |

## Verification commands

```
# which repo owns this repo-relative path
gh search code "tests/fixtures/<something>" --limit 10

# read the file without cloning (confirm the fixture is deliberately incomplete)
gh api repos/<owner>/<repo>/contents/tests/fixtures/x/SKILL.md --jq '.content' | base64 -d

# provenance and per-source counts
python3 - <<'PY'
import json, os, collections
d = json.load(open(os.path.expanduser('~/.agents/.skill-lock.json')))
print('locked:', len(d['skills']))
print(collections.Counter(v['source'] for v in d['skills'].values()))
print('fixture names installed?', [k for k in d['skills'] if k in ('custom-skill', 'default-skill')])
PY

# find the code that emits a warning, then read its surroundings
grep -rl "<warning text>" <runtime-home> ~/.npm    # then open dist/cli.mjs in the npx cache
```

`gh` is the cheap path for anything GitHub-side: authenticated, clean JSON, no page rendering.
Use it instead of a browser unless the question is genuinely visual.

## Judgement

- Fixture-induced warnings are an upstream scanner gap (it should skip test trees or accept
  fixture-format skills). Do not "fix" a local install or hand-edit files in the store to
  silence it.
- The user-facing answer is still mechanism + impact + evidence: what phase produced the path,
  how many skills were actually affected (usually zero, proven from the lock file), and where
  the confirming file lives.
