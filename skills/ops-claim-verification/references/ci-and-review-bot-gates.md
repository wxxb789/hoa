# CI and review-bot gates before landing

Mechanics for turning "the worker says it is fixed" into a landed commit. Pairs with the review-bot
bullet in §1 of the parent skill; this file is the command-level detail.

## Triage a red check before editing code

- `gh pr checks <n>` prints `pending`/`queued` for unfinished jobs and exits non-zero when any job
  failed — when polling, read the **text**, not the exit code.
- `gh run view <run-id> --log-failed` names the failing step. Classify it:
  - Failure inside a dependency or tool **install** (HTTP 4xx/5xx while downloading a release asset,
    a 504 from a mirror) is infrastructure. `gh run rerun <run-id> --failed`, re-poll, report it as an
    infra rerun — never as a code fix.
  - Failure in the repo's own lint/build/test step is the delivery. Dispatch the fix with the failing
    test name and its error text, not with the log pasted whole.
- A rerun that passes proves the runner, not a change in the tree. Say which one you observed.

## Split proof between local and CI

- Run locally only what the diff touches (the focused suite plus anything that imports it). Seconds to
  a minute; it catches the obvious regression before a CI cycle is spent.
- Let CI execute the repo's full chain on the pushed head. When CI runs the same command the repo
  defines, a second full local verify is duplicated wall-clock, not extra evidence.
- Quote which run produced each number (`local focused 30/30`, `CI verify 3m32s pass`). A worker's
  self-reported pass count is a claim; the run is the evidence.

## The review bot's state marker, not its prose

- External review bots publish a hidden marker comment; the marker is the machine-readable verdict, the
  rendered summary is decoration.
- Read the newest one:
  `gh api repos/<owner>/<repo>/issues/<n>/comments --jq '[.[] | select(.body|contains("<marker-token>"))] | last | .body'`
- Gate on three things: `status: completed`, `commit_sha` equal to the head you pushed, and no
  unresolved findings. A marker naming an **older** commit is the previous round's verdict: it reads
  green while the pushed head is unreviewed.
- A push does not re-request the review. Post the documented trigger comment after pushing, then poll
  the marker in the background.
- Inline review threads block the merge on their own: resolve them only after the fix is on the head.

## Verify the finding before dispatching a fix

- Open the cited `path:line` and restate the mechanism in one sentence. A finding is a claim from a
  reviewer, and reviewers occasionally describe a path that already handles the case.
- Check whether a sibling function in the same file already implements the correct rule. If it does,
  the fix is **alignment**, and the prompt must say so ("the rule already exists at X; align Y to it") —
  otherwise the worker invents a third variant and the divergence grows.
- A two-line probe (parse the rewritten text and count nodes; call the resolver on the crafted input)
  is enough falsification, and it costs less than a fix round.

## Background polling instead of a blocking wait

- Poll in a notified background job that appends every iteration to a log file in the task dir: it
  survives session end, leaves a retry trail, and needs no babysitting.
- Set a non-interactive environment for `gh`; a progress spinner in a log is noise, not a failure.
- Stop on the state you actually need (all checks settled, or the marker landed on the current head),
  and bound the loop so a stuck job surfaces as a timeout instead of silence.

## Commit the worker's tree

- `git status --short` then `git diff --stat` must show only what the round claimed. An untracked
  probe script or a generated tarball left behind is part of the tree you are about to commit.
- Commit messages go through a file: a heredoc body containing `&` or `&&` can be read as a
  backgrounding request and the call is refused before anything runs. Write the message to a scratch
  file, then `git commit -F <file>`.
