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
compared, the host capabilities actually used, the independent judge's
evidence-backed result, deterministic checks and their results, and any
inconclusive or untested claim. Keep evaluation conclusions within the hosts,
inputs, and conditions exercised.
