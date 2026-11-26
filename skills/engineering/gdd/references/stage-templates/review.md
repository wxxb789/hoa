# Stage template — code review (report only)

Repo: ${REPO_NAME} at `${REPO_PATH}`
Range: `${BASE_SHA}..${HEAD_SHA}` (whole increment)
Goal: ${GOAL} — contract file: `${GOAL_FILE}`

Start only after the simplify findings were applied or the pass was recorded as skipped, so you review the tree that will actually ship.

## Prefer the runtime's read-only reviewer

If your runtime's own skill discovery offers a `ce-code-review` skill that accepts a read-only
`mode:agent`, invoke it through that runtime's skill mechanism — never install it. Before it gets
the diff, establish two things. First, the checkout is clean at `${HEAD_SHA}`: `git status
--porcelain` shows no staged or unstaged tracked delta — a dirty checkout reviews something other
than what ships. Second, the invocation supports the declared no-peer boundary. Then pass
`mode:agent` and `base:${BASE_SHA}` and state explicitly that no external or peer model receives
the diff. A dirty checkout gets a clean authorized checkout pinned to `${HEAD_SHA}`, or the fallback
below; never stash or clean paths you were not asked to move. If the no-peer boundary is not
established before launch, fall back before the diff is sent. Only a project profile that names a
peer and holds separate authority for that review run may override the local-only rule; the profile
preference alone is not current authorization.

Let a started invocation settle and finish its documented recovery and cleanup — terminal
unavailability is an outcome after recovery, not a first error. Accept the result only when it
reports `status: complete`, carries an artifact path or run id, its receipt names head `${HEAD_SHA}`
and base `${BASE_SHA}`, and its scope evidence covers the same changed paths. Keep the full receipt
retrievable from the gdd run. Anything else — skill absent, failed or degraded run, no receipt,
different range or scope, or required coverage the run left out — is **unavailable** or
**incomplete**: name which one in your report and run the report-only review below yourself, filling
any materially missing coverage before approval is considered. An omission the invocation declares
intentional (depth, peer) is not a coverage failure; a required reviewer that failed is. A degraded
receipt is not a clean review. Carry the receipt (status, verdict, run id or artifact path, reviewed
range and scope) into your report and the result `summary`, and map every retained finding into
`findings` below: `location` = `file:line`, `claim` = what is wrong and why it matters, `fix` =
suggested fix or null. Judge those findings under the rules below; the receipt does not set the
stage verdict, and it never replaces the head-bound machine-review marker the operator runs at
merge.

MODE: **report only**. Do not edit files, do not commit, do not push.

## Inputs this prompt must carry

Three things decide whether the review is useful, and the orchestrator owes all three:

- **Intent summary** — what the change is trying to do, in the contract's words. Without it the
  reviewer judges against its own preferred design and returns rewrite advice.
- **Binding standards** — the contributor contract, the accepted design doc, and the predecessor's
  implemented contract. These are what a finding must be anchored to.
- **Do-not-report list** — later goals' scope, formatting taste, prose length, "could be structured
  differently". Without it half the findings are unactionable taste.
- **Prior disposition table (round 2+)** — `Fixed / Dismissed / Known` from earlier rounds with
  the rule "re-raise only with new evidence". Before dispatching reviewers, run a fast diff grep
  for any contract-forbidden literals so trivial omissions do not waste a full review round.

Ask for the diff of the branch against its base, never a single commit, and for each finding:
severity, `file:line`, and **the input that breaks** — not just the concern.

## Grade by what is false, not by severity label

- A P2 that makes documentation, a comment or a test name state something untrue outranks any tidy-up.
- A test that would still pass if the contract semantics were swapped is a real finding.
- A testing gap that only mirrors an internal shape is not.
- Unfair comparisons (baseline doing different work, setup charged to one side only, mixed tiers or
  counters in one table) are findings about the deliverable, not about style.

## Test code is not production code

Triage the diff into production and test paths before grading; test files are reviewed, not skipped.
In test code, a wrong or missing assertion, a mock that passes regardless of the behaviour, an
assertion on private internals, or a skipped test counted as coverage changes the verdict — never
demote it to style. Never recommend sharing an expectation with the implementation or an input
fixture with its assertion: an oracle that moves with the code cannot fail. Repeated literals and
short setup duplication inside one test class are not findings.

## Report format

Per finding: id, severity, `file:line`, what is wrong, why it matters, suggested fix. Then an
explicit verdict line: `nothing material` if there is nothing that would change behaviour or make a
document untrue.

## Dual-axis mode (whole-increment)

When the operator selects dual-axis review, return one report per axis over the same frozen input —
range, changed paths and contract — each with its own verdict line (`APPROVE | MUST_FIX (<n>) |
DECISION_NEEDED (<question>) | BLOCKED:no_progress`) and stable IDs (`STD-A01…`, `SPEC-A01…`). Keep
the test-code triage above in the Standards axis; the Spec axis answers one line per acceptance
clause. If a `(axis, rule, file, mechanism)` quadruple repeats a prior round, stop at
`BLOCKED:no_progress` instead of starting another round. A single receipt from an optional reviewer
cannot substitute for the two verdicts; use its findings as input to both.

## Stage result

After the report, end your final message with one fenced ```json block matching the schema at
`${RESULT_SCHEMA}`: `"stage": "review"`, the verdict line as `"verdict"` (`nothing material` is
`"APPROVE"`, `BLOCKED:no_progress` is `"BLOCKED"`; in dual-axis mode, the worse axis verdict); every
finding also goes in `findings`. Gate exit codes are integers. If your runtime enforces that schema
itself, send the report as its own message first; the final message is then that JSON object alone.
