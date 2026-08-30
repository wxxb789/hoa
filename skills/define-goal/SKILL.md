---
name: define-goal
description: Clarify and stress-test an intention into a meaningful, feasible, and verifiable `/goal` prompt without planning how to achieve it. Use when the user wants to turn a vague idea into a goal, refine or challenge a proposed goal, or narrow an ambition that may be too broad or infeasible. Do not use for implementation planning, task breakdown, execution, or progress management.
---

<!-- Originally ported from openai/skills@b0401f07213a66414d84a65cb50c1d226f99485a; redesigned for runtime-agnostic /goal output and modified to add HOA catalog metadata. See LICENSE.txt. -->
<!-- index: areas=self-management,software-development,work-management; targets=runtime-agnostic -->

# Define Goal

**Outcome:** Turn the user's intention into one ready-to-run `/goal` invocation whose prompt defines a meaningful end state, credible completion evidence, and material bounds without prescribing implementation.

**Done:** The response either contains one ready-to-run `/goal` invocation with no unresolved issue that could materially change its outcome, evidence, bounds, or feasibility, or withholds the invocation and identifies the smallest current frontier of decisions, facts, or reframes needed to make an honest goal possible.

**Safe failure:** Do not manufacture precision or emit `/goal` when no honest completion contract can yet be stated. Name the decisive ambiguity, contradiction, or feasibility problem and help the user resolve it first.

## Boundary

This skill owns the goal space: the desired change, why it matters when that affects the target, credible evidence of success, material constraints, and whether the result is plausibly achievable.

It does not own the solution space: methods, architecture, tools, steps, task breakdown, sequencing, milestones, execution, or progress tracking. Discuss a means only when it materially changes feasibility or the acceptable bounds, and record the resulting constraint rather than an implementation choice.

This skill produces the `/goal` invocation. The `/goal` command owns persistence, planning, execution, and lifecycle. Do not call, emulate, or prescribe runtime-specific goal tools.

## Clarify The Goal

Express the state of the world or knowledge that should hold at completion, not merely an activity. A research, diagnostic, or decision goal may end in justified knowledge or a resolved decision rather than a changed external system.

Distinguish a goal from a vision. A goal has a finishable state; a vision is directional and open-ended. When the input is a vision, say so and help the user choose a bounded goal that serves it without inventing an implementation plan.

Surface assumptions whose failure would make the goal stop serving the user's intent, become misleading, remain unverifiable, or prove infeasible. Challenge proxy outcomes, unsupported confidence, contradictory constraints, and ambitions outside the user's plausible control. Preserve the user's underlying intent while correcting the proposed target.

Use quantitative thresholds only when the metric, target, and measurement method are grounded in the user's context or reliable evidence. Otherwise use an observable binary or qualitative acceptance condition. A metric is evidence of the desired outcome, not a substitute for it.

## Resolve Material Uncertainty

Resolve externally knowable facts from available context and tools when they materially affect the goal. Ask the user for preferences, priorities, commitments, and tradeoffs that only they can decide; do not make them supply facts the agent can reasonably obtain.

Present together the user decisions whose prerequisites are already settled. Frame each as concrete choices or candidate goal formulations, recommend an answer, and state what the choice changes in the goal; do not substitute a generic questionnaire or fill-in-the-blank intake form for that judgment. Do not ask downstream questions before the decisions they depend on, and stop questioning once the remaining uncertainty cannot materially change the goal contract.

When the ambiguity represents genuinely different desired outcomes, offer a small set of materially distinct candidate goals, explain the tradeoff at the goal level, and recommend one. Do not brainstorm competing implementations.

## Check Feasibility

Judge feasibility against the stated horizon, constraints, available control, and critical dependencies. Treat an unsupported claim of impossibility as another uncertainty to resolve, not as a verdict.

When the goal is feasible only under material assumptions, expose those assumptions and include them as bounds or conditions. When feasibility remains unknown, either resolve the missing fact or ask whether the user wants an epistemic goal that determines feasibility.

When the goal is not feasible as stated, do not polish it into false precision. Explain the decisive mismatch and offer the closest meaningful reframing that preserves the underlying intent. Do not turn the reframe into an action plan.

## Compile The Goal Prompt

Compile one cohesive, plain-language goal payload. On a runtime that accepts `/goal`, begin the final invocation with `/goal ` followed by that payload. When the runtime does not accept `/goal`, return the payload for its native goal intake without claiming it was submitted or executed. Include:

- the desired end state
- the evidence that will distinguish completion from non-completion
- only the scope, constraints, exclusions, or critical assumptions that materially limit acceptable outcomes

Keep implementation choices open. Include a deadline, threshold, validator, command, or named artifact only when it is supplied by the user or verified as authoritative; never invent one to make the goal look concrete.

Once the goal is ready, return the invocation or portable payload as the final substantive content without analysis, alternatives, a plan, or runtime-specific flags.
