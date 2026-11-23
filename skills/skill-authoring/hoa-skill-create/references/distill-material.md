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

## Collect by track

- Give each research track one face of the subject: long-form writing, unscripted conversation,
  short-form expression, others' views and criticism, decisions and actions, timeline and recent
  changes. For a topic, first name its few schools or figures, then give each a track.
- File user-supplied material into tracks first and search only the empty ones; label notes as user
  material or web.
- Criticism gets its own track; a portrait without critical material is a fan filter.
- Each track reads the prior first and hunts for what differs, writes as it goes, records actions in
  past tense (year, situation, options, action, outcome, own explanation), grades each item primary,
  cross-corroborated secondary or single secondary, lists contradictions side by side, and ends
  with its overturn, deepen and add items and the dimensions it could not cover. Stop at the planned
  source budget or when consecutive searches add nothing.
- Few overturn, deepen or add items means the notes still restate common knowledge: go to long
  interviews, early writing, participants' recollections and critics before extracting.
- Report the research summary (strongest overturns and additions, contradictions, thin dimensions,
  planned direction) with the result; pause on it only when the user asked to steer.

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
- After drafting, scan the notes for recorded actions with no corresponding move; the commonest
  loss is a finding flattened into a value.
- Delete the subject's name from the models: if another expert could own them, they are not
  distilled yet. A heuristic must fire on a new situation; one that fits only its origin is a case.
- Sort contradictions into change over time (record the trajectory), domain-specific rules (keep
  separate) and value conflicts (tensions, both sides). Do not pick a side, invent a
  reconciliation, or hide one.
- Prefer an honest skill with stated gaps over a complete-looking one that invents.

## Hold out a test set

Before extracting anything, set aside a few primary items, preferably decisions that had a real
alternative or reasoned answers, not slogans. Keep them out of the skill; they are the only ground
truth independent of it. With too little material for a holdout, skip it and state "increment not
tested".

Avoid the subject's famous decisions; both arms already know them. Prefer small reasoned judgments
from long interviews. Keep an item only if a close reader would likely answer it right and a smart
outsider would likely answer it wrong or generically. Record source, a question that does not leak
the answer, the three to five points they actually said or did, and why it was chosen. After
validation an item may move into the casebook; record which.

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
- **A colleague's or practitioner's working method**: build the work playbook first (scope
  and boundaries, how they take on and structure tasks, review standards, output preferences,
  and lessons in their own words); add a persona layer only on request. Weight their own
  long-form writing (design docs, review comments) above decision replies, and those above
  casual chat. Mark a dimension "insufficient material" instead of inferring it. Collectors
  that need a login run in the user's terminal; only exported files enter the session.
- Do not make imitation of a named person's voice the product.

## Refresh or re-distill

- **Refresh** for new events: start from the research date in the limits note and collect only
  conversations, decisions and timeline since then. Evidence that supports a model adds a case;
  evidence that contradicts it records a dated change and rewrites the model; a new recurring
  action may add a move. Update the research date.
- **Re-distill** an old shape without moves, cases or misreadings: while the notes survive, do not
  re-research. Write the prior before rereading the old skill (or label it "not blind"), gather
  scattered old notes into one dated legacy folder with an errata list, search only thin tracks,
  and re-extract. Draw new holdout items mainly from newly found material, but do not seal all of
  it: that material is the increment. Keep the old `SKILL.md` as a snapshot for the comparison arm.

## Cost and validation

Long multi-search research can be expensive; state the expected scale before starting and save
notes per source track so an interrupted run resumes. Validate with [the evaluation
protocol](evaluate.md), using the holdout as ground truth and adding one question the material
does not cover.

Adapted from [nuwa-skill](https://github.com/alchaincyf/nuwa-skill) (MIT, Huashu): `SKILL.md`,
`references/extraction-framework.md`, `references/validation-playbook.md`,
`references/special-cases.md`, `references/research-playbook.md`, and the update section of
`SKILL.md`. The working-method variant adapts
[colleague-skill](https://github.com/titanwings/colleague-skill) (MIT): `prompts/shared/work_analyzer.md`.
