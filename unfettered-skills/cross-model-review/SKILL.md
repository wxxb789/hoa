---
name: cross-model-review
description: Use when several models review one artifact independently.
version: "0.1.0"
author: Zoe
metadata:
  version: "0.1.1"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  hermes:
    tags: ["review", "second-opinion", "multi-model", "independence"]
    related_skills: ["omp-headless-orchestration", "agent-workflow-harness", "delegated-work-acceptance"]
---

# Cross-model review

Ask N models from different families to review the *same* artifact, then compare. The value is
disagreement; one model asked twice produces agreement, and two lanes that can read each other produce
the same. Independence is a property of the setup, not of the model.

## When to Use

- A design, architecture or harness judgement where being wrong is expensive and the operator wants a
  second opinion from another family.
- Comparing an external project against the operator's own library, where the operator's prior
  conclusions would anchor any single model.

Not for: factual lookups, single-file edits, or anything one lane can settle in a minute.

## Rules

1. **One clean working directory per lane.** Never point the lane at the analysis directory: any prior
   report, note file or project instruction there becomes an anchor and gets paraphrased back as if it
   were the model's own finding.
2. **One core prompt, N copies differing by one line** (report path, model name). Byte-identical core
   text is what makes reports comparable; differences must come from the model, not the wording.
