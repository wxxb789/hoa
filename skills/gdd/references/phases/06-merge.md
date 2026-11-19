# Phase 6 — merge gate (mechanical, not remembered)

```bash
uv run <gdd-skill>/scripts/pr-merge-check.py <pr> --repo <path> --verified-head <sha> --gates-rc <rc> --auto [--marker TEXT]
```

Run the merge-time version precondition below first. Only pass `--auto` with merge authorization:
it can land immediately. Omit it for a read-only manual verdict. Exit 0 means `MERGE-QUEUED`
(request submitted) or `MERGE-OK` (manual gate passed); exit 1 blocks and exit 2 is an error.
`--verified-head` is the full SHA you actually ran
the gates on (usually `git rev-parse HEAD` in the worktree you verified), and `--gates-rc` without it
is `UNKNOWN`. A PR whose branch is not checked out reports `head not verified`, never a false mismatch;
a merged or draft PR reports `pr not open` / `pr is draft`. A repo with no machine-review lane reports
`marker: UNKNOWN` and stays blocked unless `--allow-no-machine-review` is passed explicitly, in which
case it prints `marker: none`. That opt-out applies only when no selected marker exists. Never merge
on any other basis:

1. For the manual path, every CI check green **on the head SHA** — unless the PR head tree has no
   `.github/workflows/*.yml|*.yaml` **and** zero registered workflows/check runs/statuses on that
   head SHA. The CI clause is **not applicable** only on the script's exact `verdict: BLOCKED: no
   checks` (sole blocking reason; items 2–4 pass in the same output). The operator's closeout note
   and PR body record `workflows: 0`, `checks: 0` beside the script's literal `checks: 0 total, 0 ok,
   0 pending, 0 failing (no checks)` line. Not `--allow-no-checks`: red or pending checks, or a repo
   that *has* workflows but shows none on this head, stay blocked.
2. newest `machine-review-state:v1` evidence: `status: completed`, `has_any_findings: false`,
   **full 40-hex `commit_sha` exactly equal to that head**, nonempty operator-selected `model` and
   configured `provider`, full UTF-8 `report`, and matching `report_sha256`;
3. unresolved review threads = 0;
4. local gate re-run recorded for this tree (no `--gates-rc` ⇒ `UNKNOWN` ⇒ blocked).

The manual gate requires structured output from `gh pr checks --json name,state,bucket`.
Upgrade gh if it cannot export these fields; the human table is never used as merge evidence.
Malformed JSON, a missing response, or a command error exits 2. A successful empty list or gh's
explicit zero-check result blocks as `no checks`; the CLI's `--allow-no-checks` is only for
repositories with no CI and never forgives pending or failed checks.

`--marker TEXT` changes only the token, not the required evidence schema. The newest malformed,
incomplete, stale, or hash-invalid marker blocks older clean evidence and cannot be overridden by
the no-review opt-out. Generate evidence from the actual completed report with
`uv run <gdd-skill>/scripts/review-evidence.py --report <file> --head <full-sha> --model <selected-model>
--provider <configured-provider> --findings false --output <comment-file>`; post via `--body-file`
and read back the exact comment before accepting it. Never turn a dirty report into a clean flag.

## Version precondition — after the rebase, before the merge

A version claim is only true for the main it was measured against. **After** any rebase onto
`origin/main` — never before it — run the gate the project **profile** declares for merge time:

```text
git fetch origin main
uv run --no-project --with-requirements scripts/requirements.txt python scripts/version.py check-revisions
```

A repo whose profile declares no merge-time version gate skips this step. It is not part of the
generic protocol: `version.py` exists in `hoa` only, and writing it as universal made every consumer
repo silently skip Phase 6.

A non-zero exit blocks the merge. The fetch comes first so a sibling PR that merged after your last
fetch cannot hide behind a stale `origin/main`. The fix is always a rebase onto `origin/main` plus
raising each `metadata.revision` the gate names above the rebased base.

## Submit and confirm landing

- **Auto:** The script reads `allow_auto_merge` on the target repo and looks for required status
  checks on the actual PR base, in active rulesets or classic protection. If both are confirmed,
  it delegates the CI clause to GitHub (required checks only) and still enforces items 2–4.
  After those pass, it runs `gh pr merge <N> --auto --squash --match-head-commit <sha>` with
  the full `headRefOid` read from GitHub by `gh pr view`, not a typed or abbreviated SHA.
  Branch deletion is left to the repository setting. If submission fails, stop and inspect the
  PR; never treat it as permission to merge manually.
- **Manual:** If capability is absent or unreadable, the same invocation runs the existing manual
  gate. On `MERGE-OK` (or the explicit no-CI exception above), recheck that
  `gh pr view <N> --json headRefOid` still equals the verified head, then run
  `gh pr merge <N> --squash --delete-branch --match-head-commit <full-sha>`.

On `MERGE-QUEUED`, record the PR, full verified head, and target branch in the ledger before waiting:

```bash
uv run scripts/delivery-state.py append --repo <path> --goal <id> --stage merge --head <full-sha> --pr <N> --next merge --note "merge queued; base=<target-branch>"
gh pr view <N> --json state,baseRefName,headRefOid,mergeCommit,autoMergeRequest
```

Keep the ledger at `merge queued` while the PR remains open with auto-merge enabled. On resume,
read the live state before doing anything else; do not resubmit a pending request or run a second
CI waiter. While queued, read the check conclusions with `gh pr checks <N>`: GitHub does not merge
past a failed required check, and it does not report that as a failure either. A required check
that died on an infra step (<60 s, download/setup) gets `gh run rerun <run-id> --failed` once, and
the queue stays as is. Any other failed required check blocks the goal: disable auto-merge
(`gh pr merge <N> --disable-auto`), record it in the ledger, and fix forward as on the manual path. Do not push or retarget while queued: the match flag applies at submission, not as a
permanent lock. Disable auto-merge and verify it is off before changing the head or base. If the
queue disappears or head/base drifts, stop, disable any remaining auto-merge request, and
re-verify before proceeding.

On either path, require GitHub to report `MERGED`, confirm `headRefOid` still equals the verified
head and `baseRefName` still names the intended target, and record the `mergeCommit.oid` and the
ledger close per Phase 7. Only then reset from the updated main, stopping on any failure:

```bash
git fetch --prune
git checkout -q main
git pull -q --ff-only
git checkout -q -b feat/<next-goal-slug>
```

A PR that reads `MERGED` while `origin/main` still shows the old head means main had not been fetched,
not that the merge failed. **Done** is merged *and* the next goal branched off the merged head — an
open PR is not done.

Bounded CI watching (manual path): `uv run scripts/watch-pr-checks.py <PR> [max_reruns] [max_polls] [logfile]` waits for a
settled verdict — checks done *and* the PR `MERGEABLE CLEAN` at the head it started on — reruns only
jobs that died on an infra step (<60 s fail), and logs every poll. A download step failing in under a
minute is infra — `gh run rerun <run-id> --failed` first, then look at the code.

CI green does not run or finish the machine-review lane. Invoke the configured headless reviewer
with explicit provider/model flags; GPT-family endpoints require the configured Responses API route,
not Chat Completions. Do not change runtime configuration or substitute a model to obtain a verdict.
After every push/rebase, rerun review, generate full report evidence, and match the exact NEW head;
an old review can look finished while no longer applying. A running marker never passes, even if its
SHA matches. Recheck the head after review, after posting/readback, and immediately before merge.
Invocation/evidence/readback commands, finding dispositions, thread ids, and infra-flake handling:
[`references/bot-review-loop.md`](../bot-review-loop.md).

## Pitfalls this phase answers

- **CI green is not merge permission.** PRs have been squashed with unresolved P2 findings under green
  checks; the findings were real. That is why Phase 6 is a script.
- **The machine-review loop repeats after a fix.** A fix needs a NEW review on the new head with its
  own findings; budget a second round instead of assuming one fix closes the PR.
- **A release job that bumps after the merge invalidates every other open branch.** If the repo mirrors
  a new version into artifacts on each main push, a branch cut before that bump passes the version check
  on its own head and fails it on the pull-request *merge ref*. Either the repo has each pull request
  bump its own patch (then a rebase onto a newer main means bumping again) or you rebase and re-sync
  before merging — never after CI goes red.
