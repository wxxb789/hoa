# Auditing a synthesis

Use when a plan, proposal or architecture doc was assembled from several independent reviews (or from
one long analysis) and someone is about to act on it. The question is not "is this well written" but
"does it actually hold the conclusions it claims to hold, and are its open decisions answerable".

## Prompt skeleton

```text
You are auditing a proposal that another agent synthesised. Judge whether it is right, not whether it
is coherent. You will work in two phases and you must not reorder them.

INPUT A (always): the proposal at <path>, and the repository at <path> for verification.
INPUT B (phase B only): the source reviews / prior analysis the proposal claims to summarise.

PHASE A — before reading INPUT B
- Answer the items the operator must decide, one verdict each, no "it depends".
  For each: the decision, the evidence (path:line), and the condition under which the other
  answer would be better.
- Test the proposal's mechanical checks: give one concrete case that would pass them and still be
  wrong. If none exists, say so and name what the check does cover.
- Name the single claim you disagree with most, and the conditions under which it would hurt.
- Name what could be deleted without losing a capability.

PHASE B — only now read INPUT B
- Did the proposal misrepresent, over-simplify, or silently drop the sources?
- Was a contested item recorded as agreement?
- Was a source's prescribed landing spot changed ("edit skill X" → "add skill Y")?

OUTPUT: phase A, then phase B, then a list of required edits. Every judgement carries path:line or a
quoted line from the proposal; anything else is tagged (Inference).
Budget: <n> minutes. End with DONE <report path>.
```

## Why the phase gate is the whole trick

An auditor that reads the sources first grades the proposal against them and inherits their framing; an
auditor that reads the proposal and the code first has to form a position, and only then can notice that
the proposal disagrees with its own sources. The gate belongs in the prompt as an explicit prohibition,
because otherwise the model reads everything at once and produces a flattering summary.

## Grading the audit before acting on it

- **Citations:** verify two or three `path:line` claims against the real files. An audit that quotes
  line numbers is falsifiable; one that does not is an opinion with formatting.
- **Verdicts, not surveys:** every decision item must end in a choice. "Depends on context" means the
  auditor did not do the work, and the item stays open.
- **Deletions:** an audit with only additions is growing the candidate, not auditing it.
- **Counter-example quality:** a passing-CI-but-wrong case is the only proof a mechanical check is
  weak. If it cannot produce one, the check may be adequate — or the auditor did not try.
- **Its own overreach:** a phrase like "the sources explicitly forbid X" needs the quote. Auditors
  overstate dissent into prohibition; soften the record, keep the finding.

## Distortions this catches

| Symptom in the proposal | What it usually means |
|---|---|
| "New component X" where every source said "extend existing Y" | The synthesiser preferred a cleaner story to the sources' landed conclusion |
| An item the sources marked accepted is missing from the plan | Silent drop during compression; re-add or record the rejection |
| One lane's recommendation presented as "both reviews agree" | A contested item dressed as consensus |
| A check described as enforced but nothing runs it | Mechanism replaced by prose; verify what CI actually executes |
| A number, count or tier band with no origin | Carried over from an earlier draft of the tree |

## After the audit

Record the accepted corrections in the proposal itself (a dated revision section, or edit the section
that was wrong) before implementation starts, and carry the one or two changes that alter the *order*
of work into the plan. An audit whose findings live only in the chat transcript is lost by the next
session.
