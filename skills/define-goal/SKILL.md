---
name: define-goal
description: Define ambitious intentions as numbered goal-prompt files, progressing from clear near-term outcomes to provisional longer-term outcomes without planning implementation. Use when the user wants to create or refine goals, turn a large vision into inspectable increments, or refine the next goal from earlier results. Not for task breakdown, implementation planning, execution, or progress tracking.
---

<!-- index: areas=self-management,software-development,work-management; targets=runtime-agnostic; version=2.0.0 -->

# Define Goal

**Outcome:** Preserve the user's ambition in one or more ordered goal-prompt files that let a downstream agent pursue meaningful outcomes with freedom over implementation and regular opportunities for feedback.

**Done:** Each selected goal has a numbered file or, when writes are unavailable, named file contents. The next goal is bounded and verifiable; later goals may be explicitly provisional. Together they preserve the ambition. If even an honest next goal cannot be stated, identify the decisive missing fact, user choice, or reframing needed rather than emitting a misleading queue.

**Safe failure:** When a commitment is too large, narrow the next outcome without shrinking the long-term ambition. Expose uncertainty rather than inventing precision, substituting an easier target, or claiming that elapsed time establishes success.

## Boundary

This skill defines purpose, desired outcomes, credible completion evidence, material bounds, and the order in which outcomes build toward the ambition. An outcome sequence is not an implementation plan: describe what becomes possible, not the steps, architecture, or tools used to make it possible.

This skill writes goal documents. The receiving agent and harness own implementation planning, execution, timing, goal activation, and progress tracking. Do not execute the goals or build a scheduler or lifecycle mechanism.

## Preserve The Ambition

Understand what the user wants to become possible and why it matters. Their current knowledge, feature ideas, and proposed methods are context, not a ceiling on what the agent may achieve. Offer better outcome formulations when useful, distinguishing proposals from commitments the user has made.

Keep an open-ended vision as directional context rather than forcing it into one enormous completion contract. Preserve that direction across the goal files instead of replacing it with only a small first delivery. A goal can end in a changed system, justified knowledge, or a resolved decision, according to the user's purpose.

Ask only about uncertainties that materially change the intended outcome, acceptance, authority, or next commitment. Establish externally knowable facts proportionately from available evidence rather than making the user supply them. Recommend a formulation or a choice instead of issuing a generic questionnaire. Explicit assumptions can carry non-blocking uncertainty; unknown details of distant goals need not block a useful next goal. When the outcome and acceptance are already clear, ordinary discovery belongs to the receiving agent; missing execution context alone does not justify a preliminary readiness goal.

## Size Goals For Feedback

Use about **12 hours** as the default target time to an inspectable result, unless the user supplies another feedback window. This is a goal-sizing guide, not an exact estimate, guaranteed deadline, minimum duration, or automatic stop. Completion still depends on the outcome and its evidence.

Use one goal for a bounded, cohesive outcome. Split larger ambitions when the available context indicates a long gap without useful feedback, even when the goals are successive advances toward the same ultimate outcome. Do not invent scope or impose a standard release workflow to justify more goals. Keep separately desired outcomes identifiable rather than replacing them with a status-tracking meta-goal. Mutually exclusive outcomes are candidates for a choice, not successive commitments.

Choose boundaries around meaningful, inspectable advances. Favor early real product use that can grow toward the vision over a large invisible foundation. Later goals may depend on and extend earlier ones; independent cancellation is not required. Preserve user-relevant value while leaving replacement of interim features and implementations open. Database, API, UI, and testing tasks are not separate goals merely because they are different implementation work.

Inspection does not require a UI. Use evidence appropriate to the outcome: working behavior for a service, a usable experience for a product, or findings that resolve real uncertainty for research. A progress report, activity count, or cosmetic demonstration is not a substitute for the promised result.

Judge sizing against the available context, control, and dependencies. When a meaningful result cannot plausibly fit the window, expose the mismatch and propose a smaller useful outcome or an explicit exception. Separate agent work from external waiting or observation: waiting alone does not justify extra goals, and splitting cannot shorten it. Preserve the user's final acceptance conditions rather than silently weakening them to fit the window. A lack of evidence about feasibility is not proof of impossibility.

## Let Detail Follow Evidence

Number the goals in their proposed realization order, from near to far. Explain material prerequisites at the outcome level. This order guides sequential use; it does not freeze the whole series against later learning or changed priorities.

Make the next goal clear enough for a fresh agent to pursue and for completion to be judged. Let more distant goals be broader: retain their purpose, intended advance, and the kind of evidence that would establish success, while marking unresolved outcome choices and assumptions as provisional. Do not invent detailed acceptance thresholds or implementation decisions to make every future file look equally ready.

Before activation, refine a provisional goal against earlier results and current priorities, and resize it to the feedback window if needed. When revising files, preserve completed goals and unrelated content. If splitting or reordering changes future filenames, report the revised order. Resolve only material user choices; there is no mandatory human approval ceremony between goals. Do not silently change the ultimate purpose to make a later goal easier to satisfy.

## Make Success Credible

Describe the state that distinguishes completion from non-completion, not merely an activity. Preserve user-supplied validators and bounds, including what each bound applies to. Ground concrete acceptance requirements in context or reliable evidence, and distinguish proposed additions from established requirements. Use quantitative thresholds only with a grounded metric, target, and measurement method; otherwise use observable qualitative or binary conditions.

For qualitative judgment or relative improvement, name the relevant audience or acceptance authority and the observable qualities or comparison basis that make its judgment credible. The model's own confidence, arbitrary counts, and unrelated proxy scores are not completion evidence.

Preserve legitimate desired outcomes that depend on other people or external conditions, but do not imply that the agent's work guarantees them. Name the dependency and what would establish acceptance. Offer a more controllable reframe as a choice, not a silent replacement for the user's goal.

## Write Goal Files

Use the user's destination or an existing project convention; otherwise use `goals/<initiative>/`. Write one Markdown file per selected goal, with sortable numeric prefixes such as `001-<short-name>.md`, `002-<short-name>.md`. Candidates awaiting a user choice are not numbered as a committed series. Read existing files when revising a series and preserve content outside the requested revision.

Each file is a plain-language goal prompt with:

- the intended advance and enough of the larger purpose to orient a fresh agent;
- completion evidence, or a provisional basis for acceptance when the goal is distant;
- only material scope, constraints, prerequisites, and assumptions;
- a clear indication when refinement is needed before activation, with the unresolved outcome choices identified.

Keep the files free of task checklists, implementation plans, and runtime-specific flags. Supply enough relevant context in each file that the next agent does not need the original conversation. A ready file's contents can be supplied to the receiving harness's native goal intake, including `/goal` where supported; do not assume the command accepts a file path or multiple active goals.

Return the actual file paths in numeric order and explain that the user should use them one at a time, refining provisional goals before use and moving on after the preceding goal completes or the user revises the sequence. Summarize what each goal makes possible without duplicating every file in chat. If writes are unavailable or declined, return separately named complete file contents instead. Do not claim files were saved or goals activated unless that actually happened; writing the files does not activate them.
