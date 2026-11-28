# The pull-request run checks the merge ref, not your head

Why a branch can be green locally and red in CI with no defect in it, and what to do instead of
weakening the check.

## The mechanism

A `pull_request` run checks out `refs/pull/<n>/merge` — your branch merged into the **current** base at
the moment the run is created. Any check that compares the tree against main (a version file, a generated
catalog, a lockfile, a changelog rule, a "no uncommitted generated files" guard) therefore evaluates a
combination you never ran locally. Two situations produce it:

1. The base moved a value the branch also sets — a release job that mirrors a version into every artifact
   is the classic case: the branch bumped to X, main bumped to X on its own, the merge ref now has no
   *change* and the guard fires with "unchanged from main".
2. The branch was cut before a base commit that changes the same generated lines.

## Reproduce before believing either side

```bash
git fetch -q origin
git worktree add /tmp/verify origin/main
git -C /tmp/verify merge --no-edit origin/<branch>
(cd /tmp/verify && <the failing check>)
```

If it reproduces, the branch is stale, not wrong. Rebase onto the current base and re-run the repo's own
sync/bump command; re-check. If it does not reproduce, the failure is genuinely in the branch.

## A review is pinned to a revision too

The same ref-binding decides what an approval covers. A hosting-service review object carries the commit it
was submitted against, so before merging on it, match the two:

```bash
gh api repos/<o>/<r>/pulls/<n>/reviews --jq '.[] | {id, state, commit: .commit_id}'
gh pr view <n> --json headRefOid
```

Different values mean commits landed after the review and the sanction does not cover the tree you are
about to merge — re-request instead of merging on the older verdict. A review body, a comment count or an
empty/`COMMENTED` decision field is not the check itself: read the review object and the report file the
reviewer names, and give the ruling in the same message as its conditions (the nit list is where the merge
preconditions usually sit).

A finding the reviewer stumbles on **outside** the change — a stalled scheduled job, a failing sync gate,
an untracked stray file — is a separate work item: report it with its own evidence, keep it out of the
"may merge" sentence, and do not repair it inside the reviewed change's lane. A fix from the wrong surface
arrives as an unaccounted write in the next audit.

## `no checks reported` is a third state

`gh pr checks <n>` printing `no checks reported on the '<branch>' branch` after a push is **not** a pass
and **not** a workflow bug. GitHub could not build the merge ref, and the usual cause is a conflicted PR.
Order of checks:

```bash
gh pr view <n> --json state,mergeable,headRefOid   # CONFLICTING explains the silence
gh api repos/<o>/<r>/actions/runs?head_sha=<sha> --jq .total_count
```

A conflicted PR never gets a run, so every downstream belief ("CI is slow", "the workflow broke") is
built on a missing observation. Fix the conflict; do not "rerun the workflow".

## Rebuild, do not hand-resolve generated conflicts

When the base moved a generated or mirrored value, the conflict appears on every mirrored line for one
semantic change — a rebase that asks you to resolve dozens of identical scalars is a signal, not work.

```bash
git checkout -B <branch> origin/main
git checkout <old-head> -- <the hand-written files only>
<run the generator / bump command>        # mirrored values are derived from the new base
```

This keeps the hand-written diff reviewable and guarantees the mirror is consistent, which hand-resolution
cannot promise: a missed line leaves one artifact on the old value and nothing fails until release.

## Version-bump ownership is policy, and the race follows from it

- **Post-merge bump** (release job bumps on every base push): every other open branch is stale the moment
the bump lands, and fails the base-relative check on its merge ref while passing on its head. Manageable
only by "rebase and re-sync before merging" discipline.
- **Per-PR bump** (each PR bumps its own patch; the release job only tags what is already committed): no
  race, at the cost that a rebase onto a newer base means bumping **again** — an unchanged version is a
  correct failure, not a flaky guard.

Whichever the repo uses, state it in the same sentence as the workflow change so the next branch does not
relearn it from a red run.

## A parallel writer can leave the base half-updated

One repo admits one writer. A stage protocol enforces that inside a session; it says nothing about a
second session driving the same repo. A **direct push to the base branch** that touches one mirrored
version scalar without moving the version file leaves the base failing its own check and the release job
with nothing to tag — the repository is green on the branch that caused it and red at HEAD.

Diagnose from the artifact, not the run log:

```bash
git status --short                      # clean: the bad state is committed
python3 scripts/version.py check       # names the one artifact whose scalar disagrees
python3 scripts/version.py check-bump  # only meaningful on a branch
git log --oneline -3 -- <that file>    # a commit you did not author
```

Fix by re-deriving, never by editing the single scalar back: run the repo's bump command so the version
file and every mirror move together, verify `check` plus the generated catalog, commit, push. Hand-editing
the outlier leaves no record of which value was intended.

Prevention: concurrent sessions coordinate through branches and pull requests, never by writing the base
directly; and after a merge, confirm ownership of the repo before dispatching the next stage run — the
collision is visible as a foreign commit, not as an error.

## Verify a release by tag, not by run status

`gh run list` showing `completed/success` on a base push proves the workflow exited, not that a release
exists. The release itself is the tag:

```bash
git fetch -q --tags && git tag --points-at origin/main
```

An empty result with a green push run means the job skipped or failed to publish — the version check it
runs internally is the first place to look, and a base that fails its own consistency check cannot tag.

## Cost note

Each of these costs one CI round (minutes to half an hour) plus the diagnosis. The cheap prevention: before
pushing a branch older than an hour, `git log --oneline origin/main ^HEAD | head` — if the base moved, rebase
and re-run the generator first.
