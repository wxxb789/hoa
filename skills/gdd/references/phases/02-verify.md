# Phase 2 — verify before believing anything

The agent's report is a claim, never evidence:

> Mechanics: `gdd-gates` runs the repo's gates so the counts hold; `gdd-accept` rules on one run's
> diff; `gdd-measure` is the campaign when the contract's pass condition is a measured number.

- Run the repo's gates yourself and read real exit codes.
- **Exit 0 means the process ended, not that the phase finished.** Read the run's final assistant text
  (`answer.md`): a report ending with "the gate is running, waiting for its result" ended mid-gate.
  Resume it, or run the remaining gates yourself — never accept the exit code as completion.
- **A non-zero gate that names a missing build output is a prerequisite failure, not a regression.**
  Read the message before calling it a delta; produce the artifacts and re-run.
- Map every contract clause to a test name or evidence row; a clause with no test is unfinished work.
- **A proof test is only proof if it fails when the feature is deleted.** A loop over a collection
  that is empty without the feature, an input that already declares the value the assertion demands,
  and an assertion that reads the same source the code reads all stay green with the change reverted.
  Vacuous coverage is the one defect that hides every other defect in the same file.
- **An assertion that only checks a count is not verification.** A clause "proven" by
  `assert(checks > 0)` stays green after the entire section it guards is deleted — read the
  assertion's substance, not its existence. Raise a weak proof test as its own increment and tell the
  operator; do not let it be absorbed silently into the current apply round.
- Diff the plan's file list against `git status`; missing tests or docs are the usual gap.
- Re-run gates on the FINAL tree, even if they passed earlier — a resumed run keeps adding code and
  the counts move.
- Research-outcome increment: the deliverable is a decision, not a feature →
  [`references/evidence-fairness.md`](../evidence-fairness.md) before accepting any
  "faster/cheaper" claim.

## When a gate is red for a reason the change did not cause

Gate red for a reason the change did not cause, on a branch that must ship: fix it as its own
commit and disclose it — decide, don't silently absorb.

## Pitfalls this phase answers

- **A self-reported "done" with no gate output is unverified.** Ask for exit codes, then run them.
- **Put the project's own toolchain first on `PATH` before running its gates.** An ambient interpreter
  below the project's floor fails in a way that reads like a code defect.
