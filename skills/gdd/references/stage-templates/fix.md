# Stage template — fix review findings

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}`
Goal: ${GOAL}

Findings file: `${FINDINGS_FILE}`

## Instruction

1. Fix every finding in the file that is marked FIX. Fixing a finding means the behaviour, the
   document or the test actually changes — not a comment acknowledging it. The findings file is the
   accepted disposition: do not replan a settled design or weaken a contract clause.
2. **Prove it before you fix it.** For a behavioural finding, check whether the tree already
   satisfies it, find the existing test that should fail without the fix, and observe that failure
   (or capture a characterization baseline) before changing behaviour when practical. If neither is
   practical, say so and name the replacement proof.
3. A finding you judge invalid is NOT skipped: state the reason explicitly, with the evidence that
   makes it invalid, in the report table. A silently dropped finding reopens in the next round.
4. Do not expand scope. Do not restyle unrelated code. Do not delete or weaken an existing test to
   make a new one pass.
5. Re-run the gates and report real numbers:
   `${GATES}`
   Run them as given: one runnable command with its explicit working directory.
6. If the fix touches a measured consumer, re-run the measurement harness and update the numbers at
   their single source (do not leave two versions of the same number).

## Rules

- Do not commit, do not push, do not rewrite history.

## Finish with

A per-finding table: id, file, what changed or why invalid, the green command with its exit code and
the finding or clause it proves (or the replacement proof for an unobserved failure). Plus the gate
table with exit codes and the count of tests before/after.

## Stage result

After the report, end your final message with one fenced ```json block matching the schema at
`${RESULT_SCHEMA}`: `"stage": "fix"`, `"verdict": "DONE"` (or `"BLOCKED"` with the reason in
`summary`); each finding you judged invalid goes in `findings` with its reason as `claim`. Gate exit
codes are integers. If your runtime enforces that schema itself, send the report as its own message
first; the final message is then that JSON object alone.
