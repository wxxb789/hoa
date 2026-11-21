# Technical blog editing (2026-11-21)

## Before drafting

- Give the post one reader-facing question or decision. Integrate several observations if
  they answer it; otherwise separate them and link independently readable posts in both directions.
- Find a concrete entry point: an observed discrepancy, a usable example, a decision that changed,
  or an exact quote. Without enough material for an argument, write a narrower note.
- Outline by reader question rather than project chronology when the chronology hides the point.
  Map each section to evidence; set aside attractive details that do not advance the argument.
  Keep series names and navigation distinct from the post's title.

## Draft and verify

- A title and opening set an expectation. Sketch alternatives and identify where the body
  delivers each promise. Choose the most specific honest option.
- Explain the object, how it works, and its limits; for a retrospective show the initial
  judgment, what changed it, and resulting decision. Mark interpretations as such.
- Use figures or snippets where readers need to see a relationship, reproduce an action, or
  compare behavior. Check that the actual renderer supports them and that links resolve.
- Distinguish useful parameters, measured evidence, and output counts. Keep exact values where
  reproducibility needs them; drop irrelevant counts or round only without changing the claim.
- For a fresh draft, collect precise facts and verbatim source material separately from the
  previous narrative. State deliberate exclusions. To change only a passage, give the writer
  the existing draft and the bounded request instead.
- Read for structure, fact traceability, and prose in separate passes. Vary emphasis where
  the argument changes direction. Cut repeated scaffolding and unearned conclusions rather
  than mechanically trading synonyms or inserting rhetorical devices.

## Diagnostics and publication

`uv run scripts/zh_draft_check.py <draft.md> --old <previous.md>` surfaces reuse and sentence
patterns. Its built-in thresholds and labels are prompts to inspect, not acceptance criteria.
Separate required quotations and boilerplate from narrative reuse. Exclude code, links, and
enumerations from prose-length judgments when they do not behave like prose.
If the post reads like a delivery log, `uv run scripts/flow_check.py <draft.md>` surfaces
patterns to inspect. Use the result to revisit the outline rather than enforce a score.

If publication is authorized, run the site's preview and review gates. Compare any
publication-set lock with the expected additions and removals. Check the rendered title,
figures and links at the actual layout; after publication, fetch the live page without relying
on a cached preview and verify its content. Diagnose dependency failures separately from
content failures; only retry when the failing dependency has recovered.
