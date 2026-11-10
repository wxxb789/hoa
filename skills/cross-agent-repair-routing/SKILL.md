---
name: cross-agent-repair-routing
description: >-
  Get a defect repaired when it sits in another agent's write surface: establish the authority map,
  rule on the claim, reproduce under the reporter's environment, and escalate one scoped landing
  decision. Use when you found a bug you may not fix in a shared tree. Not for fixing your own files.
metadata:
  version: "0.1.25"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
---

# Cross-agent repair routing

You found a defect, you may not fix it (wrong write surface), and the tree is shared with other agents
plus an automated publisher. This skill is the loop that gets it repaired without you overstepping or
turning the thread into chatter. For the per-artifact detail behind each step, load
`delegated-work-acceptance` (verify one sender's delivery) and `report-claim-audit` (audit a digest).
For a defect that keeps coming back on one code path, `references/fixing-a-defect-class.md` turns the
findings into an invariant the fixer must satisfy.

Roles, not names: the **front door** classifies an incoming report and routes it; the **builder** owns
the code path; the **domain owner** owns a subsystem's rules and review; the **operator** owns
runtime/config landings, credentials, and session state. Your write surface is your own role
contract; the defect belongs to whichever role owns the file, not to whoever noticed it.

## 1. Establish the authority map before touching anything

- Read your own role contract and the fixer's: your write list, theirs, and what needs the operator.
- Operator-only lanes travel intact: runtime/config changes, shared-repo landings, commits, credential
  or session state. Never widen a request to "just fix it" because the fix is two lines.
- Write down what you will *not* touch in the same message that authorizes work, so the fixer does not
  infer permission from your enthusiasm.

## 2. Ruling on the claim

- Recompute the artefact's numbers from the source that owns them; a teammate's verification report is a
  witness, not evidence.
- Label every number with its **caliber** (which enumerator or field defines the set) and its **time**
  (before or after the change). The same metric printed twice with two values and no labels is a defect
  to send back, not something you reconcile silently.
- Never infer a declared field from where an item lives. Folder, batch name and the team's nickname for
  the batch all lie about the field; parse it per item. Publish both readings, named, when both are
  legitimate, and say which one the downstream rule keys on.
- Copy lists and groupings out of the output you just computed. Retyping from memory is where a wrong
  membership becomes a published fact in your own correction — the error you are sending back.

## 3. Reproducing a defect report

- Reproduce under the reporter's environment: PATH order, cwd, stripped env, the runner's own binary.
  Your interactive shell resolves a different binary and returns a clean pass that contradicts them.
- Build probes from a **glob, never from a copied path**. Tool output that masks or elides part of a
  literal path will not exist on disk when pasted, and the shell falls through to the next entry — a
  false negative that reads like proof.
- Capture the exit code without a pipe: `cmd | tail` reports the last stage, so a failure prints as
  `rc=0`.
- Separate environment from code: a capability missing from whichever interpreter the runner happens to
  pick is a selection bug in the wrapper. Hand the fixer the shape that survives it — probe for the
  capability, keep a runtime override, fail loudly with a distinct exit code instead of a bare traceback.
- Reproduce an automated reviewer's finding with **the project's own tool**, not with your reading of its
  prose: write a throwaway probe **inside the repo root** (copy the import from the file under review)
  and print input → decoded/parsed value → what the rewrite emits. Out-of-tree scratch paths cannot
  resolve the project's `node_modules` and the module error reads like "the package is not installed".
  Quote the measured tuple for every clause before you dispatch the fix.
- Triage a red gate by the failing step's own log before calling it a code defect:
  `gh run view <run-id> --log-failed` names the step, and an install/download error (an HTTP 5xx on a
  release asset) is infrastructure — re-run **only that job** (`gh run rerun <run-id> --failed`) and keep
  both runs in the log. A workflow-wide rerun hides which failure was real.
- A reviewer finding is class-shaped until proven otherwise: grep the construction for sibling call sites
  (one escaping helper reached from a source-byte path and a decoded-value path is the classic) before
  accepting a single-site fix.
- For generated files the fix belongs in the generator, proven by regenerating and re-running under the
  hostile environment. A hand-edited generated file passes today and is overwritten at the next apply.

## 4. The tree is shared and may already be published

- Read the contract for a standing auto-sync/publish exception before promising "we wait for operator
  approval to commit": where a scheduled job commits and pushes the working tree on a timer, review
  happens after publication and revert is the only control. Say that, and correct your own earlier
  promise.
- "Commit only my hunks" cannot be honoured under an `add -A` sweep: it collects every agent's in-flight
  edit. The decision is the operator's (land together, or park the other writer's work), and nobody may
  tidy a shared file to make their own commit clean.
