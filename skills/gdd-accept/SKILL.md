---
name: gdd-accept
description: >-
  Decide whether one agent run's change is acceptable: settle the tree before gating it, recover the
  provenance the run did not record, re-derive every number it quoted, review the change for semantic
  widening, and triage the review findings into fix-now, defer and record. Use after an implementation,
  simplify, apply or fix run reports done, and before that tree is committed or merged. Do not use for
  grading a change you authored by hand, or when no diff exists to inspect.
metadata:
  version: "0.1.49"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "settle the tree, recover provenance, re-derive numbers, review for semantic widening, triage findings"
  summary_zh: "验收 agent 产出：等树稳定、补回 provenance、重算数字、审语义放宽、分级 findings"
  kind: "mechanism"
  consumes: "work-report"
  produces: "run-verdict, findings-triage"
---

# Accepting an agent-produced change

A long stage run ends, reports `done`, and hands you a diff. Between that report and a merge there are
five checks, in this order. Each exists because a green result was once produced while the thing under
test was still moving, missing, or wider than intended.

## When to Use

- A delegated implementation, simplify, apply or fix run reports `done` and you must decide whether its
  change is acceptable.
- A review bot returns findings and they must be sorted into fix-now, defer, and record-as-a-decision.
- The owner asks "which model actually produced this?" or "is this really green?" about a finished run.

Not for: grading a change you wrote by hand, or when no diff exists to inspect.

## 1. Settle the tree before you gate it

`state: done` / `exit 0` describes the process, not the filesystem. An agent writes until its final
turn, so a write can land after the report. A gate fired immediately on that report read a half-written
tree and returned `19 passed, 1 failed`; the same commit returned `20/20` once the writes settled.

- Sample twice a few seconds apart: `git status --porcelain` plus the newest mtime under the changed
  paths. Gate only when both samples are identical.
- A gate that fails within seconds of a `done` report is suspect by default. Re-run it on the settled
  tree before calling it a real failure, and say which tree the green number came from.
- If it still fails on a settled tree it is a real failure — do not run it a third time hoping.

The write-surface half of acceptance — snapshot, diff, seal, verify — belongs to
`delegated-work-acceptance`'s `worktree-scope.py`; this skill rules on the diff itself.

## 2. Recover the provenance the run did not record

A run record can carry `model: null, thinking: null` because the wrapper omitted those flags and fell
back to the CLI's own config default. The finished run then cannot answer "which model produced this?"
from its own record — and that question gets asked, usually by the owner.

- The wrapper's default usually lives in the CLI's own config file and encodes the effort inside the
  model string (`provider/model:max`), so the pair stays answerable even when both run fields are null —
  read the config, and quote it as *the config's default*, never as the run's own metadata.
- Prove it from the log the run actually wrote:
  `grep -o '"model":"[^"]*"' events.ndjson | sort | uniq -c`, and the same for `"provider"`.
- Count as soon as the run starts or finalizes: long runs truncate the event log
  (`events_truncated: true`, hundreds of MB dropped) and take the early turns' metadata with them.
- If the answer must stay auditable, pass the model and effort explicitly at dispatch so the state file
  records them. Never present the config default as the run's fact.

## 3. Re-derive every recorded number

Test counts, assertion counts, gate counts and evidence rows go stale the moment a fix adds a case. An
evidence document still quoting the old test count after an apply pass that added two is wrong in the
direction that reads as diligence.

- After every apply/fix round, re-run the suite and update the evidence row to the measured number.
- Re-derive before quoting, not after: the number in your report is a claim you now own.
- Check that the test-count delta matches the tests you accepted. A count that moved without new cases
  means a test was deleted or a suite was skipped.

## 4. Review the change for semantic widening, not for style

A refactor that consolidates duplicated code is where permissions broaden. Two call sites can have
byte-identical bodies and still answer different questions — one consumes a grant for local inference,
the other authorizes egress to a third-party destination. Merging them hands the weaker destination the
stronger permission, and **no test fails**, because the tests encode the pre-merge semantics and the
widened grant still satisfies every one of them.

- Before accepting an "extract this helper / share this predicate" change, write down per call site: the
  grant it consumes, what it may touch, and the destination. Different answers anywhere → share only the
  mechanics (parsing, the query) and keep two decisions, with the destination passed in explicitly.
- **Assign every caller after a split.** Splitting one predicate into two rules is a second decision, not
  the absence of one: a caller left on the old helper silently inherits whichever rule you left in it.
  Walk the call sites again and name the rule each needs — a tightening written for the egress path
  becomes a silent bypass for the inference path that still shares it.
- Same blind spot: a new path that skips a precondition every sibling enforces (a verification gate, a
  budget reservation, a consent check). Grep the siblings for the guard and confirm the new path calls
  it.
- Same blind spot again: a derived total that drops a term once a special case becomes non-zero.
  Recompute the total by hand at zero usage, one unit and two, and compare with the printed value.

## 5. Triage an external reviewer's findings by mechanism, not by badge

A review bot reads the diff as a change to a running system, which is exactly what the gates cannot do.
Its unique yield is the semantic collision in section 4.

- Classify each finding before dispatching a fix: **authorization boundary**, **precondition bypass**,
  **accounting drift**, or **record-and-code disagreement**. The first two block regardless of the
  badge: a P2 that skips a verification gate on a billable path outranks a P1 typo.
- When a finding says an existing permission is now too wide, it is a tightening, not a style note.
  Land the stricter answer; whoever needs the wider case can re-justify it.
- Sort the rest into `apply now` / `defer with a reason` / `record as a decision instead of changing
  behaviour`. A finding that would change recorded semantics belongs in the open-questions file with a
  repro, not silently fixed inside an unrelated increment.

## 6. Make each accepted finding prove itself

- The test must fail without the fix **and assert the negative**: the stub received zero calls, the
  export was refused, the untouched sibling still reads `declared`. A test that only exercises the newly
  allowed path passes under both the bug and the fix.
- Deleting test lines is expected when a signature changes; confirm every deleted line is a call-site
  migration or a replaced assertion, never a removed case. Run `git diff -- '*_test.go' | grep '^-'` and
  read all of them.

## Pitfalls

- Gating the tree the moment a run prints `done`.
- Quoting the run's `model` field as fact when it is `null` and the answer actually came from config.
- Trusting an evidence document's counts across an apply pass; they are a snapshot of an older tree.
- Accepting a dedupe because "the code is identical" without asking whether both call sites grant the
  same thing to the same destination.
- Fixing a reviewer's finding yourself instead of dispatching it — the diff then belongs to no run, and
  the next review cannot attribute it.
- Reading a bot's P-number as severity here; classify by mechanism instead.
- Reading a merge gate's non-zero exit as a failure while CI is still running. A script that stops on
  the first unfinished check prints only the shards that already finished (one `pass` line, no verdict)
  and exits non-zero, which reads exactly like a crash and invites a pointless debug of `gh` or of the
  thread query. Run `gh pr checks <PR>` first: any `pending`/`queued` line means the gate is early; only
  when every shard is finished is that exit a real tooling problem.
- Re-dispatching a stage under a run name that already exists: the run dir is reused, so the previous
  round's `done`, duration and cost are what you read while the new run is still starting, and a stale
  `prompt.md` may still name the old findings file. Confirm `resumed_from` is null and grep the rendered
  prompt for the file you just wrote before polling.

## Related

Skill `delegated-work-acceptance` owns the general artifact-and-scope pass (write surface, re-derived
population, handoff corrections). This skill covers the run-to-merge interval that pass does not: tree
quiescence, runtime provenance, and semantic review of a refactor.
