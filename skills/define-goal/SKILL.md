---
name: define-goal
description: Define ambitious intentions as numbered goal-prompt files, progressing from clear near-term outcomes to provisional longer-term outcomes without planning implementation. Use when the user wants to create or refine goals, turn a large vision into inspectable increments, or refine the next goal from earlier results. Not for task breakdown, implementation planning, execution, or progress tracking.
metadata:
  version: "0.1.47"
  areas: "self-management,software-development,work-management"
  targets: "runtime-agnostic"
  summary: "preserve ambitious intent in numbered goal files, with clear near-term and provisional later outcomes, not implementation plans"
  summary_zh: "把雄心转化为编号 goal 文件，近期清晰、远期可细化，不制定实现步骤"
  kind: "entry"
---

# Define Goal

**Outcome:** Preserve the user's ambition in one or more ordered goal-prompt files that let a downstream agent pursue meaningful outcomes with freedom over implementation and regular opportunities for feedback.

**Done:** Each selected goal has a numbered file or, when writes are unavailable, named file contents. The next goal can be finished and verified within the feedback window and needs no further answers from the user; later goals may be explicitly provisional. Together they preserve the ambition. If even an honest next goal cannot be stated, identify the decisive missing fact, user choice, or reframing needed rather than emitting a misleading queue.

**Safe failure:** When a commitment is too large, narrow the next outcome without shrinking the long-term ambition. Expose uncertainty rather than inventing precision, substituting an easier target, or claiming that elapsed time establishes success.

## Boundary

This skill defines purpose, desired outcomes, credible completion evidence, material bounds, and the order in which outcomes build toward the ambition. An outcome sequence is not an implementation plan: describe what becomes possible, not the steps, architecture, or tools used to make it possible.

If the next outcome's boundaries, acceptance or test seam are still undecided, settle them with
`spec-convergence` first and consume its spec. Ambition and boundaries are two decisions; this skill
owns the first.

This skill writes goal documents. The receiving agent and harness own implementation planning, execution, timing, goal activation, and progress tracking. Do not execute the goals or build a scheduler or lifecycle mechanism.

## Preserve The Ambition

Understand what the user wants to become possible and why it matters. Their current knowledge, feature ideas, and proposed methods are context, not a ceiling on what the agent may achieve. Offer better outcome formulations when useful, distinguishing proposals from commitments the user has made.

Keep an open-ended vision as directional context rather than forcing it into one enormous completion contract. Preserve that direction across the goal files instead of replacing it with only a small first delivery. A goal can end in a changed system, justified knowledge, or a resolved decision, according to the user's purpose.

Ask only about uncertainties that materially change the intended outcome, acceptance, authority, or next commitment, and ask them together as early as possible. Goal runs are long and often unattended, so do not defer a question the user can answer now into a goal or into the receiving agent's run. Establish externally knowable facts proportionately from available evidence rather than making the user supply them. Recommend a formulation or a choice instead of issuing a generic questionnaire. Explicit assumptions can carry non-blocking uncertainty; unknown details of distant goals need not block a useful next goal. When the outcome and acceptance are already clear, ordinary discovery belongs to the receiving agent; missing execution context alone does not justify a preliminary readiness goal.

## Size Goals For Feedback

Use about **12 hours** as the default feedback window, unless the user supplies another: the time in which the receiving agent can finish a goal and show the evidence that verifies it. This is a goal-sizing guide, not an exact estimate, guaranteed deadline, minimum duration, or automatic stop. Completion still depends on the outcome and its evidence.

Use one goal for a bounded, cohesive outcome. Split larger ambitions when the available context indicates a long gap without useful feedback, even when the goals are successive advances toward the same ultimate outcome. Do not invent scope or impose a standard release workflow to justify more goals. Keep separately desired outcomes identifiable rather than replacing them with a status-tracking meta-goal. Mutually exclusive outcomes are candidates for a choice, not successive commitments.

Choose boundaries around meaningful, inspectable advances. Favor early real product use that can grow toward the vision over a large invisible foundation. Later goals may depend on and extend earlier ones; independent cancellation is not required. Preserve user-relevant value while leaving replacement of interim features and implementations open. Database, API, UI, and testing tasks are not separate goals merely because they are different implementation work.

Inspection does not require a UI. Use evidence appropriate to the outcome: working behavior for a service, a usable experience for a product, or findings that resolve real uncertainty for research. A progress report, activity count, or cosmetic demonstration is not a substitute for the promised result.

Judge sizing against the available context, control, and dependencies, counting only the receiving agent's own work, including producing its evidence. Waiting, observation, and other parties' decisions do not count toward the window: waiting alone does not justify extra goals, and splitting cannot shorten it. When the agent's own work cannot plausibly reach a meaningful, verifiable result within the window, expose the mismatch and propose a smaller useful outcome or an explicit exception. Preserve the user's final acceptance conditions rather than silently weakening them to fit the window. A lack of evidence about feasibility is not proof of impossibility.

