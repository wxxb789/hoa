# Stage template — apply accepted simplifications

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}`
Goal: ${GOAL}

Apply **only** the accepted simplify findings below, then re-run the gates.

Findings file: `${FINDINGS_FILE}`

## Instruction

1. Read the findings file. Apply exactly the findings marked ACCEPT.
2. For every finding marked SKIP, change nothing and keep the stated reason intact in your report —
   do not silently drop a finding.
3. If applying an accepted finding turns out to conflict with a contract clause, stop on that
   finding, keep it unapplied and say so explicitly.
4. Re-run the gates and report real numbers:
   `${GATES}`
5. If the accepted set touches measured consumers, also re-run the measurement harness (never
   concurrent with the full suite) and republish every affected number at its single source.

## Rules

- Do not commit, do not push, do not rewrite history.
- Do not expand scope beyond the accepted findings; do not "fix while you are there".
- Do not delete or weaken a test, an evidence row or a documented boundary to make the tree simpler.

## Finish with

A per-finding table: number, file, what changed, gate result. Plus the gate table with exit codes.
