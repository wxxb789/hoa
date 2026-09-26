---
name: hoa-skill-review
description: >-
  Evidence-ranks skill behavior against its intended outcome and next consumer
  without changing the subject. Use when auditing a skill or reviewing a changed
  skill block. Use when candidate skill replies need judgment against task requirements.
  Use hoa-skill-work for requested skill creation or evolution; use
  hoa-introspect-distill for recurring-work candidates considered for distillation.
---

<!-- index: areas=software-development,work-management,self-management; targets=runtime-agnostic; version=1.0.0 -->

# hoa-skill-review

**Outcome:** Give the skill author or output decision-maker an evidence-ranked assessment of whether the intended behavior works for its next consumer, and the smallest supported decisions to make.

**Done:** The relevant contract and its reachable consumer path have been examined in proportion to the request; every finding meets its evidence floor; and the report separates paths actually verified from those not verified.

**Safe failure:** When a source, consumer, host, candidate context, or independent judge is unavailable, identify the exact limit and narrow the conclusion. Do not invent evidence, grade an unobservable result, claim an unrun behavior, or edit the reviewed subject.

## Boundary and review path

This is a read-only audit, change review, and output-judging skill. Inspect the subject, relevant references, fixtures, and consumer contracts. Non-writing checks or isolated prompts are useful only when their effects are known; do not modify the reviewed asset or its environment.

Start with the user's question and the smallest relevant boundary. For a changed block, inspect its diff, enough surrounding instructions to understand its contract, and the tests or fixtures that exercise that contract. Trace the relevant output into its next consumer when the finding depends on interpretation, parsing, activation, or handoff. For a whole-skill audit, inspect the main instructions and only the references and consumers reached by the behavior under review. Expand beyond that boundary only when evidence points to another dependency; a named diff does not require a full-repository audit.

Scale the review to the claim and consequence. Start with the target's contract and affected path; expand to consumers, fixtures, or real execution when the claim depends on them or a failure would be material. Before calling a rule missing or redundant, trace what it changes, account for the runtime and harness that may mask behavior, and diagnose the gap before prescribing a fix. A hypothetical already decided by a stated condition is not a finding.

Check what evidence actually demonstrates. A fixture may assert an intended rule without exercising its runtime. A forced skill invocation tests its body, not automatic activation. A mock or prompt simulation tests only the simulated interaction, not a real consumer, host, tool call, or protocol transition. Identify harness assumptions that could bake in the expected answer or omit the relevant context.

When behavior cannot be settled from available artifacts, or when candidate replies need grading, read [behavioral evaluation](references/evaluate.md). Static review alone is sufficient when it establishes the claim and consumer consequence without an execution-dependent assumption.

## Findings

Classify each finding by its evidence, not by how plausible it sounds. Order findings within each class by user or consumer impact.

- **Change** — A demonstrated gap. Cite a reproduced failure or the exact path that necessarily fails, explain the resulting user or consumer consequence, identify the owning layer, and state the smallest condition-based correction. Static evidence supports this class only when the failure follows necessarily from the inspected path.
- **Verify** — A concrete risk that could change the conclusion but still needs a named reproduction or trace. State what is uncertain and the specific check that would resolve it; do not prescribe a fix yet.
- **Consider** — An unproved improvement. Explain its plausible value and why the evidence does not establish a defect or required change.

Do not turn a missing observation into a Change. If the necessary path cannot be reproduced or shown to fail, classify it as Verify. Do not report an enhancement as a defect merely because another design is possible.

## Report

Return the conclusion, the scope actually inspected, and findings under Change, Verify, and Consider as applicable. For each item, include the affected file/block or candidate, the evidence, and the consequence; a Change also needs its owner and smallest condition-based fix. Keep the rationale complete enough for a separate author to act without reconstructing unstated assumptions.

List **Verified paths** and **Unverified paths** separately. A deterministic static trace may verify that an inspected path necessarily fails; label it **statically established**, not runtime-exercised. Reserve **runtime-verified** for an observed run. Name the host, consumer, fixture, simulation, or static trace and make its evidence boundary explicit. Put unavailable hosts, unexecuted triggers, mocked boundaries, ambiguous candidate contexts, and runtime or consumer behavior conclusions based only on static inspection under Unverified paths. Never imply that a simulation proves automatic activation or real downstream behavior.

## Optional routes

Use `hoa-skill-work` when the user requests skill creation or evolution; this review does not acquire write authority from that handoff. Use `hoa-introspect-distill` when the user wants recurring-work candidates assessed for distillation; its own process determines whether a candidate is approved for creation. These routes are optional; if unavailable, finish the review within this skill's boundary and report any resulting limit.

## Provenance

The portable package and progressive-disclosure conventions follow the [Agent Skills specification](https://agentskills.io/specification). The evidence-based Change, Verify, and Consider findings and risk-scaled diagnose-before-prescribing method adapt the public [CE Skill Work review guidance](https://github.com/EveryInc/compound-engineering-plugin/blob/main/.agents/skills/ce-skill-work/references/review-skill.md). The evaluation discipline adapts the public [Anthropic skill-creator evaluation guidance](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md); this package is an independent adaptation of those principles.
