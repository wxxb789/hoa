# Stage template — simplify (report only)

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}` (the whole increment, not just the last commit)
Goal: ${GOAL} — contract file: `${GOAL_FILE}`

Use the repo's simplify skill on that range.

MODE: standalone, **report only**. Do not edit any file, do not commit, do not push. The
orchestrator reads your findings and decides what gets applied in a separate instruction.

## Report format

Number findings continuously across **Delete**, **Refactor**, and **Encode as a test**. Each finding:
`file:line` — what is wrong — the evidence (why it is redundant/duplicated/misleading, what test
would have caught it). Then a short list of what is already sound and should NOT be touched.

## Hard constraints

1. Contract, evidence and decision records are deliverables, not prose to prune: do not propose
   deleting measured rows, disclosed limits, non-adoptions, maintainer judgments or boundary
   statements.
2. Tests that pin a contract clause are proof, not noise: do not propose deleting, weakening,
   renaming or merging them, nor the test-only code they call.
3. Do not propose unmeasured micro-optimizations, and do not propose representation changes that
   alter default-value semantics.

Everything else is fair game: duplicated fixtures, expectations derived by running the code under
test, misleading names, dead helpers, comment noise in new files.

End by stating how the findings could be applied: all, specific numbers, or a described subset.
