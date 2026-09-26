# Create a skill from a defined capability

Use this path only when the user has asked for a skill, or another applicable
instruction grants that authority. Start by finding the capability's current
owner and the target repository's packaging rules; inspect relevant local
skills, instructions, indexes, tests, and install metadata rather than assuming
a familiar plugin layout.

## Set the outcome before the mechanism

Write the intended skill's contract before choosing tools or prescribing a
workflow. Establish:

- the result a user can observe;
- who or what consumes it next;
- what evidence distinguishes done from not done;
- the work conditions that should activate it and the nearest condition that
  should not; and
- any material boundary or safe failure behavior that changes the result.

Choose the smallest sufficient number of skill packages. Keep one package when
the requested outcomes share an activation boundary and completion contract.
Split independently consumable outcomes only when they need distinct
activation or lifecycle; do not split merely to separate steps or mechanisms.
If a split materially changes the requested deliverable, make the distinction
and its effect explicit; ask only when a user preference determines whether
to split.

Use facts already in the request or repository. Ask only for a decision that
cannot be derived and would change the skill's outcome, authority, or scope.
Treat a user description as `user-provided` evidence. Do not imply that a
recurring pattern was found in history unless the relevant history was actually
examined.

If an existing skill owns the same outcome, avoid a second owner. Extend it
when the request fits; when the user needs a separate skill, state its
distinct result or activation boundary. If that distinction depends on a
material user choice, resolve that choice before creating a competing package.

## Package for the actual target

Follow the target repository's active instructions and existing packaging
conventions. Put always-needed outcome, activation, authority, and completion
rules in `SKILL.md`; move conditional procedures into one-level references
with a clear read condition. Add scripts, tests, metadata, and inventory changes
only when the skill's behavior or the target repository calls for them. Use the
target's native test and validation commands rather than assuming a particular
runtime, plugin, or package manager.

State capabilities and observable behavior before naming tools. Mention a host
or dependency as required only when the desired behavior truly needs it, and
describe what remains unproved when it is absent. Keep the package complete:
every referenced path, promised workflow, and required output contract must
exist, and the description must distinguish real activation conditions from
nearby work it does not own.

## Finish the creation

Read the evaluation protocol and test a fresh-context main path and the nearest
meaningful adjacent-negative path. Test model-invoked activation in a fresh
host without manually injecting or naming the skill; a forced invocation tests
execution, not discovery. When the host also exposes direct invocation, test
that path separately. Include the next-consumer contract when the skill hands
off a structured result.

Compare against a no-skill baseline when it helps establish that the skill
improves the requested result. Grade the user's observable outcome, not whether
the agent repeats the skill's instructions. Report the package path, the
capability and activation it now serves, any local integration performed,
validation evidence, and limitations. If the environment cannot execute a
behavior check, say so instead of leaving a placeholder or claiming proof.
State the basis used to define the capability, such as direct user input,
inspected examples, observed history, or cited requirements; do not attribute
the skill's behavior to sources that were not consulted.
