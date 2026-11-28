---
name: nrs-bounded-landing
description: "Use when landing an accepted candidate into <research-repo>."
version: 1.0.0
author: Scout
license: MIT
metadata:
  hermes:
    tags: [<research-repo>, land, lease, verify, commit]
    category: devops
---

# Bounded landing of an accepted candidate

## When to Use

- A reviewer accepted a candidate patch for named files in `<research-repo>` and issued bounded landing
  instructions. Not for producing the candidate (that is a revision round), not for unaccepted edits, and not
  for files the reviewer has not named.

The deliverable is applied bytes plus a verifiable receipt, not a new candidate.

## 1. Gate the scene before writing

- `git fetch`, then confirm HEAD == `origin/main` and that the target paths have no foreign uncommitted
  changes (`git diff --stat -- <paths>` empty).
- `cmp` each target against the reviewer's pre-apply backup (byte identity, not hashes) and `cmp` each
  payload against the copy you handed over. Compare both sides: a matching payload with a drifted target
  is still a stop.
- Run `git apply --check` on the frozen payloads. Any mismatch, drift, or failed check: stop and report;
  never rebase, re-edit, or land a subset.

## 2. Lease the exact paths

```
python3 bots/lease.py acquire --bot <role> --no-worktree --ttl 3600 \
  --allow-path <path1> --allow-path <path2> --task "<one line>" --json
```

- `release` takes a flag: `python3 bots/lease.py release --lease-id <id>`. A positional id is rejected.
- `status` prints nothing when nothing is active, which is the release proof to quote.
- Do not touch another agent's lease, even a released one; acquire your own on the same resource.

## 3. Apply and read back

- `git apply` the frozen payloads; note but do not normalize their warnings (e.g. `new blank line at EOF`).
- Read the landed pages, not the candidates: grep the load-bearing sentences and report line numbers.
- Confirm frontmatter equality against `HEAD:<path>` by parsing both YAML blocks, not by eyeballing.

## 4. Checks that stay inside your write surface

- `.harness/lint.py` always writes `wiki/_lint-reports/` (another role's surface). For a report-only check,
  `rsync -a --exclude=.git --exclude=__pycache__` the repo to scratch and run lint plus
  `.harness/research_system_validate.py` there. Quote the sandbox report path.
- `bots/verify_writes.py --role <role> --path <p>` per target; the unscoped run also flags other agents'
  uncommitted files, so scope it and say whose those paths are.
- Compare dangling-wikilink totals with the pre-change baseline, and resolve every wikilink your diff adds.
- Count **new** wikilinks against the parent, not against your added lines: strip fenced and inline code first,
  then report `refs / unique targets`. A link that appears in an added line but already existed elsewhere in the
  parent (a page-to-page navigation link, for example) is not new, and a backlink added from two pages is 2 refs
  to 1 target — not 3 new targets.

## 5. Commit and push on explicit paths only

- `AGENTS.md` makes commit+push standing-authorized for this repo, with explicit paths and
  the configured git author (`GIT_AUTHOR_NAME <GIT_AUTHOR_EMAIL>`). Stage only your targets (`git add -- <paths>`), verify
  `git diff --cached --name-status` shows nothing else, commit, then push.
- Never sweep another agent's review directory or evidence files into the commit; a dirty tree belonging to
  a reviewer stays theirs.
- After push, re-fetch and compare `git rev-parse HEAD` with `git rev-parse origin/main` and
  `git ls-remote origin refs/heads/main`. Run these as separate commands: `git rev-parse --short HEAD
  origin/main` errors with `Needed a single revision` in this repo.

## 6. Receipt shape

Real HEAD and its parent, pushed ref equality, per-file numstat from `git show --numstat --format=` for the
commit, checks actually run with their rc, backup paths usable as the rollback unit, which uncommitted paths
belong to whom, and the lease release result. State plainly what you did not do (no `--apply`, no third page,
no metadata change) and any anomaly you left in place for the reviewer to decide.

## Pitfalls

- Counting patch lines with `grep '^+[^+]'`: it drops added blank lines and understates the diff. Only
  `git apply --numstat` / `git diff --no-index --numstat` numbers are reportable.
- Running lint in the checkout and creating a report file you have no write surface for.
- Landing a payload whose trailing blank line changes EOF bytes and then "tidying" it.
- Claiming "applied" from apply-check success alone; only a read-back of the landed file plus a pushed
  commit hash is evidence.
