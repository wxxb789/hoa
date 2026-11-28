# Reviewing a protocol, skill or checklist

A prose artifact fails differently from code, so a code-shaped prompt returns prose-shaped praise
("well structured, comprehensive"). Ask these six, in this order, and require a citation for each.

## 1. Does it degenerate into a form?

Compute the realistic size of the interaction the protocol prescribes: number of undecided decisions ×
blocks per question × two languages of detail. A rule that sends the whole decision set in one message
is a form to rubber-stamp, and the operator's rational response is to answer "ok" N times — which is
exactly the silently-decided outcome the protocol exists to prevent. Look for the protocol's own
vocabulary: it usually already contains a grouping concept (a root, a level, a phase) applied to one
part of the flow and not to the message shape.

## 2. Where can the agent still decide silently while appearing to comply?

Enumerate the places where a compliant-looking run buries a decision:

- the agent chooses the **set** of questions (an unlisted concern is never offered);
- option pruning happens invisibly (the operator cannot challenge the exclusion, only the survivors);
- the confirmation is an agent-written **paraphrase** of the operator's answers;
- a section the protocol calls "confirmed" is drafted by the agent and shown for approval;
- a classification step (choice vs lookup, fact vs preference) hands the framing decision to the party
  with less information.

Require each item to be quoted, not summarized. A finding of this kind is worth more than ten style
notes: it names a defect that survives every future run.

## 3. Is the produced artifact's edge real?

Three questions, in this order: does the output have a **location and name** (and a resolution chain —
flag → env → config → default — rather than an inlined path)? Does the declared **consumer** actually
read it? Does the consumer want the shape this producer forbids (a plan wants file paths and
signatures; a spec that bans implementation detail cannot satisfy it)?

A declared edge in a graph, a `consumes:` line or an "Output" section is decoration until a consumer
resolves it. This is the cheapest structural finding in any protocol review and the most likely to be
skipped by both lanes in favour of prose critique.

## 4. Name a request that hits three entries

Neighbouring skills are only separated by a request that plausibly matches several of them. Ask for one
such request, which entry wins under the current descriptions, and whether that is right. If one of the
neighbours never mentions the other in its own body, the boundary is one-directional and the mixed case
falls the wrong way.

## 5. What can be deleted whole?

Ask for sections to remove, not to improve: a rules block that restates the body, numbered ids nobody
parses, a "definition of done" that repeats the outcome. A protocol that cannot lose a section is
being defended, not reviewed.

## 6. What is the single most likely-wrong rule, and when does it hurt?

Forced to pick one, reviewers name their real objection. The strongest findings in practice are
absolute rules whose exception is the normal case — "never ask what the repository answers" failing on
where the repository shows what happens **today** and the decision is about the **future**; "every
question carries a path" failing on greenfield work where the honest fact is the absence.

## Grading the findings

Give every finding one of **adopt** (with the sentence to change) / **adapt** / **reject** (with the
reason), and record the rejects — a rejection nobody wrote down returns next round as a fresh finding.
Two lanes reaching the same defect from different evidence is the set worth acting on; two lanes
reaching it from the same paragraph is one finding counted twice.

When the lanes give different numbers for the same knob (a cap of 3–4 against ≤7), check whether they are
answering different questions before compromising: the usual resolution is two orthogonal axes — what to
group per round versus how to order the overflow — not a middle number.
