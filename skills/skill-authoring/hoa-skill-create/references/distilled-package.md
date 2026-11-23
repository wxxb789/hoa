# Shape a distilled skill package

Read this when writing the package a distillation produces. The layout is a floor, not a form:
when the subject's most valuable asset is a procedure or a checklist, give it its own section or
reference file.

## Layout

- `SKILL.md` loads on every activation. Keep only how to use it, moves, models, heuristics,
  misreadings, a case index, tensions, boundaries and sources; move anything only some questions
  need into references.
- `references/casebook.md`: one card per case, read on demand.
- `references/passages.md` (optional): sourced primary passages with visible reasoning, grouped by
  occasion (writing, unscripted answer, under challenge, on their own mistakes). They are evidence
  for reasoning and stances, not a style sheet.
- Research notes, the prior and the holdout stay outside the installed package: an install copies
  the whole skill directory, so anything inside it is visible at runtime and spoils the holdout.

## Sections

- **Move**: trigger, concrete action someone could copy, one dated, sourced example.
- **Model**: one line, evidence from two domains, when to use it, when it fails (ideally where the
  subject failed).
- **Misreading**: the popular view, then what the primary record shows, with source.
- **Case card**: situation (options and pressure), action (past tense, a verb not an attitude), own
  explanation (a quote from that episode or blank), afterwards (outcome, later reflection or
  reversal), analogous problems, source with confidence. Include failures, regrets and say-do gaps;
  keep two cases with opposite outcomes when both exist; small everyday cases transfer well.
- **Case index**: id, year and event, and a "use when" column written in the words a user's problem
  would use. Unused cases usually trace to this column being too narrow or abstract.
- **Tensions**: evidence on both sides, unreconciled.
- **Boundaries**: the three cells, each with how to answer. Present silence faithfully; do not
  generate a compromise on the subject's behalf. Close with the research date, this distillation's
  blind spots, the prior's bias, and what new evidence would overturn the conclusions.

## Runtime rules

Write a "How to use" section with these rules. Adapt the wording to the skill, but keep every
meaning. By default the skill speaks about its subject in the third person.

1. Classify each question. Documented: answer with cases. A well-recorded episode of the subject's
   that the casebook lacks: tell it fully from memory with a half-sentence caveat; never downgrade
   it to inference. Outside their experience: answer and say once it is inferred from their
   approach. Silence or known misjudgment: say so; do not force an answer.
2. For a concrete decision, find the closest cases in the index and read their cards first. Tell
   the recorded cost along with the success, give only sourced motives, and keep case ids out of
   the answer.
3. When the answer depends on current facts, gather the specific facts the subject would check
   first (named in the moves) from tools or the user; mention the research date only then.
4. Keep sourced quotes, memory and new reasoning distinguishable; never invent a quote. The
   material adds to what the model knows rather than replacing it; on conflict the sourced material
   wins. One "not in this material" per answer is enough.
5. Raise a known blind spot only when it affects the user's decision, without a fixed closing line.

First person is an opt-in mode, only for a public or deceased subject and only when the user asks
the skill to speak as them. Then also: say once per conversation that this is a perspective
distilled from the public record, not the person; on "exit" return to the plain assistant, and on
"analyze without role-play" switch to third-person analysis with sources; in long conversations
re-read the sourced passages to keep reasoning and stances anchored, not to copy phrasing. Never
use first person for a living private person or a colleague.

These rules instruct the model; their vocabulary ("blind spot", "case card", "inference") should
not appear in answers. Rules 1 and 4 exist because a skill that treated "not in my material" as
"inferred" scored below the no-skill baseline on held-out questions.

For a topic or method skill, split models into consensus and disagreements, and replace passages
with a glossary.

## Before delivery

Check that every case id in the index has a card and every card is indexed, every card cites a
source, the limits note carries a research date, a holdout exists or "increment not tested" is
stated, and no holdout item appears in a runtime file.

Adapted from [nuwa-skill](https://github.com/alchaincyf/nuwa-skill) (MIT, Huashu):
`references/skill-template.md`, `references/extraction-framework.md`, `scripts/quality_check.py`.
