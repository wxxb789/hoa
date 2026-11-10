# Phase 6 — merge gate (mechanical, not remembered)

```bash
scripts/pr-merge-check.py <pr> --repo <path> --verified-head <sha> --gates-rc <rc> [--marker TEXT]
```

Boolean lines and a verdict; exit 0 = merge allowed. `--verified-head` is the SHA you actually ran
the gates on (usually `git rev-parse HEAD` in the worktree you verified), and `--gates-rc` without it
is `UNKNOWN`. A PR whose branch is not checked out reports `head not verified`, never a false mismatch;
a merged or draft PR reports `pr not open` / `pr is draft`. A repo with no machine-review bot reports
`marker: none` and stays blocked unless `--allow-no-machine-review` is passed explicitly. Never merge
on any other basis:

1. every CI check green **on the head SHA**;
2. machine-review marker `status: completed`, `has_any_findings: false`, **on that same head SHA**;
3. unresolved review threads = 0;
4. local gate re-run recorded for this tree (no `--gates-rc` ⇒ `UNKNOWN` ⇒ blocked).

Then `gh pr merge <N> --squash --delete-branch`, `git fetch --prune`, `git checkout main`,
`git pull --ff-only`, prove `gh pr view <N> --json headRefOid` equals the head you verified, report.
Land and re-branch in one sequence so the next goal starts from the merged head:

```bash
gh pr merge <N> --squash --delete-branch
gh pr view <N> --json state,mergeCommit --jq '"\(.state) \(.mergeCommit.oid)"'
git checkout -q main && git pull -q --ff-only && git checkout -q -b feat/<next-goal-slug>
```

A PR that reads `MERGED` while `origin/main` still shows the old head means main had not been fetched,
not that the merge failed. **Done** is merged *and* the next goal branched off the merged head — an
open PR is not done.

Bounded CI watching: `scripts/watch-pr-checks.sh <PR> [max_reruns] [max_polls] [logfile]` waits for a
settled verdict, reruns only jobs that died on an infra step (<60 s fail), and logs every poll. A
download step failing in under a minute is infra — `gh run rerun <run-id> --failed` first, then look
at the code.

A review bot typically posts minutes AFTER CI turns green; a merge fired at "checks pass" skips it
every time. A push does not trigger a re-review — request one and match the marker's `commit_sha` to
the NEW head; the old review keeps the old sha and looks finished. The bot writes its marker when the
review *starts* (`status: running`) with the new sha already in it, so a poll that matches the sha alone
returns a fake verdict on the first iteration — test `completed` and the sha together. Request/read/
resolve commands, thread ids and infra-flake handling: [`references/bot-review-loop.md`](../bot-review-loop.md).

## Pitfalls this phase answers

- **CI green is not merge permission.** PRs have been squashed with unresolved P2 findings under green
  checks; the findings were real. That is why Phase 6 is a script.
- **The bot review loop repeats after a fix.** A fix produces a NEW review on the new head with its
  own findings; budget a second round instead of assuming one fix closes the PR.
- **A release job that bumps after the merge invalidates every other open branch.** If the repo mirrors
  a new version into artifacts on each main push, a branch cut before that bump passes the version check
  on its own head and fails it on the pull-request *merge ref*. Either the repo has each pull request
  bump its own patch (then a rebase onto a newer main means bumping again) or you rebase and re-sync
  before merging — never after CI goes red.
