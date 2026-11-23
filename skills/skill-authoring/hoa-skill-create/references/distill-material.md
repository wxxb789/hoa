# Distill a skill from source material

Read this when the skill's content comes from a body of material (a domain's literature, a
person's documented work, transcripts, or upstream repositories) rather than from a procedure the
user already holds. The skill is worth only what a model cannot answer, or answers shallowly,
without it.

## Write the prior first

Before reading the material, write down what you already believe: the core claims, the facts you
are sure of, the ones you are not, and the common one-line impression. Save it with the research
notes. If you have already read the material, label the prior "not blind". When the prior is
nearly empty, say so; then every finding is new.

## Keep the increment

- Tag each finding: **overturn** (the prior or popular view is wrong), **deepen** (right direction,
  now with conditions, cases and sources), **add** (absent from the prior) or **confirm**.
  Confirmations get a line at most. Overturns become an explicit "common misreadings" section.
- For every line you plan to keep, ask whether a model without the skill would say the same. If it
  would, compress or cut the line.
- Record what was done as moves: trigger, concrete action, sourced example. "Values evidence" is a
  lost finding; "re-derives the order of magnitude before trusting a result" is a move.
- Promote a claim to a model or rule only when it recurs in two or more domains, predicts a
  position on a new problem, and is not what any competent practitioner would say. Otherwise
  demote it to a heuristic or a case.
- Prefer concrete cases (situation, action, stated reason, outcome, source), and include failures
  and reversals. Keep contradictions with evidence on both sides; date changes of mind.
- Tag provenance as said, did, said by others, or inferred. Drop any quote you cannot trace to an
  original. A site root, search page or topic page is not a source.
- When choosing sources, prefer long-form over quotes, controversy over consensus, changes of mind
  over fixed positions, actions over statements, and unscripted answers over prepared ones.

## Hold out a test set

Before extracting anything, set aside a few primary items, preferably decisions that had a real
alternative or reasoned answers, not slogans. Keep them out of the skill; they are the only ground
truth independent of it. With too little material for a holdout, skip it and state "increment not
tested".

## State the boundaries as behavior

Sort topics into three cells: documented, inferable from the extracted models, and silent or
known blind spots. Say how the skill answers in each cell. "Not in the material" is not "never
said". Close the skill with a short limits note: missing material, the prior's bias, and what new
evidence would overturn the conclusions.

## Variants

- **Topic or method** (several authors or schools): record consensus and disagreements per school,
  write in a neutral voice with a glossary, and use canonical cases with known outcomes as the
  holdout.
- **A living private person**: use only material the user supplies, with no web search. Remind the
  user to get the person's consent, and keep the result unpublished. When the user distills
  themself, record where what they did differs from what they say they do.
- Do not make imitation of a named person's voice the product.

## Cost and validation

Long multi-search research can be expensive; state the expected scale before starting and save
notes per source track so an interrupted run resumes. Validate with [the evaluation
protocol](evaluate.md), using the holdout as ground truth and adding one question the material
does not cover.

Adapted from [nuwa-skill](https://github.com/alchaincyf/nuwa-skill) (MIT, Huashu): `SKILL.md`,
`references/extraction-framework.md`, `references/validation-playbook.md`,
`references/special-cases.md`.
