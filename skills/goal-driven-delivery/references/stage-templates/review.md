# Stage template — code review (report only)

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}` (whole increment)
Goal: ${GOAL} — contract file: `${GOAL_FILE}`

Use the repo's code-review skill on that range. Start only after the simplify findings were applied,
so you review the tree that will actually ship.

MODE: **report only**. Do not edit files, do not commit, do not push.

## Grade by what is false, not by severity label

- A P2 that makes documentation, a comment or a test name state something untrue outranks any tidy-up.
- A test that would still pass if the contract semantics were swapped is a real finding.
- A testing gap that only mirrors an internal shape is not.
- Unfair comparisons (baseline doing different work, setup charged to one side only, mixed tiers or
  counters in one table) are findings about the deliverable, not about style.

## Report format

Per finding: id, severity, `file:line`, what is wrong, why it matters, suggested fix. Then an
explicit verdict line: `nothing material` if there is nothing that would change behaviour or make a
document untrue.
