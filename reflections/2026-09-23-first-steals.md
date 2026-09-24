# First steals from ref/: the map pays out

> 2026-09-23 · retro on the first reference patterns landed as artifacts

## Context

The [first retro](./2026-09-23-skills-first-split.md) closed on "On the
horizon: the first `ref/` pattern actually stolen into production". The same
day, a full-project review found the opposite: the "what to steal" column of
the ref map was 40 rows of unspent promissory notes, and nine of ten library
folders were `.gitkeep`.

## What happened

- **Every library folder now holds one exemplar**, each adapted (not ported)
  from a ref/ row, each with provenance and an `<!-- index: ... -->` row:
  - `agents/skill-scout.md` — ECC's search-before-author
  - `orchestration/typed-verification-gates.md` — looper's
    programmatic/judge/human taxonomy
  - `rules/generated-means-generated.md` — from this repo's own drift scar
  - `prompts/fresh-context-grader.md` — the judge shape behind define-goal's
    fixtures
  - `workflows/adopt-a-pattern.md` — the recipe, distilled from doing it
  - `mcps/ghc-proxy.md` — the portable definition, registration left to chezmoi
- **The taxonomy took real content, and held.** The classification table
  resolved every one of the six placements without strain. The one soft spot:
  an exemplar artifact written *as a pattern* (typed-verification-gates)
  versus one written *as a contract* (skill-scout) read differently; the
  classifier didn't care, and that's fine — the folder owns the consumption
  interface, not the prose style.
- **The generator grew up with the library.** `generate_index.py` now indexes
  library folders beside skills (one metadata comment per artifact, wherever
  it lives), so a library artifact can't be invisible the way an unindexed
  skill can't.
- **Trigger evals landed** (`evals/trigger-cases.json`): routing is the
  skill-description contract this repo keeps asserting but never tested.
  10 cases validate offline in CI; an LLM-judge pass is the natural next step.
- **The ref map got its first pruning.** Five submodules dead for 5+ months
  (god-skill: 1 commit total; the persona family duplicated by active
  colleagues) were removed; andrej-karpathy-skills survived as a link-only
  row — the right weight for a one-page idea.
- **Judge baseline is green.** The trigger evals scored **10/10** under
  `evals/judge_trigger_evals.py` (ghc-proxy, gpt-5.6-luna, effort=low) on
  first run — the routing contract holds with real descriptions against real
  distractors.

## What we learned

1. **Seeding beats waiting.** The retro's original bet was "artifacts land
   organically"; three weeks of `.gitkeep` said otherwise. One exemplar per
   folder made the taxonomy falsifiable at near-zero cost.
2. **A steal is a rewrite, not a copy.** Every landed artifact is this repo's
   voice, constraints, and provenance format around an upstream idea — that's
   what makes it ours and keeps the attribution honest.
3. **Counts drift; the counter doesn't.** ghc-search's SKILL.md said "11
   tests" while the suite ran 14. The fix wasn't updating the number; it was
   deleting it (the rule that follows is now `rules/generated-means-generated`).

## On the horizon

- The first skill authored *by* the distill loop — the forge hasn't fired yet.
- Keep the trigger-eval judge baseline green as descriptions evolve.
- The first external consumer issue; the intake is now open (issue templates).
