---
name: hoa-skill-work
description: >-
  Build a complete skill around a defined capability, or evolve an existing
  skill from a concrete failure or improvement target. Use when the user asks
  to create or change a skill. Use hoa-skill-review for read-only audits and
  candidate-output judgments; use hoa-introspect-distill for recurring-work
  findings that need qualification and item approval, when available.
---

<!-- index: areas=software-development,work-management,self-management; targets=runtime-agnostic; version=1.0.0 -->

# hoa-skill-work

## Outcome

Create or evolve the requested complete, installable skill package or smallest
sufficient set of packages that produces the user's requested capabilities.
Keep capabilities in one package when they share an activation boundary and
completion contract; split only when separately consumable outcomes need
independent activation or lifecycle, not merely because they use multiple
steps or mechanisms. Each package's next consumer is the person or runtime
invoking it. Work is done when every package expresses a clear result and
activation boundary, all referenced files and required integrations exist,
the change has been validated to the level its risk and available capabilities
allow, and the user receives a truthful change, provenance, validation, and
limits summary.

## Choose the work path

- For a user-defined capability with a direct request to create a skill or
  justified set of skills, read [the creation protocol](references/create.md)
  before writing.
- For an existing skill with a concrete failure or improvement target, read
  [the evolution protocol](references/evolve.md) before editing.
- Read [the evaluation protocol](references/evaluate.md) for either path before
  assessing behavior or making a validation claim.

First find the current owner of the capability and inspect the target
repository's skill layout, instructions, and nearby examples. If an existing
skill already owns the outcome, avoid duplicating it: extend that owner only
when it matches the user's target, otherwise make the distinction explicit.

A direct request to create or evolve a skill authorizes the local edits needed
for that skill and its required repository integration; it does not require an
extra per-item approval token. Follow any approval gate imposed by the host,
user, or project. Stop for confirmation only when a necessary action exceeds
that authority, such as an external or destructive change, or when only the
user can supply a material decision.

A recurring-work finding by itself is evidence, not authorization to create an
asset. When the request is to qualify a pattern or seek item-specific approval,
route to the optional `hoa-introspect-distill` skill if installed. When the user
directly asks to create from that finding, use the creation path and label the
basis accurately; do not claim an audit or history analysis that did not occur.
If qualification is the only request and that sibling is unavailable, leave
files unchanged and state that the route is unavailable. This skill's direct
create and evolve paths do not depend on either sibling.

If the task is only to audit a skill or judge supplied outputs without changing
the skill, use the optional `hoa-skill-review` route when available. This skill
can still proceed without it when the user requests in-scope creation or edits.
If review is the only request and the sibling is unavailable, do not mutate the
skill; state that the review-only route is unavailable.

## Complete and report

Finish the requested skill rather than leaving a scaffold. If a required
capability, source, or host is unavailable, complete the reachable work and
name the exact blocker. Do not present a design review, a parse check, or an
unavailable-host simulation as proof of behavior.

Report the changed skill path, the behavior changed, the reason for any removed
mandate and its provenance result, validation actually performed, and any
unverified host or behavior. Keep the report specific enough for the user to
distinguish an implemented result from a blocked or untested claim.

## Provenance

The upstream creator workflow adapts Anthropic's public
[`skill-creator`](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md).
The evidence-led editing and portability principles adapt the public Compound
Engineering Plugin's [`ce-skill-work`](https://github.com/EveryInc/compound-engineering-plugin/blob/main/.agents/skills/ce-skill-work/SKILL.md)
and its authoritative
[`portable-agent-skill-authoring.md`](https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/solutions/skill-design/portable-agent-skill-authoring.md).
Those CE principles are repository-maintained guidance. The creation and
evolution methods here are not presented as work observed in a prior audit.
