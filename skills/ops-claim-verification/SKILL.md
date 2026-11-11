---
name: ops-claim-verification
description: >-
  Turn a statement about a scheduled job, a repair, or a deployment into evidence before it reaches
  the operator or a teammate: find the surface that actually records the claim, separate a manual
  reproduction from the scheduled run, and treat an external auditor's verdict as a claim set.
  Use when verifying a cron result, a "fixed" claim, a CI/review-bot gate, or a batch status report
  about an environment. Not for auditing the contents of a written report, and not for accepting a
  teammate's delivery — those are separate passes.
metadata:
  version: "0.1.32"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "turn a scheduled-job, repair or deployment claim into evidence: find the recording surface, separate manual from scheduled runs, audit the auditor"
  summary_zh: "把定时任务、修复或部署的说法变成证据：找准记录面、区分手动与调度运行、审查审计者"
  kind: "entry"
---

# Ops claim verification

Any statement about a scheduled job, a repair, or a deployment is a claim about *an environment at a moment*.
This skill converts it into evidence before it reaches the owner or a teammate.

## 0. Quote the authority clause, not its direction

Read the exact line that grants or withholds permission, then enumerate what it does **not** cover.
A policy that makes commit/push a sync service ("per-run approval is gone") usually leaves the adjacent
gates standing: persistent profile/config/memory/schedule/session writes still need explicit owner scope.
Removing one gate is not removing the lane next to it. If you release a teammate on a misread clause, you
are the one who authorized what the owner still gates — and the teammate who refuses is right.

## 1. Find the surface that actually records the claim

Absence in one file is your search error, not the sender's fabrication. Locate the record first, rule second.

- **Scheduled job outcomes** live in the scheduler's per-run output, not the agent log. Common layout:
  `<home>/cron/output/<job_id>/<timestamp>.md` (full stdout/stderr, `Script exited with code N`), while
  the agent log prints only the first line of the injected prompt. Grepping the log for a traceback
  returns 0 on a genuine failure.
- **The wake is the signature.** A logged gate decision (`wake=false, skipping agent run`) = the gate
  returned false (healthy). `Running job` followed by an inbound message carrying the job output = the
  gate did not return false, so the agent was woken by an error or by real work. Read the scheduler's own
  log for its gate lines and the run output for the payload.
- **Repairs** are proven by `git apply --check` against the current tree, `git show --stat` on the landed
  commit, `rev-list --left-right --count origin/main...HEAD` for publication, and a re-run of the gates.
  A patch file that applies cleanly is not a deployed fix.
- **Attribution is a claim too.** "Did you follow X's advice?" / "where did this change come from?" is
  answered by grepping each candidate review stream for the changed paths and terms, then quoting
  `path:line` for the one that actually names them. A repo routinely carries several review streams in
  the same week (external model review, maintenance review, audit notes); the true origin is often a
  different stream than the one named. Answering from memory invents provenance, and a plausible wrong
  "yes" is harder to retract than a checked "no".
- **A batch is many claims, and a plan summary is a claim about its own commit, not about the tree in
  front of you.** When the question is "how much of that improvement program actually landed", the unit
  of evidence is the plan: map each recommendation to its generated plan, read that plan's status line,
  then re-verify every DONE against the current repo (a later rename can make the plan's own paths
  fictional). Program-scale recipe, status vocabulary and the post-execution audit round:
  `references/plan-batch-status-audit.md`.

