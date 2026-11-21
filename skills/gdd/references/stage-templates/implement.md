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

## Optional delegation — `ce-work mode:return-to-caller`

Decide eligibility before invoking, and delegate only when all of these hold: your runtime's own
skill discovery offers `ce-work` with `mode:return-to-caller`; it accepts an explicit plan path or
bounded work statement as the invocation argument; the verbatim `${GATES}` command and its working
directory can travel in separate caller context — in statement mode, written into the statement;
`${GATES}` is a real command, not `-` (no gate supplied); and the runtime will run the loop natively
or on a route the operator already authorized. `mode:return-to-caller` bounds the shipping tail, not
onward routing — a standing cross-model engine can still send the work packet elsewhere, so never
inherit routing authority from this dispatch. If any of these fails, skip this section and run the
loop below yourself. Never install or fetch the skill.

Hand over the loop in the current worktree, recording the expected goal branch first
(`git rev-parse --abbrev-ref HEAD`). Accept its unit commits on this branch and a mid-loop
simplification; it must not push or open a PR. After it returns and before you report, check and show:

- the checkout is still on the recorded goal branch (no switch or detached HEAD), and
  `git merge-base --is-ancestor ${BASE_SHA} HEAD` holds;
- every path touched by every commit in `${BASE_SHA}..HEAD`, enumerated per commit —
  `git log --no-renames --name-status --format=%H ${BASE_SHA}..HEAD` — and every path in a fully
  expanded `git status --porcelain -z -uall --no-renames` inventory is inside the goal's scope, so a
  path added and later removed outside it is still caught;
- it ran the exact `${GATES}` command to completion on the settled final output, and its evidence
  shows the command, working directory and exit status; a complete delegate status never waives
  gdd's gate;
- its run id or archived summary as a recovery pointer, in the report and in the stage `summary` — a
  paraphrase in the stage summary alone is not a recovery artifact.

After the invocation, any failed check above stops the stage: preserve the original scope snapshot,
leave the tree and its commits as they are, report `BLOCKED` with the reason, and do not fall back to
the loop below, retry inline, resume, or advance. A capability decided absent before invoking is the
only reason to fall back.

The delegation contract above adapts Compound Engineering (MIT, Copyright 2025 Every), paraphrased
rather than copied.

## Deliver

1. **Reuse the accepted plan.** Execute the accepted plan by path (the goal file, the design doc it
   names, the shape reference); do not replan a settled design, reopen a decided dependency, or weaken
   a contract clause. Write a short plan only for implementation choices the accepted plan leaves
   unresolved, in the repo's designated plan location (never in a directory the repo forbids for new
   work): public/API shape, exact edge-case semantics the contract demands, evidence plan, design
   trade-offs, and anything you consider out of scope with a reason.
2. **Check before you change.** For each contract clause, check whether the tree already satisfies it
   and find the existing test that pins it. Where practical, observe the expected failure before
   changing behaviour — extend or add the clause test and watch it fail — or capture a
   characterization baseline of the current behaviour first. If neither is practical, say so and name
   the replacement proof.
3. **Then implement**: source, tests, docs, evidence record, examples, and any baseline/manifest
   updates the repo requires.
4. **Close the increment** the way this repo closes one (archive/move the contract file unchanged,
   update its index, reconcile any contract/grammar/stability document the change makes stale).
5. **Run the gates yourself** and record real output:
   `${GATES}`
   When the repo supports it, `${GATES}` is one runnable command with an explicit working directory
   (the operator passes it through `--gates`); otherwise run each gate as given. A gate you did not
   run is missing; never report a check as passed without its exit code.
6. Sequencing rule: never run a measurement/benchmark harness concurrently with the full test
   suite on this host — that gets both killed for memory and looks like a code failure.

## Rules

- Do **not** push and do **not** rewrite history. Do not commit your own edit — leave the tree for
  verification; only unit commits from a `ce-work` delegation you accepted above are allowed on this
  branch.
- Do not weaken, delete or rename a test that pins a contract clause to make a gate pass.
- If a contract-preserving decision is genuinely ambiguous, state the options and your
  recommendation in the plan instead of guessing silently.
- If a measurement or comparison is part of the contract, the baseline must do the same work as the
  implementation (same carrier, same setup charging, competent implementation). An unfair baseline
  is a defect in the deliverable, not a presentation issue.

## Finish with a report

Files written (grouped, committed and uncommitted); gate results with counts and exit codes; and per
contract clause the green command, its exit code, the evidence row that proves it, and the expected
failure or baseline you observed first (or the replacement proof you used). When the loop was
delegated, name the `ce-work` run id or summary and the branch, base, scope and status checks above.
Residual risks and known limits. No adjectives in place of numbers.

## Stage result

After the report, end your final message with one fenced ```json block matching the schema at
`${RESULT_SCHEMA}`: `"stage": "implement"`, `"verdict": "DONE"` (or `"BLOCKED"` with the reason in
`summary`). Gate exit codes are integers. If your runtime enforces that schema itself, send the
report as its own message first; the final message is then that JSON object alone.
