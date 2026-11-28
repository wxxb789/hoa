---
name: code-review-gates
description: "Use before merging: inspection passes, verdict markers."
version: "0.1.0"
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [review, merge, gates, pr, verification]
    related_skills: [gdd, delegated-work-acceptance, multi-model-generation-pipeline]
  categories: "software-development"
---

# Code review gates

Topic depth: `references/platform-premises.md` — a suite leg that fails on one OS only (undeclared host premises: path grammar vs kernel semantics, dual-dialect assertions, the import-time host probe, the idiom lint).

## The reviewed revision is pinned to the PUSHED head

A verdict must name the revision it saw, and a lane whose receipt has to match `gh pr view --json
headRefOid` reads the **pushed** head, never a local commit. Order a fix round
`verify → commit → push → re-run the lane`: with the fix committed locally only, the lane either refuses the
run or measures the previous bytes, and the verdict it produces then describes a revision that no longer
exists. Re-check the equality the lane itself checks (HEAD vs `headRefOid`, clean worktree) immediately before
and after the run; keep the exact diff, the receipt and the fixing SHA in the round's evidence; treat a push
landing mid-round as invalidating that round, and re-run on the new head instead of carrying the old verdict
forward. A finding is closed by the fixing SHA the lane can see plus a measured result — never by a comment or
a marker alone.

What must be true before a change is merged, and how to tell a real review verdict from a placeholder.
This is the inspection half of the delivery loop; the full contract-driven loop lives in `gdd`. Keep them
consistent: the rules below hold for every merged PR, including the ones no goal contract describes.

