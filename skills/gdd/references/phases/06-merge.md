# Phase 6 — merge gate (mechanical, not remembered)

```bash
<gdd-skill>/scripts/pr-merge-check.py <pr> --repo <path> --verified-head <sha> --gates-rc <rc> [--marker TEXT]
```

Boolean lines and a verdict; exit 0 = merge allowed. `--verified-head` is the SHA you actually ran
the gates on (usually `git rev-parse HEAD` in the worktree you verified), and `--gates-rc` without it
is `UNKNOWN`. A PR whose branch is not checked out reports `head not verified`, never a false mismatch;
a merged or draft PR reports `pr not open` / `pr is draft`. A repo with no machine-review lane reports
`marker: UNKNOWN` and stays blocked unless `--allow-no-machine-review` is passed explicitly, in which
case it prints `marker: none`. That opt-out applies only when no selected marker exists. Never merge
on any other basis:

1. every CI check green **on the head SHA** — unless the target repository declares **no workflow at
   all**: when the repo lists zero workflow configs *and* the PR carries zero checks/statuses, the CI
   clause is **not applicable**, and a `BLOCKED: no checks` verdict from the merge script is read as
   *not applicable* for that head rather than a failure. The merge then rests on items 2–4, and the
   verdict line plus the PR body must carry the evidence that made it inapplicable (`workflows: 0`,
   `checks: 0`). This is not `--allow-no-checks` and not an excuse for red or pending checks: a repo
   that *has* workflows shows none on this head, or any failing/pending check, stays blocked;
2. newest `machine-review-state:v1` evidence: `status: completed`, `has_any_findings: false`,
   **full 40-hex `commit_sha` exactly equal to that head**, nonempty operator-selected `model` and
   configured `provider`, full UTF-8 `report`, and matching `report_sha256`;
3. unresolved review threads = 0;
4. local gate re-run recorded for this tree (no `--gates-rc` ⇒ `UNKNOWN` ⇒ blocked).

The checks clause reads gh's structured output (`gh pr checks --json name,state,bucket`). When that
read is unavailable and only gh's human table remains, the parsed table is **advisory**: a non-green
row blocks as always, and an all-green or empty table blocks too, with `verdict: BLOCKED: checks
unreadable`. A table-only read can never produce MERGE-OK — gh's table is a display format whose
field count, emptiness, case and row set are not a contract, and every parse of it has produced
another way to lose a row. An operator whose gh cannot do `--json` restores the table's authority
explicitly with `--allow-table-only-checks` (named in `pr-merge-check.py`'s docstring as well); the
default fails closed, and the opt-in bypasses neither the exact-header rule nor the unknown-verdict
rule. A nonblank line without a tab is not a row either: it carries no STATUS field, so the parser
ignores it and prints one `pr-merge-check: ignored table line without a tab (not a row): '…'`
diagnostic per such line on stderr — the only trace of a truncated row, and the parsing limitation
the opt-in accepts. In that fallback only gh's check-result exits carry CI state — 1 (a check
failed) and 8 (a check is pending). Any other non-zero exit is an operator error: it exits 2 with
its own exit code and message preserved, so an interrupted (2) or unauthorised (4) read cannot
become a `checks pending` verdict. `--allow-no-checks` forgives a zero-check read, but on its own
cannot authorise table-only evidence; together with `--allow-table-only-checks` the table is
authoritative and an empty one is accepted. Neither opt-in forgives a reported pending or failing
check, with or without the other.

`--marker TEXT` changes only the token, not the required evidence schema. The newest malformed,
incomplete, stale, or hash-invalid marker blocks older clean evidence and cannot be overridden by
the no-review opt-out. Generate evidence from the actual completed report with
`<gdd-skill>/scripts/review-evidence.py --report <file> --head <full-sha> --model <selected-model>
--provider <configured-provider> --findings false --output <comment-file>`; post via `--body-file`
and read back the exact comment before accepting it. Never turn a dirty report into a clean flag.

## Version precondition — after the rebase, before the merge

A version claim is only true for the main it was measured against. **After** any rebase onto
`origin/main` — never before it — run the gate the project **profile** declares for merge time:

```bash
python scripts/version.py check-merge      # hoa; other repos: whatever their profile names
```

A repo whose profile declares no merge-time version gate skips this step. It is not part of the
generic protocol: `version.py` exists in `hoa` only, and writing it as universal made every consumer
repo silently skip Phase 6.

A non-zero exit blocks the merge. `check-merge` reads the remote's real main with `git ls-remote`, so a
sibling PR that merged after your last fetch cannot hide behind a stale `origin/main`; it also fails
when tag `v<VERSION>` already exists on the remote. The fix is always
`git fetch origin main && python scripts/version.py bump` — never a hand-edited `VERSION`.

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

Bounded CI watching: `scripts/watch-pr-checks.py <PR> [max_reruns] [max_polls] [logfile]` waits for a
settled verdict — checks done *and* the PR `MERGEABLE CLEAN` at the head it started on — reruns only
jobs that died on an infra step (<60 s fail), and logs every poll. A download step failing in under a
minute is infra — `gh run rerun <run-id> --failed` first, then look at the code.
`watch-pr-checks.sh` is the POSIX twin with the same exit codes.

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
