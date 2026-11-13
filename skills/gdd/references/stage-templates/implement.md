# Stage template — implement

Repo: ${REPO_NAME} at `${REPO_PATH}`
Branch: current (HEAD `${HEAD_SHA}`, based on `${BASE_SHA}`)
Goal: ${GOAL} — contract file: `${GOAL_FILE}`

You are implementing one written increment. Work autonomously until every clause of the
contract is satisfied and the gates have actually run.

## Read first (in this order)

1. `${GOAL_FILE}` in full — it is the completion contract, not a suggestion.
2. The repo's `AGENTS.md` (and any directory-level `AGENTS.md` that governs the files you touch).
3. The shape reference: the most recently merged increment of the same kind (its commit, source,
   docs, evidence record, tests, measurement harness). Match its structure rather than inventing one.

## Deliver

1. **Plan first**, in the repo's designated plan location (never in a directory the repo forbids for
   new work): public/API shape, exact edge-case semantics the contract demands, evidence plan,
   design trade-offs, and anything you consider out of scope with a reason.
2. **Then implement**: source, tests, docs, evidence record, examples, and any baseline/manifest
   updates the repo requires.
3. **Close the increment** the way this repo closes one (archive/move the contract file unchanged,
   update its index, reconcile any contract/grammar/stability document the change makes stale).
4. **Run the gates yourself** and record real output:
   `${GATES}`
   A gate you did not run is missing; never report a check as passed without its exit code.
5. Sequencing rule: never run a measurement/benchmark harness concurrently with the full test
   suite on this host — that gets both killed for memory and looks like a code failure.

## Rules

- Do **not** commit, do **not** push, do **not** rewrite history. Leave the tree for verification.
- Do not weaken, delete or rename a test that pins a contract clause to make a gate pass.
- If a contract-preserving decision is genuinely ambiguous, state the options and your
  recommendation in the plan instead of guessing silently.
- If a measurement or comparison is part of the contract, the baseline must do the same work as the
  implementation (same carrier, same setup charging, competent implementation). An unfair baseline
  is a defect in the deliverable, not a presentation issue.

## Finish with a report

Files written (grouped), gate results with counts and exit codes, contract clauses you consider
covered and how, residual risks and known limits. No adjectives in place of numbers.
