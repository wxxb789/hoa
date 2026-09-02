---
name: define-goal
description: Define and stress-test an intention as one cohesive, feasible, verifiable goal or the smallest sufficient set of independently meaningful goals, without planning implementation. Use when the user wants to create or refine a goal, turn a vision into bounded outcomes, or separate independently finishable outcomes within an initiative. Do not use for task breakdown, implementation planning, execution, or progress management.
---

# Define Goal

**Outcome:** Turn the user's intention into either one cohesive goal payload or the smallest sufficient set of separately addressable goal payloads, each defining a meaningful end state, credible completion evidence, and material bounds without prescribing implementation.

**Done:** The response contains one ready goal payload, contains the smallest sufficient goal set whose members each have an independently meaningful and verifiable completion judgment, or withholds the output and identifies the smallest current frontier of decisions, facts, or reframes needed to state an honest goal structure. Material uncertainty is resolved, represented as an explicit assumption or condition when that preserves the user's intent, or returned as part of the blocking frontier.

**Safe failure:** Do not manufacture precision, force independently meaningful outcomes into one completion contract, or turn solution structure into goals. When no honest goal structure can yet be stated, name the decisive ambiguity, contradiction, or feasibility problem and help the user resolve it first.

## Boundary

This skill owns the goal space: the desired change, why it matters when that affects the target, credible evidence of success, material constraints, and whether the result is plausibly achievable.

It does not own the solution space: methods, architecture, tools, steps, task breakdown, sequencing, milestones, execution, or progress tracking. Discuss a means only when it materially changes feasibility or the acceptable bounds, and record the resulting constraint rather than an implementation choice.

This skill produces goal payloads. The receiving runtime or goal mechanism owns persistence, planning, execution, and lifecycle. Do not call, emulate, or prescribe runtime-specific goal tools.

## Clarify The Goal

Express the state of the world or knowledge that should hold at completion, not merely an activity. A research, diagnostic, or decision goal may end in justified knowledge or a resolved decision rather than a changed external system.

Distinguish a goal from a vision. A goal has a finishable state; a vision is directional and open-ended. When the input is a vision, say so and help the user choose a bounded goal structure that serves it, applying the cardinality rule below without inventing an implementation plan.

Surface assumptions whose failure would make the goal stop serving the user's intent, become misleading, remain unverifiable, or prove infeasible. Challenge proxy outcomes, unsupported confidence, contradictory constraints, and any claim that in-scope work guarantees an outcome materially outside the user's control. Preserve the user's underlying intent while correcting the proposed target.

Use quantitative thresholds only when the metric, target, and measurement method are grounded in the user's context or reliable evidence. Otherwise use an observable binary or qualitative acceptance condition. A metric is evidence of the desired outcome, not a substitute for it.

When completion depends on qualitative judgment or relative improvement, identify the relevant audience, reviewer, or decision authority and the context, observable qualities, or comparison basis that makes the judgment credible. Do not use the model's own confidence, arbitrary counts, or an unrelated proxy as completion evidence.

## Choose Goal Cardinality

Prefer one goal when the user's intended success has one completion judgment, even when that judgment requires several necessary conditions or pieces of evidence.

Use the smallest sufficient goal set when the intention contains outcomes whose completion, deferral, or cancellation can be judged independently. Each member must have its own end state, completion evidence, and material bounds, and the set must preserve the user's intended outcomes without overlap or silent omission.

Do not collapse independently desired outcomes into one meta-goal to decide, track, or report their statuses. Each outcome remains its own goal unless the user's intended end state is the portfolio decision itself.

Size, number of workstreams, architecture layers, phases, milestones, or execution order do not by themselves justify multiple goals. Do not turn implementation structure into goal structure.

Do not present mutually exclusive outcomes as a goal set. When only one outcome should be chosen, offer candidate goal formulations or define an epistemic goal whose end state is the justified decision.

Record a cross-goal prerequisite only when it materially changes whether a goal can honestly be completed; leave execution ordering to planning.

## Resolve Material Uncertainty

Resolve externally knowable facts from available context and tools only when they materially affect the goal contract and can be established proportionately from authoritative evidence. Otherwise expose the uncertainty as an assumption, condition, or feasibility question. Ask the user for preferences, priorities, commitments, and tradeoffs that only they can decide; do not make them supply facts the agent can reasonably obtain.

Present together the user decisions whose prerequisites are already settled. Frame each as concrete choices or candidate goal formulations, recommend an answer, and state what the choice changes in the goal; do not substitute a generic questionnaire or fill-in-the-blank intake form for that judgment. Do not ask downstream questions before the decisions they depend on, and stop questioning once the remaining uncertainty cannot materially change the goal contract.

When the ambiguity prevents choosing between materially different goal structures, offer a small set of candidate formulations, explain the tradeoff at the goal level, and recommend one. Do not brainstorm competing implementations.

## Check Feasibility

Judge feasibility against the stated horizon, constraints, available control, and critical dependencies. Treat an unsupported claim of impossibility as another uncertainty to resolve, not as a verdict.

A desired end state may depend on decisions or responses outside the user's control. Preserve that intended outcome, but do not imply that in-scope work guarantees it. State the acceptance authority or external condition that makes completion observable, and offer a more controllable reframe only as a choice when the original commitment cannot be made honestly.

When the goal is feasible only under material assumptions, expose those assumptions and include them as bounds or conditions. When feasibility remains unknown, either resolve the missing fact or ask whether the user wants an epistemic goal that determines feasibility.

When the goal is not feasible as stated, do not polish it into false precision. Explain the decisive mismatch and offer the closest meaningful reframing that preserves the underlying intent. Do not turn the reframe into an action plan.

## Compile Goal Payloads

Compile each ready goal as a cohesive, plain-language payload. On a runtime that accepts `/goal`, render each payload as a separate `/goal ` invocation. When the runtime does not accept `/goal`, return separately addressable payloads for its native goal intake. Do not claim that a payload was submitted, executed, or activated, and do not imply that a goal set can be activated atomically. Each payload includes:

- the desired end state
- the evidence that will distinguish completion from non-completion
- only the scope, constraints, exclusions, or critical assumptions that materially limit acceptable outcomes

Keep implementation choices open. Use only evaluation details and concrete bounds supplied by the user or grounded in authoritative evidence; never invent specificity merely to make the goal look concrete. A deliverable directly implied by the user's intent may be stated without prescribing how to produce it.

Once the goal structure is ready, return the payloads plus only the labels needed to distinguish a goal set from alternatives or state a material prerequisite. Do not append analysis, an implementation plan, or runtime-specific flags.
