# Corpus findings and escalation

Read when a delivery makes a claim about a corpus or graph, needs report
corrections, or must be sent back to its write owner. Perform the applicable
[delivery checks](delivery-checks.md) before routing anything.

## Judge a corpus or graph finding on its mechanism

When the delivered finding is about a knowledge corpus, three of these decide most cases:

- **Duplicates vs a missing hub.** Before accepting "page A duplicates page B": compare sizes (4:1 is a
  hub and a summary, not a duplicate), count inbound **and** outbound links on both, then check whether
  the whole sibling family is unlinked too. A family with no hub looks duplicated, and merging two
  orphans produces a bigger orphan. The cheapest fix is the link that was never made.
- **Fields with no writer.** Before accepting "N pages lack field X", grep every script for the field.
  All hits read, none write ⇒ the field has no write path, its values are backfill, and every rule
  keyed on it can never fire. Report that as the defect; a page-count of missing values reads as
  routine hygiene and gets deprioritised forever.
- **Coverage declared by a fixed type list.** When a catalog enumerates only legacy types, new canonical
  types are counted in totals yet listed nowhere. Test empirically: for each page of the new types, does
  its slug appear in the generated index? Report `0 of N`, not the summary counts.

## Correct the deliverable's own report when it is imprecise

A handoff report becomes next month's diff baseline, so its errors are future work: wrong denominator,
an unresolvable citation, an understated population. Send them back as numbered corrections with the
correct value already supplied — the sender fixes its own file, and you keep the ruling on the
substance.

Before closing a revised handoff, compare it with the latest operator/reviewer ruling, not only the
earlier correction request. Designate one final decision artifact and explicitly supersede conflicting
draft options, counts and approval manifests; an old draft must not become an execution payload. Label
static coverage, design acceptance, implementation, payload effects, scheduled-worker proof and
delivery proof separately — a passing static gate proves neither deployment nor real behavior.

## Send a rejected delivery or out-of-scope defect to its owner

Use this playbook when you cannot repair the affected surface yourself. Check the claim as above
before routing it; do not expand either agent's authority.

1. Map the affected paths to their write owner and identify who can authorize landing. Check for
   scheduled publication before touching a shared tree: a sweep can pick up unrelated in-flight
   work. Re-read the live paths before any authorized apply.
2. Reproduce with the reporter's exact command, tool binary, PATH order, cwd and relevant
   environment. Use the project's own tool and capture the command's exit code before piping
   output. Resolve paths from the tree, not masked logs. Use an isolated copy with equivalent
   dependency resolution if a probe writes; in-place probes and CI reruns need explicit authority.
   Read the failed step's log to distinguish infrastructure from code; if authorized, rerun only
   the failed job and retain both results.
3. Give the write owner the exact paths, exclusions, reproduction and runnable acceptance check.
   Check sibling call sites; on a second same-class defect, require an invariant, a corpus with
   controls, and before/after evidence. Route generated output fixes to the generator.
4. Ask the landing owner for one scoped decision, with your recommendation, rollback unit and
   cost of waiting. Stop when only authorization remains. Re-verify a revised delivery and any
   automated review on the exact candidate before accepting; approval of a prior head is stale.

## Pitfalls

- Fixing the finding yourself because it is two lines. The sender owns the path; a fix from the wrong
  surface is an unaccounted write, and the next audit reports it as one.
- Escalating a reversible house-convention question to the operator and calling it a decision item.
