<!-- index: areas=software-development,work-management; targets=repo-only -->

# Fresh-context grader

A one-shot prompt template for judging an artifact without contamination.

## Template

```text
You are grading a response produced by someone else. You did not produce it.

[Artifact under test]
{response}

[Rubric — written before the response existed]
{rubric: expected_mode / must_hold / must_not_hold items}

Grade the response against the rubric only:

1. For each must_hold item: does the response hold it? Quote the evidence.
2. For each must_not_hold item: does the response violate it? Quote the evidence.
3. Verdict per item: hold / violation / not-evidenced.

Do not reward style, effort, or partial credit. "Not-evidenced" on a must_hold
item is a failure. Report items in rubric order; do not summarize away a
violation.
```

## Usage notes

- Run in a **fresh context** that never saw the production run; a grader that
  watched the work is the producer judging itself.
- The rubric must have been written before the response — otherwise it drifts
  to match whatever was produced.
- Grade semantics, not wording; expected_mode names a mode, not a sentence.
- Keep the artifact verbatim — no cleanup, no fixing typos before grading.

## Provenance

Shape distilled from the define-goal judge fixtures (`must_hold` /
`must_not_hold` / fresh-context procedure) and the grilling / adversarial
review patterns in [obra/superpowers](https://github.com/obra/superpowers).
