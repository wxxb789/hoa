# External bot-review loop (GitHub)

Run from the repo root with `GH_NO_SPINNER=1` exported. In a headless background job `gh` prints
`open terminal failed: not a terminal` — noise, judge by the JSON.

## Ask for a review

A push does **not** trigger a bot re-review. Post one comment whose body ends with the request:

```bash
gh pr comment <PR> --body "<what changed, measured before/after, gate numbers>

@codex review"
```

## Read the verdict

The bot appends a machine-readable marker to its own summary comment. Always read the **last**
matching comment and match it to the head sha:

```bash
gh api repos/<owner>/<repo>/issues/<PR>/comments \
  --jq '[.[] | select(.body|contains("codex-review-state"))] | last | .body'
```

Marker shape (one line, JSON inside an HTML comment):

```
<!-- codex-review-state:v1 {"code_review":{"commit_sha":"<sha>","has_any_findings":true|false,
     "has_unresolved_findings":true|false,"status":"running|completed"}, ...} -->
```

A verdict counts only when `status == "completed"` **and** `commit_sha` starts with the current
head. Poll that conjunction, not "a review exists".

The bot writes the marker **when the review starts**, with `status: "running"` and the new sha
already in it — so a poll loop that greps for the sha alone returns a fake verdict on its first
iteration. Test both fields in one expression (`*completed*<sha7>*` against the extracted
`status`+`commit_sha`, or parse the JSON), and log each poll's `status`/`commit_sha` so the wait
is auditable afterwards.

## Findings

Inline findings come from the review-comments endpoint:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments \
  --jq '.[] | select(.created_at > "<iso>") | "=== \(.path):\(.line)\n\(.body)"'
```

Each carries a severity badge in the body (`P1`/`P2`) and a `<!-- codex-code-review-finding:v1 -->`
trailer. Reproduce the claim before dispatching it.

`commit_id` on a review comment is **not** "the review that raised it" — GitHub re-anchors old
threads onto the newest head, so a fresh `commit_id` can still carry a finding you already fixed.
Anchor by `created_at` relative to your review request instead, and confirm each finding against
the current tree before dispatching a fix.

A push does not close a thread. After landing the fix, reply on every thread
(`gh api repos/<o>/<r>/pulls/<PR>/comments/<comment_id>/replies -f body="Fixed in <sha>: …"`) and
check `isResolved`. A clean verdict on the new head (`has_any_findings: false`) with an empty reply
trail means the findings were never **answered**, not that they were addressed — the reviewer's next
pass may repeat them, and the merge gate counts open threads.

## Threads

```bash
gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<PR>){
  reviewThreads(first:50){nodes{isResolved isOutdated path
  comments(first:1){nodes{author{login} createdAt}}}}}}}'
```

Resolve a thread only after the fix is pushed and CI is green on the fixing commit.
`isOutdated` turns true when the diff moved under the thread — that is not the same as resolved.

List the ids, then resolve each and read the boolean back:

```bash
gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<PR>){
  reviewThreads(first:50){nodes{id isResolved path}}}}}' \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[] | "\(.id) \(.isResolved) \(.path)"'

for t in <id> <id>; do
  gh api graphql -f query="mutation{resolveReviewThread(input:{threadId:\"$t\"}){thread{isResolved}}}" \
    --jq '.data.resolveReviewThread.thread.isResolved'
done
```

Every call must print `true`; a silent `null` is a wrong id format (the id is the opaque
`PRRT_…` string, not the numeric comment id).

## Infra flakes vs real failures

- `gh pr checks <PR>` lists status and duration. A job that dies in <60 s on a download step
  (`curl: (22) ... error: 5xx` while installing a pinned binary) is infra.
- Re-run only the failed jobs, then re-check: `gh run rerun <run-id> --failed`.
- Build the retry into the poller instead of babysitting it: loop `gh pr checks` until no line says
  `pending|queued|in_progress`, and if the settled output contains a `fail`, extract the run id
  (`grep -oE 'runs/[0-9]+' | cut -d/ -f2`) and rerun `--failed` once or twice, logging the reason.
  Bound it — an unbounded rerun loop turns a broken job green-adjacent by attrition.
  Ready-made: `scripts/watch-pr-checks.sh <PR>` does exactly this (fast-fail threshold 60 s, two
  reruns, exit 0/1/2/3) and logs every poll to `ci-watch-<head7>.log`.
- Re-run the *same* commit's job: a new commit does not repair a mirror outage and it invalidates
  the review verdict you already paid for.