3. **State the fact boundary in the prompt:** absolute allowed directories, forbidden directories (other
   lanes' output, prior analysis, memory/identity files), read-only outside one declared output path.
4. **Require `path:line` for every claim**, with an explicit `(Inference)` tag otherwise. A review with no
   citations is a model opining; verify two or three citations per report against the real files.
5. **Demand a dissent section** — which of the operator's stated constraints is most likely wrong, and
   under what conditions. Unanimous compliance is the least useful output a review can give.
6. **Never feed lane A's report into lane B**, including in a second round. Aggregation happens in the
   orchestrator, not in the lanes.
7. **Do not silently substitute a model.** If a lane dies at the provider, report the raw error and
   offer the replacement; the operator chose the family, not the slot.
8. **Check each recommendation against the repo's own documented anti-patterns before accepting it.**
   A lane reads the code, not the rulebook, so it will confidently propose what the owner already
   banned. When lanes disagree, the repo's own rule breaks the tie — and a lane that never read that
   rule is the one whose other recommendations need re-reading too.
9. **A hosted reviewer's model is not yours to pin.** A GitHub review app (`@codex review`) picks its
   model server-side and does not echo it, so a harness config file (`~/.codex/config.toml`, an
   `opencode.json`) governs only that CLI's local runs — answering "which model reviewed this PR" with a
   local config value is a wrong claim. When a specific model is required, that is a self-built lane
   (`codex exec`, `pi -p --model <id>`) carrying your own prompt, schema and finding format.
10. **Carry a disposition table from the comparison into the plan.** Every item the lanes raised keeps a
   row with its classification (adopt / adapt-before-adopting / reject) and the plan either contains it
   or states the reversal. Re-planning after an audit drops items by default — and a dropped *adopt* is
   indistinguishable from one nobody read, so nobody notices until an auditor diffs the two documents.
   Anything moved from "adopt" to "not in this round" needs a written reason and a place in the
   sequence, not silence.

## Auditing a proposal that already merged other reviews

A plan synthesised from N reviews drifts from them, and the drift is invisible to the person who wrote
the plan. Audit it with the same independence rules, in two phases:

1. **Phase A — independent judgement first.** The auditor reads only the proposal and the repository and
   answers the open decisions itself. No source reviews, no prior analysis.
2. **Phase B — distortion check.** Only after Phase A is written may it read the source reviews, and it
   answers exactly one question: did the proposal misrepresent, over-simplify, or drop them?

Enforce the phase gate in the prompt ("do not read X before part A is written"), not by politeness: a
single-phase prompt returns an echo with citations. Give the auditor the decision list the operator is
waiting on, verbatim, and require one verdict per item plus the condition under which the other answer
wins — "it depends" is a failed answer. Ask what can be **deleted**, and ask for one concrete
counter-example to any mechanical check ("something that passes CI and is still wrong"); those two
questions are what turn an audit into a design change rather than more prose.

Skeleton and grading table: `references/auditing-a-synthesis.md`.

## Reviewing a protocol, skill or checklist

Prose artifacts fail in their own way: a bloated message shape that turns the reader into a rubber
stamp, an agent that can comply and still decide silently, an output edge no consumer resolves. Ask the
six protocol questions (degeneracy, silent decisions, artifact edge, a request that hits three entries,
what can be deleted, the most likely-wrong rule) and grade every finding adopt / adapt / reject.
Recipe: `references/reviewing-a-protocol.md`.

## Verify the fix with your own probe, not the fixer's tests

A review loop has a second half — the fix — and a fix verified by the tests its author wrote is not verified:
test and code came out of the same pass, so they agree by construction. Restate the finding's hostile input
from its own words, drive the public entry point, assert the *exact* number the finding named, then delete the
probe so the tree stays the author's and the gate counts still describe the delivery. Three traps: a
module-level cache (font discovery, config loaders, memoised resolvers) turns an in-process env swap into a
no-op — run that probe in a fresh process; a positive control that never reaches the drawn/observable path
fails for an unrelated reason and reads as a regression; and asserting "findings" instead of the equivalent
direct spelling accepts an under-count.

## Procedure

1. Write the shared prompt: role, fact boundary, evidence bar, required structure (mechanism inventory →
   what the operator's own library already covers → absorb / adapt-before-absorbing / reject with
   reasons → composition design → dissent), length cap, time budget.
2. Create a neutral workspace; per-lane prompt copies; one config overlay per lane if the runner takes
   concurrency settings.
3. Launch all lanes at once as detached runs, never as children of the chat session.
4. Health-probe once after ~2 minutes per lane: is it making turns, is it calling tools, how many
   retries. A lane with rising retries and zero tool calls is a provider failure — see
   `references/omp-lane-mechanics.md` for the probe and the OMP flags.
5. Read every report in full before comparing. Build an item table: recommendation → which lanes raised
   it → verdict. Cross-lane agreement is a candidate, not a conclusion; a lone finding is a hypothesis.
6. Deliver: converged items, the disagreement with both readings, and the substance of the strongest
   dissent. Depth stays in the task directory, conclusions go to chat.

## Pitfalls

- **A provider 5xx on one model group is not a prompt problem.** If a sibling model on the same key
  answers a truncated probe, the alias is valid and the group is down upstream; retries will not fix it.
- **Prompt compliance is not evidence quality.** Two lanes given identical instructions still produce
  different structures; normalize before comparing, and treat a report that ignores the citation bar as
  low-trust however confident it reads.
- **The lane that flatters the operator's plan is the one to distrust.** Check whether it verified the
  claims its agreement depends on.
- **A plan that upgrades its sources' landing spot is the most common synthesis defect.** When every
  lane says "edit the existing skill" and the plan you wrote says "add a new skill", the plan is no
  longer a synthesis — it is a new proposal wearing their agreement. Copy each recommendation's landing
  spot as the source wrote it, and when auditing someone else's synthesis ask for exactly that
  comparison. Two lanes disagreeing is also not consent: a contested item may be recorded as a decision,
  never as a convergence.
- **A probe that swallows its own parse error looks alive.** A lane-watch or review-marker loop written with
  the wrong quoting (Python embedded in a bash heredoc) records nothing each iteration yet runs its full poll
  budget; the first poll must print a real state, and a healthy running lane reads `running` with the new sha,
  not an empty field. Fix the probe on poll 1, never after twenty minutes of waiting.
- **Two lanes giving different numbers for one knob are usually answering two questions.** Group per round
  versus order the overflow, cap versus budget, sample size versus threshold: resolve the axis split before
  compromising on a middle value, or the reconciliation invents a third option neither lane argued for.
- **Cost scales with lanes times effort.** A review needs high thinking, not maximum; and a lane that
  fans out sub-reviewers costs the sum of them, not one pass.
