<!-- index: areas=software-development; targets=repo-only -->

# Typed verification gates

An orchestration pattern for loops that verify before they continue.

## Pattern

Every iteration of an agent loop ends at a **verification gate**, and every
gate is **typed** before the loop starts. The type decides who — or what —
may judge it:

| Gate type | Judged by | Example |
|---|---|---|
| `programmatic` | a command with an exit code | test suite, `--check` drift, lint |
| `judge` | a second model with a rubric | "is this answer grounded in the sources" |
| `human` | the operator, explicitly | destructive actions, judgment calls |

## Rules

1. **Declare the gate with the task, not after the work.** A verification
   invented after the output exists is a rubber stamp.
2. **A gate without a type defaults to `human`** — the strictest judge —
   never to "the author's own confidence".
3. **Never let the producer be the judge.** A `judge` gate must run in a
   fresh context, graded against a rubric written before the output.
4. **A loop needs at least one `programmatic` gate** that can fail, or it is
   not a loop — it is a monologue with extra steps.
5. **On gate failure:** retry with the failure evidence appended, up to a
   bounded count; then stop and surface the run to the human. "Stop condition
   met" is a fact, not an acceptance.

## Provenance

Adapted from [ksimback/looper](https://github.com/ksimback/looper)'s typed
verification taxonomy (programmatic / judge / human) plus its loop-lint rule:
a loop whose checks are all vibes, or whose judge is the same vendor/context
that produced the output, is flagged as an anti-pattern.
