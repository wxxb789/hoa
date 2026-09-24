<!-- index: areas=software-development,work-management,self-management; targets=repo-only -->

# Generated means generated

A standing constraint for anything in this repo that is the output of a
generator.

## Rule

If a file is generated from another source, then:

1. **Never hand-edit the output.** Edit the source (metadata comments, the
   generator's data tables, the fixtures) and regenerate.
2. **Regeneration is part of the same commit** as the source change that
   caused it.
3. **Drift is a CI failure, not a nit.** A `--check` mode exists for every
   generator here; CI runs it and fails the build on drift.
4. **Counts live in one place.** A number of tests, a number of rows, a
   version — state it once (the thing that counts) or not at all; never
   hard-code it in prose that will silently rot.

## Why

Hand-maintained copies of generated facts always drift — the index tables did
before `generate_index.py`, and the "11 tests" comment did after the suite
grew to 14. The fix is always the same shape: make the generator the only
writer, and make CI the enforcer.

## Applies to
`index.md` / `index.zh-CN.md` (`generate_index.py`), vendored shared scripts
(`vendor_shared.py`), and any future generated catalog or count.

## Provenance

Distilled from this repo's own drift scars: the hand-maintained index tables
before `scripts/generate_index.py` existed, and the hard-coded "11 tests"
comment in `skills/ghc-search/SKILL.md` after the suite grew to 14 (recorded
in [`reflections/2026-09-23-first-steals.md`](../reflections/2026-09-23-first-steals.md)).
Not adapted from any `ref/` row — the rule generalizes the repo's own
incidents, in the shape of `workflows/adopt-a-pattern.md` step 5.
