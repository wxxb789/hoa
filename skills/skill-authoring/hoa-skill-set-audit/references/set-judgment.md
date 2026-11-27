# Judge the offered skill set

Read only when assessing overlap, visibility, pruning, or necessity. Check the
visible set first, then hidden skills. Findings and verdicts are proposals,
not authority to make changes; every cut needs explicit owner confirmation.

## Assessment axes

Assess each skill named in a set finding (or every skill when the owner asked
for a full prune):

- **Usage:** recent, historical, or unobserved, from host usage data, never from
  the name.
- **Overlap:** unique, complementary, or a replacement candidate.
- **Core value:** the owner's main workflows, on demand, or non-core.
- **Quality:** clear, bulky or ambiguous, stale, risky, or malformed.
- **Necessity:** non-inferable behavior or knowledge versus advice a capable
  model already follows unaided.

## Necessity verdicts

Give each assessed skill exactly one: `keep`, `keep explicit-only`, `merge into <name>`,
`cut`, `needs A/B`, or `needs owner`. State the evidence that earns it. Do not equate no
observed usage with no value. `keep explicit-only` is for valuable manual workflows; verify that
required sibling Read links still resolve. A single skill needing deeper judgment goes to
`hoa-skill-review`; provenance and upstream freshness stay with `hoa-skill-curate`.

For a locally authored skill with no upstream, the owner's rule is **180 days unloaded, or
never loaded** makes it a cut candidate, unless current projects suggest a plausible near-term
use. Use usage records with known coverage and directory history, not `SKILL.md` mtimes. Missing
usage data is `unobserved`, not evidence for a cut. Every cut stays a proposal pending explicit
owner confirmation.

Nominate at most five uncertain skills for A/B, and run probes only if the owner authorizes
the cost. Write two or three representative prompts and a rubric first. Run with and without the
skill in isolated environments, check the no-skill trace never loaded it, and grade responses
blind against the rubric. A skill that adds no verified value is a cut or merge candidate.

## Set-level checks

| Check | Evidence | Typical fix |
|---|---|---|
| Overlapping activation | `overlap` pairs (lexical candidates only), then read both descriptions against 2–3 realistic requests: would the model pick reliably? | merge, or narrow one description with a mutual anti-trigger |
| Contradictory instructions | the same situation governed by two bodies (commit rules, output format, authority) with different answers | one owner; the other points to it |
| Shadowing | `totals.visible_names`, plus a generic skill whose trigger swallows a specialist's | hide or retire distractors; keep the visible set small ([host shadowing evidence](hosts.md#shadowing)) |
| Near-duplicate names/descriptions | `overlap`, `duplicates.by_hash` | merge or retire the weaker |
| Same name, different content | `duplicates.by_name` with `same_content: false`; `offered-twice`; [host precedence](hosts.md#roots-and-same-name-resolution) says which copy wins | remove or re-sync the losing copy; pin the source |
| Visibility mistakes | `offered.hidden_but_offered`; `codex-policy-missing`; `hidden-codex-only`; a chained child absent from every root, or removed by a host deny/exclude setting | fix the frontmatter/openai.yaml pair; install the child; never deny a chained child |
| Broken `../` closure | `closure-*` findings: lexical and physical sibling must both exist and match | install the parent's whole `../` closure into the same root |
| Wrong discovery depth | `beyond-host-depth` | move the skill to the host's discovered level |
| Budget and truncation | `offered.without_description`, `totals.visible_description_chars` vs the host budget | shorten descriptions, hide rarely chosen skills |
| Horizontal knowledge in a skill | a skill every task needs, or one never selected while its content is always relevant | move it to an always-on index (AGENTS.md / rules) |
