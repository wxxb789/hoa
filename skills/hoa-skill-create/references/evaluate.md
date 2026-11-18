# Evaluate skill behavior proportionally

First classify whether the change can alter behavior. For a mechanical-only
change, such as a typo or path/metadata correction, use a deterministic check
to prove the correction and rule out behavior impact; record that behavior
evaluation was skipped and why. If a path or metadata change can affect
activation, loading, routing, or runtime behavior, use the behavior-evaluation
path instead.

For any behavior-bearing change, evaluate the user-visible behavior it intends
to change. Before running cases, write down a rubric with the expected result,
unacceptable outcomes, and any adjacent behavior that must remain unchanged.
Derive it from the request and real consumer contract, not from the
implementation's wording.

## Make a fair comparison

For a behavior-bearing evolution, snapshot the old skill before editing. Run
old and revised versions in equivalent fresh contexts with the same task,
inputs, permissions, available tools, and host capabilities. For a new skill
there is no prior-skill arm; use a no-skill baseline only when it clarifies the
benefit being claimed.
Keep discovery separate from execution: a manually invoked skill can prove its
main path, but only a fresh host asked the task without naming or injecting the
activation. Test direct invocation separately when the target host exposes that
path.

Have an independent judge in a separate fresh context grade anonymized outputs
against the predeclared rubric. Give it the task, needed inputs, and rubric,
not the author's diagnosis or run history. Grade resulting decisions, files,
actions, and handoffs rather than instruction recitation, output length, or
stylistic preference. Use substantive user-like tasks so the eval does not
reward the skill merely for being named in the prompt or for repeating the
test's expected protocol. If no independent judge is available, label any
self-review as such rather than reporting it as independent evidence.

Launch the with-skill and baseline (no skill, or the old snapshot) runs of a
case together, in the same turn, so host conditions match. Capture each run's
token count and duration as it completes; Claude Code reports `total_tokens`
and `duration_ms` only in the completion notification, and other hosts need
their own source. With repeated runs, report mean ± stddev per arm and the
delta; stddev means nothing from a single run
([agentskills](https://agentskills.io/skill-creation/evaluating-skills)).
Present arms to the judge blind, as A and B in randomized order.

Ask the judge to critique the eval as well as grade it. Flag an assertion that
passes in both arms or fails in both as non-discriminating, and one that flips
across repeats as flaky; report it for a human decision, never delete it
automatically.

## Test activation with a control

A hidden skill has no model-invoked activation to test; test the parent's
chain (the transcript shows the child read and followed) and the host's
manual invocation.

Before trusting trigger rates, include a known-should-trigger query as a
positive control; it must trigger every time. Uniform 0% means the harness is
broken, not the descriptions — for example a candidate written to the wrong
location, a run started before the host picked it up, per-worker renamed
copies, or an installed copy of the same skill
([anthropics/claude-plugins-official#4425](https://github.com/anthropics/claude-plugins-official/issues/4425)).

When optimizing a description, default to the
[agentskills loop](https://agentskills.io/skill-creation/optimizing-descriptions):
about 20 queries (8-10 should trigger, 8-10 near-miss should not), a stratified
60/40 train/held-out split fixed across iterations, about 3 runs per query with
a 0.5 trigger-rate threshold, at most 5 iterations, revisions informed by train
failures only, and the winner selected by held-out score, then confirmed on
5-10 fresh queries. Never paste keywords from failed queries into the
description; that overfits.

## Pressure-test discipline skills

For a skill that enforces a rule an agent may rationalize away, follow
[superpowers' TDD loop](https://github.com/obra/superpowers/blob/main/skills/writing-skills/references/testing-skills-with-subagents.md):
run pressure scenarios that combine three or more pressures (time, sunk cost,
authority, exhaustion, consequences) without the skill, record each choice and
rationalization verbatim into a rationalization table, write minimal counters
for the observed failures only, and re-run until no new rationalization
appears.

## Read the transcripts

Outputs show what happened; transcripts show why. Read execution transcripts
and act on what they show: cut instructions that caused wasted steps or never
applied; treat a bundled file that is never read as unnecessary or poorly
signaled; move a section read on every run into `SKILL.md`; bundle a helper
that runs keep rewriting into `scripts/`
([Anthropic best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)).

## Start narrow; expand when evidence calls for it

Start with the main user path and its nearest meaningful restraint case. When
activation or routing changes, test each changed route and its nearest
false-trigger neighbor without forcing the skill to run. Add a handoff case
when a consumer contract changes. If the real decision compares several skill
variants, evaluate the candidates against the same rubric. Add distinct inputs,
repeated runs, or additional hosts only when reach, impact, observed variance,
or host divergence could change the claim. Use the weakest relevant host
available as well as any host needed for a portability claim; do not assume a
fixed model roster or repetition quota.

Stop when the evidence supports the specific claim and no unresolved,
decision-changing risk warrants another case. A broad claim needs broader
evidence; a narrow check does not justify one. Tool failures, unparsable
results, missing permissions, and unavailable hosts are inconclusive, not
passes or product failures. Do not substitute a simulated no-tool session for
a host's real lifecycle, and do not claim that an unavailable host was tested.

Run only repository-supported deterministic checks for packaging and mechanics.
They complement, but do not replace, behavior evaluation. If no available host
can exercise behavior, report the exact capability gap and leave the behavior
claim unproved.

## Record the result

Report the rubric and paths exercised, whether old and new versions were
compared, the host capabilities actually used, tokens and duration per arm
when captured, the independent judge's evidence-backed result, flagged
assertions, deterministic checks and their results, and any
inconclusive or untested claim. Keep evaluation conclusions within the hosts,
inputs, and conditions exercised.
