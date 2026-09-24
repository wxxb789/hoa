<!-- index: areas=software-development; targets=repo-only -->

# Adopt a pattern from a reference repo

A finite, outcome-oriented recipe: turn a "what to steal" note in the ref map
into a landed artifact. No retry or scheduling logic — this is a fixed
sequence.

## Steps

1. **Pick one row** from `ref/README.md` whose *what-to-steal* column names a
   concrete pattern (not a vague "nice ideas").
2. **Read the upstream source** for that pattern — the actual file, not the
   map's one-liner. Confirm the pattern is what the map claims.
3. **Classify the target** with the README's table: where does the adapted
   artifact belong (`skills/`, `agents/`, `rules/`, …)?
   - If it is a deployable capability invoked by name → a skill.
   - If it is a role contract, standing constraint, prompt shape, or
     orchestration pattern → the matching library folder.
4. **Adapt, don't port.** Rewrite in this repo's voice and constraints; keep
   attribution with a `Provenance` section linking the upstream.
5. **Add the `<!-- index: ... -->` metadata** comment and make sure the
   artifact has an index note: a frontmatter `description:` (preferred) or a
   readable first body line, unless a curated bilingual note belongs in the
   generator's `NOTES`. Regenerate the index
   (`python scripts/generate_index.py`), and run the repo's checks.
6. **Mark the steal in the map**: change the row's *what-to-steal* cell to
   note where it landed (e.g. "→ landed as `rules/generated-means-generated`").

## Stop conditions

- The pattern does not survive contact with the upstream source (map was
  wrong) → fix the map row, land nothing.
- The pattern needs a whole repo's context to make sense → leave it as a
  link-only reference; do not force it into an artifact.

## Provenance

Workflow shape distilled from this repo's own first steal (ECC's skill-scout
→ `agents/skill-scout.md`, looper's typed gates →
`orchestration/typed-verification-gates.md`).
