# Contributing a fix upstream (repo you do not own)

Use when the fix is not for our code: the running install must stay untouched and the result is a PR to
the upstream project. The clone is disposable; the running checkout is not.

## 1. Set up without touching the running install

```bash
mkdir -p ~/repos && cd ~/repos
[ -d <name>/.git ] || git clone --depth=50 https://github.com/<owner>/<repo>.git <name>
cd <name> && git log -1 --format='%h %ad %s' --date=short   # record the base commit
uv sync --group dev --no-install-project                   # deps live in ./.venv, not the runtime env
.venv/bin/python -c "import pytest; print(pytest.__version__)"
```

`uv sync --group dev` is the cheap path when the repo keeps test tooling in `[dependency-groups]`. If the
repo has no lockfile, fall back to its documented dev install; never `pip install` into the venv the
running service uses.

## 2. Locate the behavior, then confirm it on `main`

- `grep`/`search_files` for the user-visible string (status name, message, field) and read the whole
  function that produces it, plus the comment above it. Deliberate non-failures are usually explained
  there, with the issue that forced them.
- Read the layer that *writes* the value as well as the one that *renders* it: a status can be correct
  in one and stale in the other, which is exactly the shape of most "reports success but did nothing"
  bugs.

## 3. Reproduce before fixing

Write the failing test first, in the suite that already owns that module. Small and local: build the
object the production path builds, assert the status/output users see, not the internals.

```bash
.venv/bin/python -m pytest tests/<area>/<new_test>.py -q      # red
# fix
.venv/bin/python -m pytest tests/<area>/<new_test>.py -q      # green
```

## 4. Pre-existing failures

```bash
git stash -u
git checkout <base> -- . 2>/dev/null || true
git stash pop  # only after the run below
.venv/bin/python -m pytest tests/<file>::<test> -q   # same failure on a clean tree?
```

Simplest reliable sequence: `git stash -u` → run the single test → `git stash pop`. Record the base SHA
and paste the failure line in the PR body under the checklist item about the suite.

## 5. Gates

```bash
.venv/bin/python -m pytest tests/<area> -q            # targeted, -x for the first error
.venv/bin/python -m pytest tests -q > /tmp/suite.log  # full: background it, it is minutes
.venv/bin/python scripts/check                        # repo-specific gate, if present
.venv/bin/python -m ruff check <changed files>
```

Run the long suite as a background job and keep working; do not block the turn on it.

## 6. Commit and PR

Conventional commit, one logical change per commit; the body explains the user-visible symptom, not the
file list.

```bash
git checkout -b fix/<short-slug>
git add <files>
git commit -F - <<'EOF'
fix(<scope>): <observable symptom in one line>

What the user saw, why the code caused it, what the fix changes, and what stays deliberately
unchanged.
EOF

gh repo fork <owner>/<repo> --clone=false
git remote add fork https://github.com/<you>/<repo>.git
git push -u fork fix/<short-slug>
gh pr create --repo <owner>/<repo> --base main --head <you>:fix/<short-slug> \
  --title 'fix(<scope>): <symptom>' --body-file <body.md>
gh pr view <N> --repo <owner>/<repo> --json state,mergeable,files
```

## 7. Body skeleton (adapt to the repo's template)

```markdown
## What does this PR do?
<the symptom, the mechanism, the one-line shape of the fix>

## Related Issue
Related to #N (different root cause: ...). This PR does not close it.

## Changes Made
- <path> — <what and why>

## How to Test
<exact commands and their output>

## Checklist
- [x] <only what you actually ran>
- [x] Suite: N passed; the only failure is <test>, which fails on a clean <base-sha> too
```

## Failure modes that cost a review cycle

- **Fixes an adjacent issue.** `Fixes` auto-closes; on a different root cause that is a contract error.
  Use `Related to ...` and state the difference.
- **Reverses a documented decision.** A comment citing an issue number for "keep this non-fatal" means
the naive fix was already rejected once. Ship the observability half and say why.
- **Leaves an old-behavior test red.** Update that test with the new contract; the reviewer will not
  accept a fix that breaks the suite.
- **Claims pre-existing without proof.** One `git stash` run is the proof.
- **Pushes before confirming scope.** A PR on someone else's repo is public and durable; get the repo,
  base and behavior change confirmed first.
