# Stage template — fix review findings

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}`
Goal: ${GOAL}

Findings file: `${FINDINGS_FILE}`

## Instruction

1. Fix every finding in the file that is marked FIX. Fixing a finding means the behaviour, the
   document or the test actually changes — not a comment acknowledging it.
2. A finding you judge invalid is NOT skipped: state the reason explicitly, with the evidence that
   makes it invalid, in the report table. A silently dropped finding reopens in the next round.
3. Do not expand scope. Do not restyle unrelated code. Do not delete or weaken an existing test to
   make a new one pass.
4. Re-run the gates and report real numbers:
   `${GATES}`
5. If the fix touches a measured consumer, re-run the measurement harness and update the numbers at
   their single source (do not leave two versions of the same number).

## Rules

- Do not commit, do not push, do not rewrite history.

## Finish with

A per-finding table: id, file, what changed or why invalid, test/gate result. Plus the gate table
with exit codes and the count of tests before/after.