- **A review-bot verdict marker names the commit it reviewed.** A green marker that quotes an older head
  is the previous round's verdict; the current head is unreviewed. Read the marker (and its `commit_sha`)
  from the PR's own comment stream instead of the bot's prose summary, and re-request the review after a
  push — an external reviewer is not re-triggered by the push itself.

  Landing-loop mechanics (CI log triage, local-vs-CI proof split, marker polling, committing the
  worker's tree): `references/ci-and-review-bot-gates.md`.

## 1b. Evidence bundles handed to an external auditor

When a separate model audits your work without tools, its verdict is only as good as the bundle — and its
false positives become your errors. Before sending:

- **Give structure, not greps.** `grep '^model:'` on nested YAML returns the key with an empty value and
  reads as "unbound"; paste the whole block or parse it. Same for any field that can be a map.
- **Count the thing, not the rendering.** `cli list | wc -l` counts banner lines and separators: a 17-job
  scheduler rendered 202 lines. Count records (`grep -c '<id pattern>'`) and say which caliber you used.
- **Include the boring proofs** for every claim you expect to be judged APPLIED: config file existence,
  the code lines that implement the mechanism, the doc section heading, one command output with rc.
  Missing them yields UNVERIFIABLE, which reads the same as not done.
- **State the sampling frame.** `validator → []` over an empty or single-item population is a vacuous pass;
  say the population size next to the green result, or the auditor will (correctly) call it out.
- **Run the audit as a tool-less one-shot, and keep the prompt.** Invoke the runtime's CLI in one-shot mode
  with an ask-only toolset (`<runtime> -q "$(cat prompt.md)" -m <model> -t ask`; exact flags differ per
  runtime — what matters is that no write tool is exposed). The prompt file (recommendations + claims table
  + raw evidence) stays next to the output so the verdict is reproducible and re-runnable after the bundle
  is corrected.
- **Treat the returned verdict as a claim set, not a grade.** Re-verify each finding against the tree before
  relaying it; label each as *false positive from the bundle* or *real gap*, with the command that decided.
  A quarter of an audit's findings are usually bundle defects, and a verdict accepted unchecked is your error,
  not the auditor's.

## 2. Separate a manual reproduction from the scheduled run

A hand-run of the same script in an agent shell answers a different question: the agent shell's `PATH`
puts the venv interpreter first, while a cron pre-script subprocess can put the host's bundled toolchain
first. Same script, opposite results, same minute. Cite `command -v python3` and the exact `PATH` for any
manual run, and never present a manual `rc` as the scheduled outcome.

## 3. One green run is not restoration

A success proves that run's environment. Check whether the environment was re-provisioned around the
observations — directory mtimes under the host toolchain, install/venv paths appearing or vanishing,
symlink targets. Two failures and one success across such a change is a **nondeterministic dependency**,
not a fix and not a self-heal; say so, and let that be the argument for pinning the dependency rather than
for closing the issue.

The same inversion applies to a *quiet* observation. Absence of the symptom in one sample does not
disprove a periodic fault: measure the cadence over several days, quote the last occurrence with a
timestamp, and answer with the trend — "right now zero connections, 5102 logins by 10:21, and worse each
day" is one honest sentence where "looks fine now" is a false all-clear. Check the sampling window
before the metric: a daily counter read at 10:00 understates a storm that runs all night.

When the claim is about access itself (who is connecting, valid key vs brute force, whether an
egress-pool IP belongs to the owner), use an access-forensics procedure — and preserve its two
separations: "Accepted" is not a credential attempt, and "quiet now" is not fixed.

## 4. Report the finding so it survives the next reader

- Paste computed output verbatim. Re-typing a distribution or membership list from memory is how the
  verification pass injects its own errors.
- One metric, one labelled value per document. If the work moved the number, carry both with time points
  (`pre-fix 83 → post-fix 75`) and name the caliber when two enumerations could both be true (directory vs
  frontmatter `type`, pages vs index rows).
- Verify the artifact, then correct the summary: a diff can be right while the sender's shorthand would be
  wrong if taken literally.
- When only an owner decision remains, stop. No acknowledgement ping-pong; hand the owner one decision with
  the scope, the rollback unit, and the cost of the branch you reject.

## 5. "Pre-existing / unrelated failure" is a claim, not a waiver

A predecessor's green summary ("N−1 pass; the one failure is pre-existing and unrelated") is the sender's
verdict, not evidence. Before shipping work that inherits it:

- Reproduce it yourself with the exact command, and name the failing test/job and its error text.
- Check what the CI gate actually executes. A workflow that runs a narrow subset (docs snippets, action
  pins, one platform) never exercises the full suite, so "CI is green" says nothing about a locally red
  test — a red test the gate never runs can sit for months and is still red.
- Decide by owner intent, not by the label. When the owner asked for everything green before shipping,
  fix it in the same branch as its own commit so the feature diff stays reviewable; when the fix is truly
  out of scope, report the failure and the reason in your own words.
- Never relay another agent's "harmless" as your own judgment; if you did not reproduce it, say so.

## Output shape

1. What reproduced, with the numbers you computed yourself and the file:line that holds them.
2. What did not, correct value first.
3. What is still gated and on whom — a single decision sentence the owner can paste back.

Plain text, one point per line, no markdown decoration.

## Pitfalls

- Ruling on a claim from the wrong file, then retracting it a day later when the sender produces the real one.
- Reading `completed successfully` as a pass: it describes the scheduler's run, not the payload's exit code.
- Calling a transient rerun a fix, or calling one success a recovery.
- Releasing a teammate on a relaxation that covered only a different lane.
- Sending an auditor a bundle built from line-greps and rendered-line counts: the false findings cost a full
  rebuttal round, and the real gaps get buried among them.
- Treating intentional undeployed drift as a regression: name the paths that are meant to be red, and judge
  acceptance as "nothing drifted beyond these".
- Repeating a predecessor's "pre-existing failure" without reproducing it: the label survives every hand-off
  and the red test outlives the change that disclaimed it.
- Trusting "CI is green" for a suite the CI workflow never runs.