- Re-read the live tree immediately before applying a patch; peers keep extending shared files during
  the round, and a patch verified an hour ago may conflict now.
- Files a pipeline deletes before committing (dated report stubs) are not durable. Anchor the numbers
  you will diff against later inside a surface that survives.

## 5. Loop control

- One round = one ruling + the exact next action. Send corrections as a numbered list with the correct
  value already supplied; the sender fixes its own file.
- **Second finding on the same path ⇒ stop patching instances.** Convert it into an invariant (round-trip
  `parse(rewrite(x)) === parse(x)`, idempotence, byte equality) and give the fixer a table-driven corpus
  that must satisfy it, with old-vs-new output for every row. Two instance fixes on one path is the signal
  that the rewrite's shape is wrong. Recipe: `references/fixing-a-defect-class.md`.
- Key every automated-review verdict to the commit it reviewed — the review-state marker carries a sha —
  and wait for the sha to match your head before merging: a clean verdict for the previous head is not a
  verdict for yours, and a push alone does not re-trigger the review. Request it explicitly after the
  gates are green.
- Do not resolve the reviewer's thread when the fix is pushed; resolve after the verdict for that head is
  clean, or the next round's finding lands with nowhere to live.
- Re-verify the correction: a revision is a fresh claim. Check closure again (subsets sum to the
  population, two mentions of one metric agree) — revisions routinely fix the flagged item and introduce
  a new inconsistency a few lines down.
- Freeze the artefact explicitly once it passes, and say when it becomes immutable (publication time).
  Further edits after that are a new revision, not a continuation.
- No acknowledgement ping-pong: when the other side reports "parked, awaiting authorization", reply to the
  operator, not to them. Stop the loop when the only thing left is someone else's decision.

## 6. Escalate with a landing zone

One decision per message, with: the exact paths and hunks, what the fixer will and will not touch, the
acceptance test in runnable terms (regenerate, then run X under the hostile environment, expect Y), the
rollback unit, and the cost of the other branch. Recommend one branch. A fixer told "fix it" without
scope will either overreach or sit still.

## Pitfalls

- Fixing a defect in another role's surface because you both have write access to the machine.
- Accepting a correction as verified because the sender said "fixed" — re-read the region.
- Retranscribing an abbreviated form into a fix instruction; paste the exact strings from the diff.
- Reading a masked path back into a command and calling the fallback a pass.
- Telling the operator work is "waiting for commit approval" while a pipeline is publishing it hourly.
- Letting a stale snapshot decide an apply, or reporting a peer's earlier diagnosis as current state.
- Chasing a fix across a boundary in several messages instead of escalating one scoped decision.
- Dispatching a reviewer finding without reproducing it. Such reviewers are right often enough that the
  habit trains you out of checking, and the first wrong one ships a change to a path that was already
  correct.
- Probing a defect from outside the repo root and reading the module-resolution error as a missing
  dependency.
- Treating a workflow-wide rerun as proof the failed step was flaky; only the failed-job rerun isolates it.
- Handing the fixer the reported example when the same construction has other triggers (`&` escaped but
  `*`, a backtick and `<` left raw). The corpus, not the example, is the request.