Two homes, one rule set: the shared skill library (`gdd`, `delegated-work-acceptance`) is the authority for
the loop, and it is edited in the library repo through that repo's own PR flow — a host profile cannot write
it with skill tooling (the names resolve to other profiles' materialised copies and the write is refused).
This skill carries the same rules where the host can own them; when the library copy gains a change, keep the
two in step rather than letting one drift.

## When to Use

- About to merge a PR, or about to say a change is ready to merge.
- A reviewer's verdict came back and you must decide whether it is a verdict.
- A merge is discovered to have shipped without the required inspections.
- A review lane (hosted bot, CLI, model provider) stopped answering and the stage still has to close.

## Standing rules — no exemptions

- Every PR that gets merged passes both inspections first: a **simplify report that was applied** and a
  **code review whose findings were fixed**, with the repo's gate green. A one-line fix is not exempt —
  "it is only a small diff" is how an unreviewed change reaches `main`. Only the operator waives a stage,
  and only by saying so.
- A green CI run is a gate, not the acceptance. Keep the two facts separate in the report: *the increment
  was inspected* and *the operator re-ran the gate on the merged head*.
- Re-run the gate on the final tree yourself; a run reported by the author is a claim.
- **The head's own CI run is the gate, not the delegated run's gate list.** A run that gates only the
  files it touched reports green while a repo-wide check it never invoked fails: a relative link in a new
  document that no longer resolves, a locale key that lost its pair, an artifact over its byte budget.
  After the branch is pushed, read `gh pr checks <n>` on the pushed head sha before merging — and treat a
  failure the run could not have seen as information about the run's gate list, not about the change.
- **Classify a red check before touching the change: transfer failure vs the workflow's own code.** A step
  that failed while moving bytes (HTTP 4xx/5xx on a release asset, a mirror 504, rate limiting) is
  infrastructure — rerun it and report the rerun. A resolver verdict is deterministic and its own text says
  so — `version constraints conflict`, a module that `declares its path as` a different import path, an
  unknown flag, a runner the tool does not support: it fails byte-identically on every rerun and every
  matrix leg, so a rerun loop only burns wall-clock and hands the operator the same red check with no new
  information. The local gate never executes the workflow's install steps, so a green local run says
  nothing about them: reproduce the install line on the host with a scratch prefix
  (`GOBIN=<task>/gobin go install <module>@<version>`, then `<prefix>/<tool> --version`) and dispatch the
  the fix with that command, the resolver's error text, and the required local reproduction in the prompt.
- **A suite outside the diff that passed on the immediately preceding head is not a flake by default.**
  Pull that suite's line out of the previous head's green run (`gh run view <green-run-id> --log |
  grep -E '<test name>|summary:'`) and compare. PASS shortly before, on the same runner image, plus a fix
  round that touched the harness the suite sits on (temp-dir/`TMPDIR` teardown, process-group cleanup,
  `PATH` assembly) makes that round the **suspect** — the change under review is where a new race would
  live, not the weather. Quote both observations ("PASS 42.66s on the previous head; `OSError: [Errno 39]
  Directory not empty` while cleaning its temp dir on this head") and reproduce locally before dispatching
  anything: an infra rerun and a code fix are different branches of work. An unattended driver that blocked
  a whole series on one red check has no rerun policy, so its verdict reads "these bytes are not green" —
  decide flake vs defect before resuming whatever it queued.
- **A head with zero runs is not a green head, and it is not the no-workflow case either.** Read the run set
  per SHA from the head you are about to merge: `gh api repos/<o>/<r>/commits/<sha>/check-runs --jq
  .total_count`, `gh api "repos/<o>/<r>/actions/runs?head_sha=<sha>" --jq .total_count`, and
  `gh run list --branch <b>` to see which SHA each run actually tested. Zero runs on a head whose sibling
  branches keep triggering normally means the push's event was suppressed (a credential that cannot trigger
  workflows, a platform hiccup) — but read the PR's own mergeable state before blaming the push: a
  `CONFLICTING` PR has no `pull_request` workflows scheduled at all, so its empty check table is the
  conflict, and the runs appear once the base is merged in (see `concurrent-agent-repo-workflow`). Report
  the head as **unverified**, and require a fresh run before the merge gate. When the workflow declares `workflow_dispatch:` re-trigger it by hand (`gh workflow run <name>
  --ref <branch>`) rather than inventing a dummy push. A "CI green" claim that names an earlier head is
  describing different bytes, however recent the green looks.
- **Run the gate with an interpreter that satisfies the repo's requirements, and with a writable
  `TMPDIR`.** A checker reading a declared dependency the default interpreter lacks (a system `python3`
  without the repo's requirements file installed) reports a step-level red the increment never caused, and a
  selftest doing `mktemp -d` in a sandboxed or non-writable scratch dir reports a mass failure
  (`selftest: 14/91 ok`) that is pure environment. Build one interpreter that satisfies the repo's
  requirements, put it first on `PATH` for the whole chain, and set `TMPDIR=/tmp` as CI does — then state
  which interpreter and which `TMPDIR` produced each line of evidence.
- **A red step that is not yours is a Known limit, not a case to delete.** A pre-existing suite failing for
  an environment reason the increment cannot fix (a sandbox that refuses to fork for `tmux`) goes into the
  PR body with the direct probe showing the environment cause and the fact that the failing files are
  frozen; editing them or dropping the case to reach green is the one disqualifying move — and the softer
  forms of that move are the same move: a `condition:` that skips the suite on that runner, an exclusion
  list, a retry wrapper added until it goes green. Each makes a real defect invisible rather than closed.
- **A red that does not reproduce on the synced head is dispositioned by mechanism, and the mechanism
  decides whether it is yours.** Reproduce it on the merged head before anything else, then name what the
  failure actually was: a suite deleting its own `TemporaryDirectory` while a child still writes into it
  (`OSError: [Errno 39] Directory not empty`) is *that suite's* teardown race, not a host or toolchain
  dependency, and no placement of the case in a test plan fixes it. State the limit of the evidence you
  hold — one green reproduction excludes the increment as *the* cause, it does not identify the race — and
  record the plausible trigger inside that window (a change to how suites are launched or reaped) rather
  than asserting innocence. Then hand the hardening decision to the review round instead of shipping the
  skip yourself.
- **Match the remediation to the failure.** A behavioural finding goes back to a stage (a run's diff
  belongs to the run, or the next review cannot attribute it). Gate bookkeeping — a dangling doc link, a
  stale count in a comment — is fixed in place on the same branch, with the failing check re-run by hand
  and quoted in the report; re-dispatching a stage for it costs an hour and buys nothing. When a
  behavioural finding already forces a stage run, the bookkeeping finding rides in the same findings
  file — one dispatch, both fixed — and every entry in that file is marked FIX or SKIP with its reason,
  so nothing is dropped silently. When the round's findings are *all* of that class (a sentence the code no
  longer supports, a stale comment, an assertion that samples too late, leftover scaffolding), the
  coordinator applies them itself in one pass, mutation-proves each new pin itself, and goes straight to the
  re-review — and **says so in the next round's packet** ("the operator applied these; grade the edits as
  code, not as a lane's report"), carrying each pin's mutation and the failure signature it produced into
  that packet, because there is no lane report for the reviewer to read the proof out of. A dispatch for
  comment-and-assertion edits costs a round-trip and, if that lane hands its own
  verification to a background child, returns a `done` with no evidence behind it. Re-prompting does not
  close that: a lane told to start its acceptance battery in the background and report afterwards does
  exactly that and ends its turn, so the run is lost with no exit code anywhere — measured twice on the
  same lane. Dispatch through a launcher that awaits the lane's in-flight async work (`--wait-async` on
  the host harness), and when one lane fails this way a second time treat it as the harness rather than
  re-wording the instruction.
- **A cleanup, guard or reset you add on a failure path must honour every mode flag the success path
  honours.** A fix that removes scratch state, restores a file or reaps a child on a refusal path
  contradicts a documented mode the moment it runs unconditionally: a `--keep` / `--dry-run` /
  `--no-clean` contract describes *every* exit, and the refusal path is exactly where an unconditional
  `rmtree`, `unlink` or reset breaks it silently while the success path keeps the flag's promise. Before
  dispatching, list the flags whose text speaks about the act you just added and read every exit path
  (success, each refusal, the `finally`) against each of them.
- **When the coordinator applies the findings itself, sweep the previous round's finding *classes* over its
  own diff before dispatching the re-review.** Those edits are unaudited until the next round reads them,
  so the round that closes round N is where round N+1's defects are born. Classify the findings you just
  fixed and re-run each class against your own edits: (i) every count, chain or `§`-pointer in the evidence
  record that the new cases made stale — re-derive each number from the command that produced it, never
  from the record it already sits in; (ii) every line the fix added or moved — ask *which case goes red if
  this line is deleted or inverted?* and execute that mutation; (iii) every mode flag the touched path can
  exit through. A pass that only re-reads its own diff closes nothing the next round would not have found.
- **A documentation-only increment is inspected too, and its prose is the defect surface.** A release
  note, a README section or an evidence record goes through both stages like any diff. The simplify
  preflight excludes prose from its Delete/Refactor categories, so its answer can be "nothing to
  simplify" while its possible-defects section still carries real findings — grade that section as
  findings, not commentary. Verify each claim in the prose against the code it describes: a command it
  names must exist in the CLI's dispatch table (the `bin/<cli>` entry point, the `bin` map in
  `package.json`, the `--help` text) with every required flag, and a count or a rule ("each requested
  once", "on the X boundary") must match the assertion the code actually makes (`> 0` is not "exactly
  once"; collapsing every run of whitespace is not a boundary strip). Release notes are copied and ship
  permanently, so a wrong command there outlives every gate that ran. Prefer wording lifted from the
  repo's own docs over fresh paraphrase — the doc is often the surface another check reads. **Scope every
  rule to the mechanism you actually reproduced.** A rule that generalises one observation into a universal
  law — teardown kills a backgrounded child; the tool resolves a path argument against its own root — is a
  factual defect the next round blocks on, correctly: name the condition the evidence covers (which launcher
  cleanup contract, which resolution base the tool documents) and the counter-case that would break it,
  because a reader on another host or launcher follows the universal phrasing and is wrong. Grade your own
  generalisation the way the reviewer will, since a prose increment's only defect surface is the scope of
  its claims.
- **A prose fix reflows the text and invalidates recorded counts.** Editing a hard-wrapped bullet or a
  table changes the `--stat` numbers quoted in the stage report, the diff block in a closeout record and
  any status entry. Have the authoring lane *report* the new numbers and refresh the out-of-repo records
  yourself: the lane's write surface is the repo, so a lane editing task records elsewhere is an
  unaccounted write. **Refresh a count without rewriting history:** a block that names its own run (its log
  path, the stage whose state it heads) stays that run's measurement — re-run the gate, put the new numbers
  and the delta (`old → new`, plus the file that caused it) in the section belonging to the new state, and
  say which section measures which state. Both failures are the same shape: silently rewriting an older
  block with numbers its log never printed, or leaving a reader whose first hit is a stale figure. (The
  library copy of this loop is `gdd`'s phase 3 — keep the two in step.)
- **Repairing one stale claim does not certify the artifact — the remaining false statements become a
  measured follow-up list, kept out of the diff.** An artifact that carried one expired claim (a comment, a
  README, a release note) usually carries more: a count that drifted, a behaviour the code no longer has.
  The increment's scope is the statements it was raised for, so have the review lanes *report* every other
  statement the code contradicts, apply none of them, and hand the operator the list with numbers re-derived
  by the command that produced them (`grep -c 'integrity:' pnpm-lock.yaml` → 435 against a comment claiming
  553; production `dependencies` counted from the manifest → 15 against "the 11 this manifest names") and the
  `file:line` you re-located yourself — a lane's line numbers are a claim like any other, and two lanes
  citing 162/174 and 167/179 for one construct means at most one is right. Grep the text and cite the tree.
  A finding the increment's *own* sentences introduced is fixed, never deferred; a pre-existing one is
  deferred only on this evidence, and the verdict line then reads *no defect in the changed sentences; N
  pre-existing false statements recorded for follow-up*, never "phases clean" or "all green". A marker whose
  verdict is `FINDINGS` is not a clean round, and the follow-up is offered to the operator as a decision
  (second PR now, or record only) rather than shipped silently. When the decision comes back *fix it
  now*, that follow-up is still a prose increment and its edits have their own shape: **replace the pinned
  count with the form it was an instance of, never with the freshly re-derived number** — "every resolved
  entry of the dependency tree", "the direct dependencies this manifest names" survive the next dependency
  bump, while a corrected number is the right *evidence* in the report and the wrong *edit* in the file. A
  rotted claim takes three forms, each settled by reading the mechanism rather than the sentence: an
  absolute negation about behaviour (read the input's default and the step that consumes it), a pinned
  count (measure it), and lifecycle tense (true only while a package is unpublished, a tool uninstalled, a
  flag unset). Sweep the whole tree for the class with one pattern and report the remaining hits
  **classified** — same defect, or a second meaning of the same word — because an unclassified sweep reads
  as shallow; and re-wrap every sentence you edit inside a hard-wrapped comment block to that block's own
  width, since a ragged diff is noise the next reader pays for. Patterns, commands and PR-body shape:
  [`references/stale-claims.md`](references/stale-claims.md).

## Reading a reviewer's verdict

- A verdict counts only when the reviewer's machine-readable marker says `completed` **and** its
  `commit_sha` matches the head you are about to merge. Read `status` before the findings field.
- `has_any_findings: true` with `status: failed` is the **failure shape, not a finding**: the review
  aborted (quota, expired credential) and produced nothing. Read the reviewer's own comment body for the
  reason, and treat the stage as **unclosed** — not passed, not failed.
- A reviewer writes its marker when the review *starts*, so polling for the head sha alone returns a fake
  verdict on the first iteration.
- A review that never ran leaves no inline findings: an empty findings list plus a failed marker is
  "nothing happened", not "nothing found".

## The mechanical merge gate

Run the repo's gate yourself on the exact head before saying a PR may merge. It answers with booleans,
and its refusal names the clause that blocks — which is exactly what the report needs:

```bash
python3 <skill-package>/scripts/pr-merge-check.py <n> --repo <path> --gates-rc 0 --verified-head <full-sha>
```

- Exit `0` = MERGE-OK, `1` = BLOCKED, `2` = usage/`gh`/`git` error. The printed lines are the evidence:
  `checks` (ok/pending/failing counts), `review` (marker status, findings, head match, report hash),
  `threads` (unresolved count), `gates` (`rc` and when it ran), `verdict` naming the blocking clauses.
  One blocked clause with everything else green is a PR that is one step away — say that, rather than
  calling the whole thing unfinished.
- `--gates-rc 0` and `--verified-head` are the local gate result *and the sha it actually ran on*: a gate
  result counts only when the head it ran on is verified, otherwise the clause is UNKNOWN and blocks.
  Supplying flags the run did not earn turns the gate into a rubber stamp.
- The marker clause reads the newest evidence comment across **all** comment pages (a `gh pr view --json
  comments` read truncates on big PRs) and never falls back to an older comment when the newest is
  malformed. The default token is provider-independent and pins the reviewed commit, the model and
  provider that produced the report, and the report's SHA256. `--allow-no-machine-review` /
  `--allow-no-checks` print that they accepted the clause — use them only for a repo that genuinely has
  no such surface, never to clear a red clause — and for the checks clause, establish the absence from the
  repo's own config before claiming it (next bullet).
- **Quote the gate's verdict in the gate's own vocabulary — a partial pass is not the gate.** Where a repo's
  gate separates required from optional steps (a `gate-required.txt`-style list plus a `PASS (partial: <steps>)`
  line), an unavailable *non-required* step still leaves `GATE: PASS (partial: …)` at exit 0, so an evidence
  record that reads "gate green" off the exit code overstates what the command printed and every later reader
  inherits the overstatement. Keep the two outcomes apart in the record, scope the fail-closed claim to the
  required set and name the file that defines it, and where the increment's acceptance needs the whole gate
  require the **unqualified** `PASS` explicitly — a partial run is not what "gate green" means, whatever its
  exit code. Grade a delegated lane's evidence record on this axis: a sentence claiming more than the command
  printed is a finding, not a summary.
- **A repository that declares no workflow at all has no CI clause to satisfy — establish that from its
  config, then record the evidence.** Read the repo's CI directory (`.github/workflows` or the equivalent)
  **and** the PR's check list: zero workflow configs plus zero checks/statuses on the head means the
  green-CI clause is *not applicable*, and the merge rests on the remaining clauses — marker evidence on
  that head, unresolved threads at zero, and the local gate re-run you performed. Write what made it
  inapplicable (`workflows: 0`, `checks: 0`) into the verdict line and the PR body, and say the clause is
  inapplicable rather than green. The boundary is the whole rule: a repo that *has* workflows but shows
  none on this head, or any failing or pending check, stays **blocked**. This is not `--allow-no-checks`,
  and an unrecorded judgment is indistinguishable from a waived gate.
- **A review you ran yourself is not yet a verdict the gate can read.** The gate reads a marker comment
  on the PR, not your report file: build the comment from the exact report bytes with the skill package's
  evidence tool (`review-evidence.py --report <file> --head <full-sha> --model <id> --provider <id>
  `--findings false|true`), post it, read the newest comment back, and only then run the gate — and when you compare
  the read-back to the file, allow only the trailing newline the platform appends (`sent.rstrip() ==
  back.rstrip()`): a one-byte length difference is that newline, not a stale or edited comment. Verify the
  run's receipt first (`review-receipt.py --session-dir <dir> --provider <id> --model <id> --transport <id>
  --api-id <id>`): the marker's model, provider and transport fields are copied from that record, so an
  unverified receipt turns the whole model-pinned chain into your own assertion — and read the gate's
  `report_hash` line, where `match` is the only proof that the comment on the PR is the bytes the tool
  built rather than a stale or hand-edited copy. Then answer and resolve every open review thread with the
  measured control that closes it — the gate blocks on unresolved threads even when the fix is already
  merged into the branch.
- **An unresolved thread is cleared by a verified control, never by prose — and a thread whose finding
  holds is a fix, not a reply.** Read the code the thread points at before answering anything: an inline
  anchor is pinned to the head it was written on, so  re-locate the construct in the current tree (`search_files` for the symbol, read the function) instead of
  trusting the line number or the diff that opened it. Finding
  holds → dispatch the fix first (its own reproduction, pin and mutation), then reply with the control —
  the `file:line` that now enforces the rule plus the test that fails without it — and resolve. Finding
  does not hold → reply with that same evidence and resolve. Resolving a true finding with a paragraph
  re-opens the class at the next head, and the gate counts the open thread either way, so a thread left
  open next to a fix already on the branch is an unclosed blocker however green everything else reads.
- **Enumerate the open threads from the API, not from the PR's comment list.** A hosted bot's findings live
  in *review threads*: `gh pr view --json` exports no such field and a `comments` read never shows them, so
  a fix round built from the comment list works from a paraphrase or misses the finding entirely. Enumerate
  unresolved ones with GraphQL —
  `gh api graphql -f query='{repository(owner:"<o>",name:"<r>"){pullRequest(number:<n>){reviewThreads(first:50){nodes{id isResolved comments(first:5){nodes{author{login} body}}}}}}}'`
  — and use the returned count as the number the gate's `threads` clause must read after you resolve them.
- **Post a thread reply and resolve the thread through one JSON payload, never through `-F` flags.** A
  mutation carrying a variable declaration cannot be passed as
  `gh api graphql -f query='mutation($tid:ID!,$body:String!){…}' -F tid=… -F <user>@example.com`: the flags are
  read as part of the query text and the call dies with `Expected VAR_SIGN, actual: COLON`, so the reply
  never posts, the thread stays open and the gate keeps blocking on it. The **lowercase** string form does
  work for both mutations — `gh api graphql -f query='mutation($tid:ID!,$body:String!){…}' -f tid=<thread-id>
  -f body='<reply text>'` — multi-line bodies, backticks and quotes included; the uppercase `-F` (typed /
  read-from-file) form is the one that dies. Write
  `{"query": "<mutation with $vars>", "variables": {"tid": "<thread-id>", "body": "<reply text>"}}` to a
  file and call `gh api graphql --input <file>` — the same shape for
  `addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$tid, body:$body})` and
  `resolveReviewThread(input:{threadId:$tid})`. Then read the threads back (`isResolved` per node) and let
  that zero be what the gate's `threads` line must print; a resolved thread whose reply never posted reads
  identically in the gate and leaves no evidence for the next reader.
- **A PR body, evidence comment or commit subject carrying quotes, backticks or line breaks goes through a
  file (or an argv list), then gets read back.** Write it to a file and apply it (`gh pr edit <n> --body-file
  <path>`, `--input <json>` for GraphQL), never as a shell-quoted argument: a body quoting code dies in the
  shell (`unexpected EOF while looking for matching quote`) with nothing posted — and a commit subject an
  apostrophe or a parenthesis rides in dies the same way in `bash -lc '…'`, before git is reached, so the
  failure reads as a git error while nothing was committed. Pass such a message as an argv list
  (`subprocess.run(['git', '-C', wt, 'commit', '-m', msg])`) and read `git log -1 --oneline` back,
  and re-check the applied text
  afterwards (`gh pr view <n> --json body`, or the comment read-back) — an edit that never landed leaves the
  PR claiming an earlier draft's wording, and a squash merge writes that body permanently into the default
  branch's history.
- **Run the gate once the checks have finished, and read a hard exit 2 as "not yet", not "broken".**
  `gh pr checks` exits non-zero while any check is pending and newer `gh` builds dropped `conclusion` from
  `gh pr checks --json`, so the gate's JSON read fails and its text fallback raises with the check table's
  first line as the message. All checks completed is the precondition for a verdict; a gate that cannot
  read the check list is an unrun gate, and the reason is the unfinished CI, not the tool. (Upstream, the
  parser belongs on the fields the current CLI still exports — `bucket`/`state` — and should report
  `pending` rather than raise.)
- **Point the wrapper at the package path that exists now.** A thin host wrapper forwarding to a skill
  script dies with `portable implementation not found` (exit 127) the moment the upstream skill is
  renamed or moved: the gate is then *absent*, not green. Repair the path and re-run; a gate you could
  not execute is reported as not run. Repair it as a **candidate list, not a fresh literal** — current path
  first, pre-move path second, and a miss printing the candidates it tried — because the library a wrapper
  forwards into can be reorganized by another machine while this closeout is running (a whole skill tree
  moving one directory deeper invalidates every wrapper holding its old location at once), and a single
  literal turns that reorganization into a failure *mid-sequence*: the review marker is already posted, the
  PR is one step from merge, and the one tool that would clear it exits 127. Verify the repair by executing
  each wrapper (`--help`, rc 0) rather than by reading the new path out of the diff.
- **A merged upstream fix is not a live fix — and that covers the rule text, not only the code.** Where the
  host consumes the skill through a symlink into a repo checkout, both the code a wrapper executes and the
  prose a later agent reads are whatever branch that checkout is on: a change merged to the default branch
  does nothing until the checkout is fast-forwarded onto it, so a lane that parks the shared checkout on its
  own feature branch freezes the live skill content for every agent on the host. Prove it in the resolved
  tree before trusting anything derived from it — resolve the symlink, then read or `search_files` the target
  path for the new text or module, because the merge commit sitting on `origin/main` is not evidence about
  the file on disk. Do not repair it by switching that worktree yourself: it holds another lane's in-flight
  branch, and you would be the second writer in its tree. Report the staleness with the branch, the
  resolving path and the merge commit it is missing, and let the owning lane return the checkout to base.
  Localize the merge by branch, not by symbol: `git -C <checkout> worktree list` names which branch each
  tree holds, and only then decide whether the stale content is yours to wait on or to escalate.
- **A draft PR blocks the gate before any other clause is read.** The verdict comes back `BLOCKED: pr is
  draft` with no check, marker or thread lines, so a draft hides a PR that is otherwise one step from
  merge. Mark it ready (`gh pr ready <n>`) — a state change on a PR you own, not a review — then re-run;
  a verdict of "draft" is a precondition you reset, never a defect to fix. The clauses a draft verdict *does* print are placeholders: the gate line reads `gates: UNKNOWN (rc=0)` even when the local gate passed on that exact head, so a report quoting that read tells a later reader the gate never ran. Clear the draft, re-run, and only then quote any clause from the verdict.
- **Drive the closeout from one script per round, whose steps print their own evidence.** The merge gate
  is a fixed ordered sequence (head identity against worktree *and* remote, the lane's receipt, marker
  build → post → read back, thread reply → resolve → count, PR body apply, mechanical gate, squash merge
  → read back). Hand-typing it across a session is where a clause gets skipped and where `--verified-head`
  / `--gates-rc` get supplied unearned. Put the sequence in a script taking the reviewed sha as its only
  argument, printing each step's evidence as it goes and aborting when step 0 (three-way head identity)
  fails, so the merge is one re-runnable command and a resumed closeout repeats the same sequence instead
  of reconstructing it from the transcript.
- **After the merge, read the merge commit back and treat the default branch's CI on it as the last gate.**
  Squash-merge with branch deletion, then read back `state`/`mergeCommit`, `git fetch` and confirm that
  commit is on `origin/main`, and confirm the workflow run *for the merge commit* finished green: the PR
  head's run does not cover the squashed result, so a merge can land a tree whose default-branch pipeline
  has never run. Then fast-forward the local checkout onto the new base and confirm the remote branch is
  gone, so the next session reads a tree and a repo state that match. Do that fast-forward **quietly**:
  `git merge --ff-only` over a rename-heavy increment prints one rename line per path, and its stat block can
  run to hundreds of kilobytes — enough that the tool result truncates and pushes the closeout's own evidence
  out of the window. Read the result back with `git log --oneline -1` / `git rev-parse HEAD` instead of the
  merge's chatter (`--quiet`/`-q` when it is a shell step).

## When the reviewer is unavailable

- Never let an unavailable reviewer become a silent green. Route the stage to a heterogeneous lane — a
  different model family from the one that authored the change — and record which lane produced the
  verdict, so a later reader can judge whether the review was actually independent.
- Probe a fallback lane with one trivial call before dispatching the real review; a lane that answers a
  one-line prompt is usable, a lane that errors is not.
- **Dispatch the lane against a checkout whose directory name is the repository's own name.** A review
  harness that derives the repository identity from the checkout path (`slug = repo.name`) targets
  `owner/wt` when the tree is a task-local worktree (`tasks/<date>/<task>/wt`), and the round dies before
  it reads the diff — no verdict, no findings, one wasted dispatch. The same shape bites any tool that
  infers a repo, a project or a service from its cwd's basename, so name the worktree directory after the
  repo it holds and confirm the slug the harness resolves before spending a round; renaming a live
  worktree is `git worktree move <old> <new>`.
- **A lane that verifies head identity fails closed on a push that has not propagated — that refusal is not a
  review.** A harness which refuses to review when its worktree HEAD differs from the PR's head sha exits non-zero
  within seconds having read nothing; a push issued moments earlier is still in flight at the remote, so the check
  races. Establish the three-way identity *before* dispatching (`git rev-parse HEAD`, `git ls-remote origin <branch>`,
  `gh pr view <n> --json headRefOid`) and re-dispatch once they agree. Read the refusal's own message and exit code
  rather than the run's absence of findings: a fail-closed lane is a positive property, and the correct response is
  to satisfy its precondition, never to override the check. The same harness may also refuse to reuse an output
  directory a failed attempt left behind, so clear that directory — and only when it holds no report, since a
  directory with a report in it is somebody's verdict, not litter — then dispatch the retry under a fresh run name
  so the failed attempt's records stay readable.
- **When an acceptance battery is running on the same host, tell every review lane not to run the
  repository test suites** ("focused in-memory probes only"): a lane that runs the suite it is reviewing
  competes for the cores the under-load runs need and distorts the timings the stability series measures,
  on a host sized for one heavy job. Put it in the packet rather than holding it as local knowledge — the
  lane cannot see the other unit. The same contention binds the coordinator's own probes: a teeth-check
  injects a violation by rewriting a file in the worktree the battery reads, so serialize it against that
  battery — wait for the run to finish, mutate, require the case to go red, restore from the pre-mutation
  copy, and confirm the file hashes are back to the originals. A mutation applied mid-battery changes the
  input of the run whose verdict you are about to quote, and a green suite turning red partway with no
  change you intended is that collision, not a defect.
- When the lane is a separate system with its own credentials or quota (a hosted review bot, a CLI with
  its own auth), that state is the operator's to fix: report the exact failing line, hand the fix to the
  operator, and close the stage on the fallback lane instead of stalling the whole delivery.
- **Hand the lane a do-not-report list, and put the already-graded findings in it.** State the intent in
  the contract's words, the binding standards, and every finding an earlier stage settled — accepted,
  rejected, or deliberately skipped, each with its reason. Without that list the reviewer re-opens
  decisions the operator already paid for and returns rewrite advice anchored to its own preferred
  design.
- **A CLI lane that ships file-editing tools is a writer until proven otherwise.** Dispatch it
  report-only, then check the reviewed tree (`git status --porcelain`) before the verdict counts: a lane
  that edited the tree reviewed something other than the head you will merge. Report-only is a prompt
  instruction, not a capability — only a lane without write tools is read-only by construction.
- **Ship the artifact the PR claims about, and refresh it before the merge gate.** A packet carrying only
  the diff leaves the increment's own description unchecked: the lane answers that the PR body was not
  supplied, so its claims could not be checked, and they later ship ungraded. Put the PR body (or the
  goal/contract document it refers to) in the packet, and treat the body as part of the tree — when a later
  round changes what it describes, rewrite it before the gate, because a squash merge writes that body into
  the default branch's history, where a paragraph asserting an earlier draft's wording becomes a permanent
  claim the code no longer supports.
- Ask for the diff of the branch against its base, never a single commit. When the increment has both a
  spec and a standards axis, ask for one verdict per axis over the same frozen input; a finding that does
  not name the input which breaks is a concern, not a finding.
- **Split a branch too large for one review call, and put the branch's manifest in every packet.** A whole
  branch diff (150 KB and up) does not fit one lane's call, and a lane given one slice reports the *other*
  files as missing deliverables — "the diff lacks the test suite", "the core implementation is not here" —
  findings that are artifacts of the harness and cost a whole round. Chunk each member to what the lane
  reliably takes (about 60 KB per packet on a CLI lane; a larger prompt can stall with zero output), and
  prefix every packet with the branch's file manifest, its contract and the increment's acceptance record,
  so the lane knows what the whole contains and grades only its part. **Attach the diff of every file the
  lane must grade — pointing it at the worktree is not a substitute.** A lane answers from its packet: a
  split that says "the tests and the prose are in the tree, read them there" comes back with exactly those
  surfaces listed as ungraded (`not attached — uncertain`), so the round has silently lost them while its
  verdict reads complete — and which lanes comply varies, so one lane covering the tree files while another
  does not is the ordinary outcome. Either give each chunk its own lane over the files that chunk owns and aggregate the verdicts, grade the uncovered packet yourself as coordinator (your read is independent of the authoring lane, and a packet no lane received still gets graded rather than shipping inside a verdict that reads complete), or declare the uncovered surface in the round's report and re-cover it on the next head. Grade the verdicts per packet and
  report which packets produced blocking findings. Size what the builder actually wrote, not what you asked
  for — a packet is its prelude (rule + manifest + contract + every context file, quoted into **each**
  packet) plus its chunk, so a builder splitting on a diff-size limit emits packets well over it: read the
  byte counts it printed and lower the limit until the total is what the lane takes. Keep the groups
  disjoint — a group whose path is a parent directory re-ships another group's files, so the same diff
  reaches two lanes and that group balloons into a dozen packets — and name the mechanical churn you
  deliberately left out of every packet, or the lane reports it as a missing deliverable.
- **A branch that carries a vendored tree is reviewed by difference, never by packets.** When thousands of
  the changed files are a byte-copy of an upstream revision (a vendored source tree, a pinned snapshot),
  chunking does not scale — the arithmetic lands at hundreds of packets and the grader cannot tell a real
  finding from a slice artifact. Scope the review to the **project-owned delta** and let a mechanical parity
  check own the copy: build the diff from the repo's own carry manifest, hand the lane that diff plus the
  manifest and the parity report, and state in the prompt what was excluded and why (an unexplained
  exclusion reads as "the reviewer never saw the change"). Require the round to grade the parity claim
  itself — that the checker proves byte identity to the pinned revision, that every deviation is declared,
  that no owned file edits a carried one, that **every record kind the manifest can carry** (ordinary
  carried files, normalised/skip entries, owned deviations, generated inputs) is covered by those rules,
  and that a run unable to perform a check returns a non-PASS result instead of skipping it silently —
  because "identical to upstream" is exactly the claim an LLM reading a sample cannot establish. Size the input before dispatching and refuse the ones no lane can read
  (`git diff --numstat | awk '{a+=$1} END {print a}'`, plus the byte count): a lane handed tens of megabytes
  dies, truncates, or grades the first screen and calls that the branch, and naming the number you refused
  is part of the report.
- **Accept the scoped preparation by arithmetic, not by the lane's summary.** Read the artifacts it left
  (diff bytes, retained path count, the exclusion list, the recorded manifest hash) and check both
  directions against the manifest: every carried path excluded, **zero** project-owned paths in the
  exclusion list, and the owned paths **present** among the retained ones. Then prove fail-closed by calling
  the guard directly with a corrupt, an empty and a missing manifest — a whole-run probe is refused by the
  pipeline's own earlier preflight and answers about the wrong guard. Put the numbers in the report
  (`66.6 MB / 5,594 paths → 0.96 MB / 40 paths reviewed, 5,554 excluded, 15 owned retained`) rather than
  the phrase "scope narrowed": the arithmetic is what shows the narrowing did not drop the risk surface.

## When the CI provider cannot schedule any job at all

Different from a red or flaky check: the account behind the repo can refuse to start *any* job — payments
failed, spending limit reached, Actions disabled for the org. Every run then dies in seconds having
executed nothing.

- **Establish it from the run's own record.** Finished in a couple of seconds, `steps: 0`, no runner id,
  and an account-level annotation on the run (a payments / spending-limit notice). That is what separates
  "the provider will not run anything" from "our workflow is broken"; another repo on the same account
  running green is the control that confirms it is account-scoped, not repo-scoped.
- **Never report `gh pr checks` output from that window as green.** No run means *did not run*: a merge
  record claiming a CI run in the window is false. Write instead "CI skipped — provider could not
  schedule a job", with the annotation, the local gate result on the exact head, and the lane that
  actually reviewed it.
- **Only the operator waives the clause, and the waiver is scoped and recorded where the merge travels.**
  Ask before merging anything; state what replaces the clause (the local gate green on the exact head +
  a fresh heterogeneous machine review on that same head + zero unresolved threads); put the disclosure,
  the annotation and the replacement evidence in the PR body itself.
- **A waiver has to have a way back.** The usual fix is repo visibility or the account being paid; the
  workflow also runs on push to `main`, so the first subsequent push re-verifies the whole tree. State
  that the platform legs have never executed on a hosted runner while the window was open, and treat that
  first post-window run as real confirmation — a red there is a finding to fix, not a formality.
- **Encode it as policy the driver re-reads, not as a habit.** In a goal series, the waiver belongs in the
  driver's resolved policy (re-resolved each run, printed in the state file and in the goal's
  notification) so it expires by itself when the provider schedules jobs again; a hand-bypass is
  indistinguishable from a waived gate two goals later.

## The review–fix loop (a fix is not a verdict)

Findings fixed by a second author (usually a delegated agent) leave unreviewed code behind. Treat the fix
round as a new change, not as the close of the review.

- **A clean round from the family that wrote the code is not the last instrument — price one heterogeneous
read of the frozen candidate before the merge.** Same-family rounds converge on the author's own reading:
six consecutive clean rounds on one increment's frozen head, and a lane from a different model family on the
same bytes returned six findings, three of them blocking, each one reproducible. Schedule that read as a
normal step of the loop rather than as the fallback for an unavailable reviewer, cap it at one frozen head,
and let its findings gate the merge like any other round's; the tell that you skipped it is a closeout whose
title marker was produced by the same family that authored every fix in the branch. Expect the classes it
finds to be the ones a same-family reading is structurally blind to: a path the caller can supply that
cannot be read (a dangling symlink under a name the run also plants), an error naming only the id read as
the refusal that was asserted, a fingerprint that silently degrades to "unavailable", an interpreter limit
standing in for a syntax decision, a comparison that gives up on the first mismatch. Budget the round it
triggers: its findings are a fix dispatch, not a re-read.

- **A round is closed by the head it moved, not by the run's exit code.** Before grading the next round,
  confirm the fix landed where the review reads it: `git rev-parse HEAD` against the round's base, the
  push state of the branch, and `git status --porcelain` inside the run's own worktree. A run that reports
  `done` with exit `0` while its diff sits uncommitted in a worktree leaves the head unchanged, so the next
  review grades the old tree, re-reports the same finding, and the loop reads as unresponsive when it was
  merely not recorded. Read the stranded diff, re-run the repo's gate over it yourself, then commit and
  push it and resume from the round that was genuinely open: re-dispatching the stage re-pays for work that
  is  already on disk, and abandoning the worktree loses it.
- **An interrupted closeout is resumed from its artifacts — head, open findings, dead process, in that
  order.** A stage session can end mid-loop (a restart, a killed turn) and leave a PR that reads green and
  unmerged: the status file still carries its unfilled placeholder sentence, the last round's findings were
  returned and never answered, and nothing is running. Establish three coordinates before writing anything:
  the PR's own state (`gh pr view <n> --json state,mergedAt,mergeCommit`), the newest artifacts of the task
  directory (`find . -type f -newermt '<YYYY-MM-DD HH:MM>' -printf '%TT %p\n' | sort | tail`) to see which
  round it stopped after, and the launcher's `status` / ledger tail plus `pgrep` for whether anything is
  still alive — a run is not alive because its newest artifact is an hour old. Then continue at the round
  that was genuinely open, on the head the last report names (its `REVIEW HEAD:` line), with the new fix
  prompt carrying the returned findings verbatim: re-dispatching the whole loop re-pays for every round
  already closed, and a round grading a head the fix never reached reproduces the finding it was meant to
  answer. Attach a completion watcher **at dispatch, not only on resume** — one background job that waits on the run's
  own `exit.code` or on the external condition the lane exists to produce (`gh pr view <n> --json state`
  until `MERGED`), with a completion notification, never the run itself — so the closeout is woken by the
  run's completion instead of stalling for hours until the operator asks. Never busy-wait in-turn on a lane:
  a wait long enough for one exceeds what a turn holds, and a turn that ends without a message is silence
  the operator experiences as a hang. A launcher reporting `state: running` (or a live tmux session) is not
  proof the work is alive — a lane can vanish without writing any exit code and leave the state file at
  `running`: a lane with no report artifact, a stuck `running` and no process is dead, so finish the
  remaining steps inline or relaunch with the watcher attached, and report the miss with that evidence
  beside the restart.
- **Ask for a delta review that answers per finding.** One round: for each accepted finding `closed /
  partial / not closed` with `file:line`, plus an explicit answer to "what did the fix introduce?" A fix
  that misread a wait-status field turned a previously proven green path into a false red: the regression
  direction costs as much as the original defect, so a fix round that is never reviewed is how a review
  gate becomes decoration.
- **Scope a post-fix round to the fix, and quote the open finding into the packet verbatim.** The range is
  `previous_head..new_head` (the fix commit) and the prompt says so explicitly — "the rest of the branch was
  reviewed in N earlier rounds, every one closed; do not re-review it" — or the lane re-derives the whole
  branch and returns the already-graded class. Carry in the packet: the finding's own words copied out of
  the still-open thread, the pre-fix/post-fix reproduction with its output, the mutation row that reverts
  the fix and the failure signature it produces (so the lane grades the pin, not your summary of it), and
  the judgement list — does the delta close the *requirement*, is behaviour unchanged for every input that
  already fit, do the writer's other consumers still hold, is the new test a real pin, what did the fix
  introduced. State the extraction rule too ("report only actionable defects attributable to this delta"):
  a packet scoped to one commit still invites generic style notes over the rest of the tree.
- **Sibling instance of the same mechanism, in a file the diff touches, is IN scope — fix the class in one
  round, never defer it as "outside this increment".** A lane that reports the same substitution/loss/race in a
  second place has reported a finding, not a note: the next review round reads the same mechanism out of the
  delta and blocks on it, so a deferred instance costs a round and buys nothing. Scope is the diff, not the
  goal's declaration of what it changed — grep the diff for the mechanism (`git diff --name-only <base>...HEAD`
  then the symbol) and fix every instance in one dispatch, naming in the prompt which files are the class and
  which one carries the shared helper behind several routes. A class-wide disclosure fix is still a disclosure
  fix: require the round to prove the bytes it writes are unchanged (same documents, same item lines, before/after
  probe) and to say so when the probe moves something, because widening the blast radius is how an accounting
  change turns into a behaviour change nobody reviewed.
- **A fix that satisfies the finding by a different mechanism must be framed as such, or the round bounces
  on route.** A reviewer's suggested remediation is not the requirement. Quote the property that must hold
  ("the retention setting cannot change the run's outcome") and say plainly which route the fix took
  instead, then ask whether the property now holds. Handed only its own suggestion, a lane grades the code
  against its own wording and returns "not fixed as described" for a fix that works.
- **Map every accepted finding to the packet whose slice contains its `file:line`; a finding no slice covers
  is unclosed.** A delta lane is asked to grade its own slice, so an honest one answers `outside packet` /
  unknown for anything its slice does not contain — that is the correct answer and it is *not* closure, and
  aggregating the slices against the finding list is the coordinator's job, not the lane's. Two traps in
  this shape: a finding whose location fell in no reviewed packet survives every clean lane, and a lane's
  sentence that an item *is* closed ("the vocabulary test asserts all seven values") is a claim to verify by
  reading that assertion — a fix that rewrites an assertion is graded on the input that now makes it fail
  (see `mechanical-gate-design` §6), because a round can delete a pin while the test count stays the same.
- **Equivalence evidence does not transfer between revisions of the same fold.** A fix that adopts the
  reviewer's suggested form of a loop rewrites code whose behaviour was already proven identical in an
  earlier round — and that proof describes the earlier text. Say so in the dispatch ("the previous round
  verified the previous form") and require the current one to be re-derived against the behaviour it
  replaces: the byte-for-byte differential against the prior implementation, or the enumerated input shapes
  where the two forms could differ. "Same semantics, less code" is the claim the round is there to test,
  not a premise it may inherit.
- **A refactor re-opens nothing until the battery says so.** A change that touches a class the acceptance
  battery covers (retention, ordering, a shared writer) earns that battery again even when every test is
  green: the suites pin the cases someone thought of, and the mutation rows and the repeated-under-load
  runs are what show the rewrite did not move an unenumerated edge.
- **Budget the loop, then change the instrument.** Two fix rounds, then the next attempt must stop patching
  case by case and state the principle the change derives from (e.g. *ambiguous evidence is never OK;
  ambiguous liveness is never a failure*) — or the round is over. Whatever survives that is reported as an
  explicit residual list, one line per item in the closeout, rather than another dispatch. An unbounded
  review/fix cycle consumes exactly the work it was meant to protect, and a whack-a-mole third round is
  where the return ends. An operator instruction in that same shape ("resolve it from the root, not
  patch after patch again") is this trigger arriving early: run the diagnosis rung now, and answer with
  the class and the rung instead of one more targeted fix.
- **Count the cap against the round, not against the goal's history — and say which budget a re-review
  spends.** A `review→fix` cap of two rounds counts dispatches of *this* round; an attempt spent on a
  superseded branch (a withdrawn PR, an increment re-scoped after the round ran) is not a third round of the
  current one, so retiring the re-review for cap arithmetic leaves the merge without the one thing it needs —
  a **clean** round on the head you merge, which the round that *found* findings can never be. Write the
  arithmetic in the ledger row, then spend a named budget: the per-dispatch override with its reason
  recorded, or the same prompt dispatched standalone through the launcher. Either way the post-fix round is
  its own named round with its own prompt file and its own report, and **that report is the marker's
  source** — build the marker from those bytes with the lane's own model and provider ids, post it, read it
  back.
- **Bound the next round with an actionability rule the lane answers per finding.** Once the budget is spent,
  "find the remaining defects" buys another round of the same class; a rule does not. State it in the packet
  verbatim and require the lane to dispose of every item on that axis: a finding is actionable only when it
  shows (i) an escape across the boundary the code is supposed to hold — a signal, a syscall or a write that
  leaves the guarded path — (ii) a **production-only** mutation (production changed, tests untouched) that
  keeps the suite green, or (iii) a literal contradiction between a comment, docstring or claim and the code
  beside it. Everything else is returned as *non-actionable* **with the reason that decides it** (a consumer
  requires the behaviour; the sequence it worries about is unreachable; the redundancy it wants is not a
  pin), so the round's answer is a table you grade rather than a rewrite you re-review. The rule bounds the
  *next* round, not the requirement: findings that do qualify still gate the merge, and a lane that ignores
  the axis is re-prompted with it rather than accepted.
- **Grade that table by executing its cheapest claim, in a copy of the tree.** "The docstring says X, the code
  does Y" is settled by reading the two lines. "This mutation survives the suite" is settled by running it:
  copy the tree *outside* the worktree (a fix lane or a gate may be reading it), apply the one-line mutation,
  run the focused case file, and read where each compared value comes from — a suite still green confirms the
  finding, and the fix is the probe's independence, not another assertion. Sort the table by cost, execute the
  cheap claims before dispatching anything, and send only the reproduced ones into the round; a claim you
  reproduce as false goes back as a refusal with the command that decided it.
- **Diagnose a recurring class as a time-of-check/time-of-act window before buying another round.** When
  consecutive rounds return one surface and every fix so far *adds an observation* — one more probe before the
  act, one more check before the signal, one more guard before the write — the class is a window: observation
  is not reservation, so each added observation is one more instant with the same gap after it, which is why
  the class survives every round that leaves the act where it is. The rung that closes it moves the proof into
  the act: a primitive that carries identity and is re-established per attempt (a handle/descriptor,
  `O_EXCL`/atomic replace for a file, compare-and-swap on a generation for a row, an idempotency key for a
  request) — or a refusal. Say which of the two the round implements, and treat a fix that merely observes
  more as the *same* rung as the previous one rather than a new attempt. When the rung is the refusal,
  **delete the route for the refused class instead of guarding it**: a check placed in front of the old path
  keeps every window that path had, plus the waits, the success log lines and the record's vocabulary that
  still describe an act the code no longer performs — so the round removes the plumbing that fed the act (the
  enumeration that selected the targets, the escalation it drove), shrinks the prose to the smaller true
  claim, and re-expresses the tests that pinned the removed mechanism as refusal-and-report pins, never
  deleting them.
- **A class that survives because one published record has two writers is closed by collapsing them, not by
  enriching the record.** The tell is in the diffs: every round adds fidelity to the record — one more field,
  one more bucket, one more derived view — while the same fact is written twice, once where the act happens
  and once by a summary computed from a projection that cannot represent the act's real sequence. Each round
  then proves the added field agrees with *one* of the two writers, and the disagreement the review keeps
  finding sits between them, so the class returns with a new field attached. The rung is one decision point
  everything derives from: emit where the decision is made, derive every published view from what was
  emitted, and delete the projection and the buckets that cannot carry the sequence instead of widening them
  — a widened bucket still cannot say *which* attempt ended the target. A fix that adds a field to the
  projection is the *same* rung as the previous round rather than a new attempt, and the tests that pinned
  the removed projection are re-expressed against the emitted sequence, never deleted.
- **A class that returns as "one more path the table does not list" is closed by deleting the claim of
  completeness, not by adding another row.** When a docstring or comment enumerates what the code handles — a
  table of endings, a list of cases, "every reachable state", "a second round cannot end on the gate" — the
  reviewer reads it as a **closed set** and each round returns one more shape nobody listed, indefinitely: the
  list was derived from one walk of the code, and no walk is exhaustive. The rung is to state the table as the
  walk's *output* and the walk as its derivation — "a shape the table does not list is a gap to be added as a
  row, not something the table denies" — and to grep every exclusivity word out of the increment (`every`,
  `exhaustive`, `cannot end on`, `only`, `no other path`) in both the code and the test file before dispatching,
  because the residue in the *other* file is what re-opens the class. Adding the missing row is the **same** rung
  as the previous round: pin the row that was genuinely missing (a refusal path the code really can take is a
  real gap) but rebuild the sentence around it, and expect the next round to grade the wording as well as the
  code.
- **A guarantee the surface cannot give is the owner's decision, not a fifth round.** When consecutive
  rounds return one class and the honest answers differ by *policy* rather than by edit — refuse and record
  the limit, keep a weaker proof, stop escalating and report residuals — the rung below a spec is a
  decision: cost two or three policies with what each gives up, recommend one, and let the owner ratify it.
  Implement the ratified policy as the requirement, and put it in the next packet **verbatim as the
  acceptance criterion** together with the limits it accepts, as an explicit not-findings list — plus what
  is still in scope *inside* the limit (can a signal still escape without proof, does a record over-claim,
  is the limit lost in a merge or at settlement). A packet that omits the accepted limits re-opens them as
  findings on the new head and the loop never converges; one that states them too broadly ("this class is
  not a finding") suppresses the defects the round exists to find. Phrase each exclusion as *without new
  evidence, not actionable* — never as *do not report*.
- **A test-completeness finding still has to close — bound the loop, do not re-label the finding.** A
  finding whose only claim is "this assertion does not pin the rule tightly enough" — tighter mutation
  coverage, one more shape the scanner should catch, an existing test made stricter — with no product or
  behaviour defect behind it is not a strictness upgrade to be argued away as a note: fix it, and the merge
  still waits for a round that reports no findings, because the gate reads a clean marker and relabelling
  findings to clear it is the rubber stamp the gate exists to prevent. The bound belongs on the
  *instrument*, not on the requirement: once the same file is the only subject of three consecutive
  rounds, stop patching one assertion per round and switch to a single systematic pass — enumerate every
  rule that file claims to protect, pin each with an exact value, and mutation-prove all of them before
  re-reviewing (see `mechanical-gate-design` §6). When the recurring subject is a **behavioural class**
  rather than an unpinned assertion — every place the file creates or removes a file in a caller's home,
  every arm that reads a name match as a refusal — sweep the **sites** of the class instead: enumerate
  them (`file:line`, each with the rule it must now obey), close each with a case that fails against the
  pre-fix code, and ship that enumerated list in the round's report *and* in the **next** round's packet
  as its checklist, so the round verifies the list rather than rediscovering the class. A sweep that only
  fixes the instances it happened to find leaves the remainder for round N+2 — the loop the sweep exists
  to end. Dispatch that sweep as a deliverable, not a sentence: one
  table line per case — the rule the case claims to protect, the mutation that must make it fail, and the
  executed result — scoped to the cases the increment added or touched (no suite restructure, no renaming a
  case other cases or the record cite by name), ending in a class verdict: closed, or the claims that remain
  unpinned and why. Run that same table over the cases **your own** fix passes added before the lane does,
  because no round has read those yet, and carry each measured mutation into the round's packet. A
  systematic pass of that shape ends the loop in one round where per-round patching had not; state in the
  round's report which findings were closed and which were deliberately skipped, with the reason, so nothing
  disappears silently. Put the escalation trigger in the packet as a question the round has to answer:
  whether its findings are the *same class* as the previous rounds' and, if so, which class — the answer
  decides the next rung (another patch, this sweep, or a spec), and it is cheaper than reading that class
  out of the round's own prose afterwards. When the demanded
  coverage has no home in the tree yet — a repo with no test surface at all — that is an architecture
  decision the dispatch must make: name where the surface goes and which existing entry point runs it,
  anchored to the repo's own growth policy for how its check set grows. Left open, the worker invents a
  runner and CI grows a second entry point the repo's gate never sees: the finding is satisfied and the
  harness is worse.
- **The budget can be spent with no clean round ever — then enumerate obligations and authorize exactly
  one audit, instead of another round of any kind.** "Every finding is closed" is not a verdict: the merge
  still needs a clean round on that head, and an all-closed list next to *no* clean round is the shape that
  merges a large unaudited increment. Diagnose before acting — map each finding to the **invariant it
  defends** rather than the file or rule title it cites (findings citing different files under different
  titles that defend one invariant are a single recurring surface no per-round patch closes), and measure
  the increment's added lines split product vs tests/harness, because a majority of growth added by earlier
  fix rounds means later rounds are reviewing the instrument those rounds built. The rung is one systematic
  close-out — a frozen obligation matrix, every obligation carrying positive evidence and one **executed**
  mutation — followed by exactly one fresh read-only acceptance audit scoped to that list, whose findings
  stop the run for decomposition rather than starting another cycle (only the owner can instead buy the
  repair plus one further audit on the repaired head). Diagnosis, the rungs to refuse, the
  evidence standard and the merge rule:
  [`references/review-budget-exhaustion.md`](references/review-budget-exhaustion.md).
- **When the sweep also fails to close the class, the next rung is a spec — not a fourth round.**
  Trigger: a fresh review of the swept tree still returns blocking findings of the same class. The class is
  structural (ownership, lifecycle, concurrency, cross-process state, generation/versioning) rather than a
  rule that never got pinned — a locally correct fix keeps revealing the next edge of the same state machine.
  Take the **cheaper rung first**: a root-cause consult that names the seam the class leaks through — one
  ownership object for a surface you do not own, one evaluation over the raw input, one result type — is an
  implementation round, not a design pass, so it costs a fraction of this one. Reach for the spec below only
  when the invariants cannot be encoded in the control flow. Seam shapes, their closure rules and their pins:
  `references/design-first-hardening.md` ("The cheaper rung first").
  - The instrument is a **normative specification**, written by a lane that is neither the implementer nor
    the grader that will judge the result: author / designer / grader are three distinct model families, and
    the round's report names which lane produced the spec. A designer that has graded earlier rounds writes
    its findings list back as prose. Ask it to attack rather than confirm: ship your own diagnosis as a stated
    hypothesis beside the code at the reviewed head and the round history, then verify each of its claims
    against that code before dispatching — the useful answer is a diagnosis you did not have (its items become
    the round's acceptance criteria, and a latent hole it finds in code you had already settled is a defect to
    fix in the same round), while a lane that only restates your hypothesis has cost a round-trip.
  - The spec is normative, not a findings list: object model, mutex protocol with a lock hierarchy, lifecycle
    state machine with what *proves* each terminal transition, generation binding per mutating operation,
    identity/ownership rules, and an invariant table where each row names the failure it prevents, the
    deterministic interleaving test that must exist, and the mutation that must make that test fail. Every
    finding of the last round must map to at least one invariant; an invariant with no test and no mutation
    does not exist.
  - Then exactly **one** implementation round conforms the code to the spec, then a fresh grader on the new
    head. If that grader still returns the class, stop and answer it with the spec's residual-limits section
    plus the evidence — another round is the loop you were escaping.
  - Recipe (packet composition, instruction, dispatch, grading, stop rules):
    [`references/design-first-hardening.md`](references/design-first-hardening.md).
  - A design pass plus an implementation round is a **scope change**: raise it to the operator as a decision
    with its costs, keep the PR open while it runs, and never let an earlier merge authorization cover it.
- **A verdict that states its own verification limit tells you what the next round re-opens.** "Static
  inspection only; no edits, builds or gate runs were performed", "mutation not executed", "by inspection" —
  the findings are hypotheses, and a fix round that answers them by re-reading the code hands the next round
  the same class. Make the executed reproduction a deliverable of the fix dispatch and quote the command
  with its output in the round's report. Where the claim is about a platform or configuration this host
  cannot produce, reproduce it by forcing the probe's other answer in a case and running it here: a green
  local run refutes nothing about the platform that has no tool, and asserting that it would pass is the
  statement the reviewer already made.
- **A surviving mutation names its own missing fixture: the discriminating input.** Before adding a
  case, name an input on which the two readings the mutation swaps between actually disagree — a
  `split` vs `rsplit` mutation is killed only by a field that itself contains the delimiter, an index
  mutation only by an input whose neighbouring fields hold different values — and add exactly that input.
  A fixture set with no such element cannot kill the mutation however many assertions are stacked on it,
  so read the mutation's two readings first and write the discriminating fixture rather than tightening
  an existing assertion: what the round owes is coverage of a *shape*, not another comparison of a value
  both readings already agree on.
- **Require a pin test per accepted finding, with its pre-fix failure quoted.** The round adds the case and
  runs it against the pristine file first (`Ran N tests … FAILED (failures=8, errors=5)`); a suite that
  still passes with the fix reverted is decoration, and "re-read the code, looks right" is not evidence.
  The suite may only grow — a count that changed is re-derived, never adjusted to match, and the acceptance is
  by **case name**, not by count (recipe: `references/delegated-lane-delivery.md` §2).
- **A rejection needs the authority that decides it, not agreement.** A finding about documented semantics
  is settled by the spec, or by the sibling implementation that already decides the same input (two
  launcher routes, two renderers, two validators): cite it, and when the code is right and the record is
  wrong, the fix is the record. "We disagree" reopens the finding next round.
- **A fix that adds confirmation or ordering is a new race until proven otherwise.** When a fix makes an
  operation wait for positive confirmation before reporting success, enumerate the paths where the
  confirmed fact never arrives because the thing legitimately died fast — a child that errors and exits
  immediately still counts as *started*: the confirmation proves the action happened, not that its subject
  is still alive. Then require the round to re-run the whole suite at least ten times, at least half of them
  under CPU load. "Intermittent" is not a disposition — demand the mechanism or the reproduction under load,
  because a single green run cannot see a race that appears one run in four. Reproduce a flake by looping
  **the single failing case** (30 runs of one test is minutes; the whole suite is not a reproduction), have
  the round dump the state at the failure moment, and read that dump before touching the code. The class it
  usually exposes: a state machine commits its terminal decision before its subject is really gone, so a
  check that samples the gap false-reds — *the stop was recorded* is not *the process tree has left*, and an
  unknown survivor set is not an empty one. A wait that actually closes it is bounded, holds no lock while
  waiting, and aborts as soon as the subject's generation changes; a wait without all three is the same race
  moved, and a drop-in sleep hides it.
- **Require the implementer to declare what it did not fix.** Put the clause in the fix dispatch — "if you
  judge a finding should not or cannot be fixed, list it with the reason instead of skipping it" — because
  a fix round that quietly drops a finding returns a green tree with an invisible hole.
- **Keep acceptance fixtures with the artifact, named for the finding they close, and re-run the whole
  set.** Running only the new fixtures lets a fix that closes one shape re-open another; the full set is
  the regression control for the next round.
- **Acceptance runs the artifact, not the author's summary.** Re-run the suite and at least one real
  end-to-end instance yourself; a delegated report — including its own quoted output — is a claim. When the
  round's deliverable is a new pin or mutation test, run each new mutation yourself and check it fails
  **only** its own case (a mutation that drops four cases pins nothing in particular); when the deliverable
  *is* the check itself, the mutation to run is on the **producer** — delete the record line the check reads
  — since a guard keyed on a shared notes field stays green without it, and require the legitimate-alternative
  path (the capability forced absent) to stay green in the same probe (design rules: `mechanical-gate-design`
  §6). Then grep the tree for the
  residue the round added (a debug env var, a forced-failure hook) before trusting a green, and read
  `git status --porcelain` with the diff's file list: a round that touched a file outside its declared
  surface reviewed something other than the head you will merge.
- **Re-establish a regression pin yourself by reverting the implementation only.** A lane's mutation row is
  a claim like any other, and a pin can be vacuous (an upper bound above everything the input can produce,
  an assertion the fix's own value satisfies). Keep the round's new cases and put back the pre-fix
  implementation: `git stash push -q -- <impl paths>` — named paths only, so the tests stay — then run
  exactly the new cases, require them to **FAIL** with the pre-fix signature, `git stash pop`, and confirm
  `git diff --stat` returns to the round's numbers. A case that passes against the pre-fix implementation
  pins nothing, and this check needs no mutation driver, so it works on any round and on a repo whose driver
  lives only in the lane's evidence directory. **When the round's cases reference symbols the base revision does
  not define, the revert dies at collection** — no summary line, so a filtered read returns nothing and is
  mistaken for a clean pin check: read the traceback, classify it as *the symbol exists, the assertion never
  executed*, and finish the check with your own targeted mutation of the rule the case pins. The round's
  mutation driver belongs in the task's evidence directory with its recipe (the exact text replaced, the
  command, the case that must go red) in the report — a driver parked in scratch space is gone before the next
  reader can re-run it, and a matrix nobody can re-execute is a table, not evidence.
- **Name the mechanism when an assertion cannot fail, and pin the rule by executing the violation.**
  "Tighten this assertion" hides five different defects, each with its own fix:
  - **Element-shape drift.** A membership test whose element's arity changed can never match and is
    green forever — `assertNotIn((kind, pid), sends)` against a recorder that now yields
    `(kind, pid, signum)` triples. Assert the rule over the shape the recorder actually yields
    (`{pid for _handle, pid, _signum in sends} == {spawned}`) and grep every other consumer of that
    record for the old arity, because a reader that unpacks pairs silently reads only the first two
    fields of each triple.
  - **The test requires the capability it claims is absent.** A case named "works where X is missing"
    that patches `X` to `None` still resolves `getattr(module, "X")`, so on the platform without X it
    errors before asserting and never exercises the fallback — model absence by deleting the attribute
    and restoring it (re-deleting when it was never there). Order the refusal the same way in the code
    under test: consult the capability *before* resolving any platform-specific constant, since a
    constant some platform lacks (`signal.SIGKILL`) raises exactly where the refusal should publish a
    limit — resolve such names through `getattr` and keep the names in one table.
  - **The evidence has a second cause.** A fixture's liveness is not "no signal was delivered": a
    fixture that can exit on its own (a sentinel the code under test removes before returning) makes
    both readings true, and a scheduling delay flips the assertion. Assert over the recorded deliveries
    and over the artifact the code writes (the run's own log), not over the state you hoped would differ.
  - **The fixture's oracle is the code under test.** A spy or fixture that recomputes its expected value
    by calling the same helper the production path calls has no independence: mutate the production
    parser and both sides move together, so the suite stays green and the change is invisible. Derive the
    expected value by a separate route inside the test — the raw field index into the recorded line, an
    expression built from the input the test itself constructed — and prove it by mutating production
    alone. A spy handed the already-parsed result instead of the raw input repeats the defect one level
    up the chain, so check every hop between the input and the asserted value.
  - **The path under test is never reached.** A case that pins a refusal, cleanup or error branch while
    every run takes the golden path asserts a property both readings already satisfy: the residue is
    absent because nothing ever wrote it, the refusal is unreachable because nothing selected that branch.
    Force the branch inside a scratch root the case owns — point `tempfile.tempdir` at a directory the
    case made, seed the collision the guard tests for, plant the file whose presence selects it — then
    assert the residue is gone and say which root you asserted in. Where the rule lives at several sites
    (two refusal guards plus a `finally`), mutate one site class at a time and record which removal the
    case catches, so the report states the pin holds the branch it names and not the neighbour that would
    have cleaned up anyway; quote the mutant's own failure text (`Lists differ: ['<scratch>'] != []`)
    rather than the word FAILED, since that signature is what the next reader re-derives the pin with.
    **Drive every site from one case rather than adding a sibling per site:** a case that seeds only site
    A's trigger stays green when site B's line is deleted, so the mirror case buys nothing a single loop
    over the triggers does not — and a docstring claiming "the refusal paths" while the body drives one is
    the tell. Parameterize the trigger (one `subTest` per site), then mutate each site separately and
    require each removal to fail its own sub-case. Write that call with explicit keyword arguments: a
    `**flags` dict unpacked against typed parameters draws a type-checker error a reviewer reads as
    breakage your diff introduced.
  Prove the fix by injecting the violation through the same primitive the code uses (deliver to the
  forbidden target via a real pidfd, not a raw `kill`) and require exactly those cases to fail — and
  ask the lane to prove each reading separately, so an assertion that would fire for the wrong reason is
  visible as such.
- **A fix that moves the obligation to the caller is verified at the call site.** An opt-in flag, or a
  declaration every call site must now make, leaves the inner API's old behaviour intact by design: a probe
  against it stays red and proves nothing either way. Require the *shipped call site* to pass the
  declaration, and require the declaring predicate to be the consumer's own predicate — a cheaper
  byte-level prefilter is narrower than the parser the consumer uses (an escaped form the parser accepts
  never matches the bytes), so the guard withholds exactly the record the reader settles from while every
  test of the inner API passes.
- **Size the round's verification by what the round can change.** A finding that touches behaviour —
  ordering, waiting, retention, a race — earns the full series: the whole suite plus the repeated-under-load
  runs. A finding that touches only comments, assertions or test scaffolding earns the gates and one green
  suite; spending the load series there buys nothing and delays the head. Decide the class before
  dispatching, and name it in the round's report.
- **Two lanes grading the same head produce two verdicts, dispositioned separately.** One table maps every
  accepted finding to its lane, the head it was raised on, and the round that closes it: a fix round for one
  lane rewrites text the other lane's finding points at, so re-locate that subject in the new head (its cited
  line may already have been replaced) rather than dispatching the older note verbatim, and the marker on the
  final head needs both lanes clean — a round that closed lane A's list leaves lane B's open. **A clean verdict
  from one lane does not refute a reproduced finding from the other.** A prose/simplify lane answering
  `FINDINGS: NONE-BLOCKING` (even with a positive sentence that the suspect construct is exact) while the code
  lane names a production-only mutation that survives the suite is not a disagreement to settle by argument:
  execute the claim yourself (the rule above on grading the table's cheapest claim) and let the run decide, then
  put **both** lanes' sentences plus the command that decided it into the *fix* dispatch verbatim — an
  implementer handed one lane's finding and the other lane's clean verdict splits the difference and satisfies
  neither. Report the arbitration as the round's own line: which lane was overruled, by which command.
- **A finding that says a rule states what the code does not do has two arms — ship the wording arm, ask for
  the mechanism arm.** The honest repairs for a rule, state doc or disclosure row whose stated condition the
  code does not implement are (a) make every surface that states the condition state the code's real one and
  say plainly what the code does instead — including that a list which cannot act for the records it names is
  inert there — or (b) change the mechanism so the stated rule becomes true. Arm (a) ships under the default:
  it moves no behaviour and is one clause to reverse, so it can be dispatched while the question is still open
  (disclose it in one line). Arm (b) is a scope call: cost it to the owner as an option round, and land the
  entry in the repo's own decision file — the artifact the next reviewer re-reads — with both arms, the
  reversal, and what would settle it; when the arm only becomes live under a later goal, say so in that entry
  instead of dropping it. Dispatch the fix naming arm (a) and **forbidding** (b): an implementer handed a
  rule-vs-code finding will otherwise choose the mechanism on its own authority. Grep every surface that
  states the condition — rule text, state doc, the row, the evidence record, the plan — and fix them in one
  dispatch: correcting the prose in one file while the rule text keeps the old condition reopens as the same
  finding on the new head. The increment's *own* rule file is inside the licensed half of a timeout; only the
  mechanism change parks. Before offering arm (b), read the code that would carry it out (does the field
  exist and who sets it, which count the row would have to move) — an arm the tree cannot support is not an
  option to put in front of the owner.
- **A declared-exception list is a deliverable derived from the tree, and every entry's reversal condition must
  name an independent expectation.** When an increment declares which sites are excepted from a rule — a debt
  list, a carve-out enumeration, "these readers are re-implemented in Python" — its completeness **is** the
  deliverable: derive it in one pass by grepping the tree for the mechanism, because a list assembled from what
  each round happened to find grows one site per round, and three consecutive rounds each returning "and here is
  a fourth site" is that signature (fix the class, then dispatch once). Each entry then needs a reversal
  condition that is a *check*, not a sentence: an **observed** reading (the producer's own output, the loader's
  own answer) cannot be its own expectation — a check's only power to reject a wrong result is the independent
  expectation standing beside the observed one — so a condition phrased "delete the prediction once the loader
  answers directly" describes a retirement that, executed, silently weakens the check while reading as
  progress. Require the entry to name where the expectation comes from on replacement (an independent read of
  the source, the harness's own documented semantics) **and** the regression case that must survive the swap.
- **A claim row that says the route carried something must be COUNTED, not just reworded.** When the route has
  no shape for that record — a role, a kind, a source the writer skips — the fix is to count it as omitted
  (the row must say what the route did) and to pin it by extending the "every route counts what it could not
  establish" test with a record of the shape the claim missed. A wording-only edit leaves the false count
  shipping, and the case is usually reachable (carried readers really do produce it), which is what makes the
  row affirmatively false rather than merely imprecise.
- **A completeness claim is checked against the writer it claims about.** When an "every category / every
  route" case stops naming categories the writer under it reports, add them and correct the case's own
  completeness wording; a disclosure-only gap is still a finding, because the count-bearing cases are then
  the only pin on the new rows.

## A merge that already shipped without them

Branch from freshly fetched `origin/main`, run both stages against the merged head, apply the accepted
findings, and land them through the same two inspections. Do not revert a shared branch to "do it
properly" — the follow-up is quieter and does not re-litigate a diff other writers may be building on.
Do not let the omission stand either.

## A PR that never entered the loop

A green PR with a clean bot marker can still have had neither inspection: the review bot is the repo's
own gate, not the simplify report or the code review. Check the delivery ledger for that repo before
claiming a PR is merge-ready — no rows means the increment never ran the phases, however green it looks:

```bash
grep -P "^\S+\t<repo-name>\t" "$HOME/.local/state/gdd/ledger.tsv"
```

Both stages run standalone against an open branch, so a retrofit needs no contract rewrite: dispatch
`simplify` (report only) through skill `gdd`'s stage tool against the PR's own worktree, grade and apply
the accepted findings, then `review`, then `fix`. Point the dispatch at the agent binary explicitly (an env
var holding the shim's absolute path) — the bundled launcher resolves the agent through `PATH` and refuses
with `agent binary not found` when a non-interactive shell has no shim on it. Confirm the stage's diff range in a dry run first — it
must be the whole increment (`merge-base origin/main .. HEAD`), not the last commit — and a branch with no
goal record is fine to run anyway (the resolved contract file reads `-`; the range is the contract). Every
new commit moves the head, so re-read `gh pr checks <n>`, re-request the review, and let the retrofit rows
in the ledger be what the next session reads as inspected.

## Keeping the PR you verified mergeable

- A base that moved while the branch sat is a conflict to resolve, not a reason to re-open the work: fetch,
  merge the base into the branch, resolve, and re-run the gates. Never force-push a shared branch.
- **Never hand-edit a file the repo generates.** Where a repo's own tool writes version scalars, indexes or
  mirrors, resolve those conflicted paths to the base side and re-run that tool: a hand-resolved scalar
  drifts from the mirror the merge-time check reads and blocks the merge for a reason that looks unrelated
  to the conflict.
- Any new commit — conflict resolution, findings fix, a late decision applied to the tree — changes the head
  sha, so the earlier CI run, review marker and gate verdict all describe the previous head. Read
  `gh pr checks <n>` on the new head and request the review again: a push does not trigger a re-review.
  **When the head moves while a round is in flight, kill that round instead of waiting for its verdict.** A
  report whose `commit_sha` no longer matches the tree can never become the marker: its findings may still be
  true, but grading them against the new head re-derives the same round, so the round is spent the moment the
  commit lands. Kill the lane by run name, confirm it is gone, land the change, then dispatch one fresh round
  on the new head — and report the round as killed-and-re-spent rather than presenting a stale report as this
  round's verdict.
- **Sequence the review round behind every decision that can still move a file.** The marker binds to an exact
  head, so an owner question answered, a policy ratified or a prose edit applied after the dispatch costs the
  whole round a second time. Put those questions to the owner before the dispatch — while the branch is being
  cut, not while the round runs — and when an answer only arrives mid-round, treat it as the head change above
  instead of letting the report and the answer race. The same arithmetic is why the merge earns exactly one
  round of slack: the round that *found* something can never leave the marker, so the last fix always needs
  one more clean round, and scheduling that round is part of the plan rather than an afterthought.
- **A check table read seconds after a push belongs to the previous head — attribute by sha, never by
  arrival.** `gh pr checks <n>` is PR-level: until the new run registers it still lists the *old* head's
  checks, so a read taken immediately after a push returns the previous head's failure as if it were the new
  head's. Never let that read start work: require the run's own `head_sha` / `headRefOid` (or
  `gh api repos/<o>/<r>/commits/<sha>/check-runs`) to equal the sha you pushed before acting on any result,
  and give every watcher that acts on a red a minimum age or a pending window. The tell is arithmetic — a
  failure reported within a second of the push, whose own duration belongs to a run that started before it —
  and acting on it starts a fix round for a defect that does not exist, while the real run is still queued.
- **Prove the new head advanced without a rewrite, in two commands.** `git ls-remote origin <branch>` must
  equal the local sha, and `git merge-base --is-ancestor <previous-head> HEAD` must succeed. That pair is
  what turns "the head is now X" from an assertion into a fact — and it is also the answer when an approval
  scanner flags an ordinary push as a force push (a short flag in the command line is enough to trigger it):
  report the ancestor check, not your assurance.
- Re-read the remote's real base instead of a stale local `origin/main` right before merging; a sibling PR
  another writer merged since your last fetch is how a version claim or a gate result goes stale.

## Reporting a verdict

One line per fact: which head, which gate numbers, which lane produced the review verdict and its
marker status, which findings were accepted or rejected, what is still unclosed. An absent review is
stated as absent; it is never summarized as "reviewed".

**A "how far are we from merging" question is answered from live coordinates plus the steps left, never from
the plan.** Read each PR's own state (`gh pr view <n> --json state,mergedAt,mergeCommit`), say which sha the
default branch's run actually tested, then list the steps that remain with who performs each and where the
next decision point is (the point at which the remaining work hands back to the operator). An estimate with
no verified coordinates is a guess dressed as progress; an unfinished stage named as unfinished is the answer.

**Green checks and a mergeable state are not a merge.** "Did it merge?" is answered from the PR's own
state — `OPEN`/`MERGED` — never from a clean check table plus `MERGEABLE`, which is one step short of it.
Name the clause that still blocks (an unclosed review class, unresolved threads, an unrun gate) and who is
deciding it, so an unfinished stage cannot read as a finished one.

**Lead with the class, not the finding list.** A round that returns ten or more blocking findings on one
file is not ten items the operator reads: name the single class they share in one sentence ("nobody owns
the run's lifecycle under concurrency"), then the mechanism — what breaks, under which interleaving — then
the two or three directions that could close it with their cost, and only then the per-finding detail. The
operator decides on classes and directions; a findings table with no class above it reads as noise, and its
replay ("I did not understand what is blocking") costs a whole round before any decision exists.

When the head under review was produced by a delegated agent lane, the dispatch contract and the
acceptance checks for that lane are in `references/delegated-lane-delivery.md` — the push, the gate run
and the report are deliverables to verify, not facts to infer from a clean exit.

## Pitfalls

- Merging on a green CI run when the flow also requires the two inspections.
- Claiming "merge-ready" from CI plus a clean bot marker without checking whether the two inspections
ever ran: the repo's ledger is the recording surface, and an empty one is a missing stage, not a pass.
- Treating a prompt-only "do not edit" instruction as read-only when the lane ships write tools — check
  the tree, or the verdict describes a tree that no longer exists.
- Reading a review bot's `has_any_findings` without reading its `status` first.
- Treating a fallback reviewer as interchangeable without recording which lane reviewed: heterogeneity
  becomes unverifiable afterwards.
- Reporting "review clean" from an empty findings list that an aborted review also produces.
- Reverting a shared branch as remediation instead of opening the follow-up PR.
- Clearing a conflict by force-pushing or by hand-editing a generated file: both put a head under review
  that no tool derived.
- Filing a deterministic install-step failure as infrastructure and rerunning it: the same red returns on
  every leg, and the fix the PR is waiting for never gets dispatched.
- Reviewing a bounded writer, a truncating sink or any retention rule without asking what the reader
  depends on: a bound that keeps "the most recent bytes" by popping the oldest element still evicts the
  **newest** record when that record alone exceeds the budget, and where the consumer derives terminal
  state from the retained tail (a `final` event, a completion marker, the last status line) one oversized
  record silently turns a successful run into a failed one. The single-record-over-budget case is not
  covered by default — require it, with its pin and its mutation, in the same round as the retention
  change. A **shared** writer makes this wider than the one consumer you were sent: the bound is part of
  the contract every route that reads that log relies on, so the round must judge each of them, and the
  the drop accounting (`dropped_bytes`, a `truncated` marker, a stats file) has to stay honest for the readers
    that consume counts rather than the tail. **Check what the bound counts, too.** A ring bounded by *count*
    of lines or records is not a bound on the memory the claim is about: one oversized element defeats it, so
    "bounded" has to name the resource under pressure (bytes retained, not elements held) and the pin has to
    feed a single element far over the per-element limit — a case that also has to read the element's remainder
    away, or the producer blocks on a full pipe while the reader believes it is draining.