## Let Detail Follow Evidence

Number the goals in one series, in the recommended order from near to far. In each file, state its prerequisite at the outcome level: the earlier goal whose accepted result it builds on, or none when it can be pursued earlier or in parallel. A goal awaiting external acceptance holds back only the goals that depend on it. The order guides use; it does not freeze the series against later learning or changed priorities.

Make the next goal clear enough for a fresh agent to pursue and for completion to be judged. A goal is ready only when the receiving agent will need nothing more from the user: no open question would change it and no input only the user can supply is missing. A stated default can settle a reversible detail, but not a question about acceptance, authority, or an irreversible effect. Until then, keep it provisional, name what is missing, and do not suggest starting it. Let more distant goals be broader: retain their purpose, intended advance, and the kind of evidence that would establish success, while marking unresolved outcome choices and assumptions as provisional. Do not invent detailed acceptance thresholds or implementation decisions to make every future file look equally ready.

Before activation, refine a provisional goal against earlier results and current priorities, and resize it to the feedback window if needed. When revising files, preserve completed goals and unrelated content. If splitting or reordering changes future filenames, update prerequisite references and report the revised order. Resolve only material user choices; there is no mandatory human approval ceremony between goals. Do not silently change the ultimate purpose to make a later goal easier to satisfy.

## Make Success Credible

Describe the state that distinguishes completion from non-completion, not merely an activity. Preserve user-supplied validators and bounds, including what each bound applies to. Ground concrete acceptance requirements in context or reliable evidence, and distinguish proposed additions from established requirements. Use quantitative thresholds only with a grounded metric, target, and measurement method; otherwise use observable qualitative or binary conditions.

For qualitative judgment or relative improvement, name the relevant audience or acceptance authority and the observable qualities or comparison basis that make its judgment credible. The model's own confidence, arbitrary counts, and unrelated proxy scores are not completion evidence.

Preserve legitimate desired outcomes that depend on other people or external conditions, but do not imply that the agent's work guarantees them. Name the dependency and what would establish acceptance. Offer a more controllable reframe as a choice, not a silent replacement for the user's goal.

When the context shows that acceptance belongs to someone other than the user, or that it depends on an event outside the window, such as a board vote, an outside reviewer, real readers, or the market, end the agent's goal at a verifiable handoff: what the agent must produce or surface for that decision. Make the acceptance itself the next numbered goal, stating the user's acceptance evidence, and mark it as external acceptance: it is recorded when the decision arrives, not run by an agent. Otherwise acceptance is the user's own review of the result: keep it in the same goal, after the run rather than in its Done when section. Do not assume an outside acceptor.

## Write Goal Files

Use the user's destination or an existing project convention; otherwise use `goals/<initiative>/`. Write one Markdown file per selected goal, with sortable numeric prefixes such as `001-<short-name>.md`, `002-<short-name>.md`. Candidates awaiting a user choice are not numbered as a committed series. Read existing files when revising a series and preserve content outside the requested revision.

Each file is a plain-language goal prompt with:

- the intended advance and enough of the larger purpose to orient a fresh agent;
- its prerequisite, or that it has none;
- only material scope, constraints, and assumptions;
- for a ready goal, a **Done when** section that stands alone: the end state, how the agent will show each part of it during its run, the constraints that must hold, and when to stop and report instead. Include only what the run itself can show, keeping user-supplied validators as given and adding no completion gates beyond them; the user's review of the result follows the run. Describe the evidence in outcome terms without assuming an unconfirmed cause or prescribing a reproduction or fix; when the cause matters and is unknown, make establishing it part of the evidence. Ask the agent to stop and report at once if, at the start of the run, something only the user can supply is missing; after that, to take and report reversible defaults, stopping only for irreversible or out-of-bounds decisions; and to end with a report that pairs each item with its evidence;
- for a provisional goal, a provisional basis for acceptance and a clear indication that refinement is needed before activation, naming the unresolved outcome choices or open questions.

Keep the files free of task checklists, implementation plans, and runtime-specific flags or commands; the user writes the goal command that hands a file to the receiving agent. Supply enough relevant context in each file that the next agent does not need the original conversation. Completion may be judged only from what the run shows, so keep the Done when section self-contained and the final report explicit.

Return the actual file paths in numeric order with each goal's prerequisite. Explain that a ready goal can start once its prerequisite is accepted, that goals without one can run earlier or in separate sessions, that provisional goals are refined before use, and that an external-acceptance goal is recorded rather than run. Summarize what each goal makes possible without duplicating every file in chat, and keep every statement about a file consistent with that file. If writes are unavailable or declined, return separately named complete file contents instead. Do not claim files were saved or goals activated unless that actually happened; writing the files does not activate them.
