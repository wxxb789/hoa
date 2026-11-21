# Behavioral evaluation

Read this reference when a conclusion depends on behavior that static evidence cannot settle, or when judging candidate replies or skill variants. Do not run a broad evaluation matrix for a straightforward review whose claim is already established by the relevant path.

## Set up an honest comparison

1. State the behavior claim and the real user or consumer outcome before choosing cases. Use the user's request, the skill's stated contract, and the actual consumer contract as evidence; do not substitute model confidence or aesthetic preference.
2. Freeze the rubric before generating candidate outputs or exposing supplied outputs to the evaluator. Define each criterion, which criteria are hard gates, and what observable evidence means met, partial, failed, or ungradable. For a criterion marked required by the rubric (for example, `must_hold`), an available candidate that omits required evidence fails that criterion; do not label the omission ungradable. Carry user-specified requirements forward. If outputs are already present in the review conversation, derive the rubric only from the task and authoritative contracts, then record that the primary reviewer had prior exposure. Do not add a criterion after seeing which candidate it favors.
3. Use a fresh, independent judge that has not seen the candidate outputs, authoring conversation, or expected winner. Give it the task and frozen rubric, then the unaltered outputs under neutral labels. If a fresh judge is unavailable, do not call a self-review independent; provide only evidence-backed observations and mark comparative judgment unverified.

For a skill behavior comparison, run the baseline and candidate with the same task, relevant context, tools, host, and consumer conditions; use a fresh run for each so one output cannot prime the other. If supplied candidate replies were produced under different or unknown conditions, judge each against the rubric but do not attribute the difference to a skill change. When the user only asks to judge supplied replies, do not regenerate them or imply they came from a controlled comparison.

## Choose cases proportionately

For a behavior comparison, begin with a discriminating case where the claimed behavior matters and a restraint case where the skill should not overreach or change unrelated behavior. Keep the cases tied to real task conditions. Add cases only for a materially different trigger or consumer path, meaningful risk, observed variance, or a host difference that could change the result. Compare additional candidate versions or hosts when those differences are decision-relevant; do not cross every version, prompt, and host by default.

For supplied replies to one task, the frozen rubric and that shared task are the primary case. Add a restraint case only when the claim being judged extends beyond that task. If a branch, host, or consumer cannot be reached, list it as unverified rather than treating it as a passing matrix cell.

## Score and preserve evidence

Use categorical judgments unless a numeric score is requested or required by the frozen rubric. If numbers are needed and no scale was supplied, declare this per-criterion scale before judging: **0** = contradicted or not met, including required evidence omitted by an available candidate; **1** = partial or ambiguous; **2** = met with observable evidence; **U** = the evaluator cannot assess the criterion because necessary external context, source, or execution evidence is unavailable. U is not a substitute for a candidate's missing required evidence. Cite the exact output passage or observed path for every grade. Do not convert U to zero, invent fractional precision, or aggregate scores unless the frozen rubric defines weights and how hard gates affect the result. A hard-gate failure cannot be hidden by a high aggregate.

Preserve candidate output exactly when the consumer contract requires a particular format. If that contract is machine-parseable, check the raw output against the actual schema or parser; do not silently repair, normalize, or omit malformed output. A parse error fails the format criterion when valid syntax is required, and fails any `must_hold` whose required evidence the actual consumer cannot extract. Grade other criteria only where the raw content still supplies evidence. Use U only when missing external context or an unavailable execution boundary prevents assessment, not because the candidate omitted required proof. If no parse was actually attempted, report the check as unverified.

A judge's score is not its evidence. Every grade must point to observable content or an executed path and explain how it meets or misses the frozen criterion. Missing candidate evidence required by a criterion is a failure; unavailable source, context, host, or consumer evidence that prevents judging is unverified and may make that criterion U. Report the task and comparison conditions, the judge's independence status, cases and hosts actually exercised, parse errors, and the limits that remain.

## Separate simulation from consumer proof

A simulated prompt shows what happened in that simulation only. It does not prove that a real host would auto-activate the skill. Automatic activation is verified only by an actual host invocation where the skill was not forced into context; a forced invocation verifies body behavior only. Real downstream behavior requires exercising the actual consuming component and observing its interpretation, parse result, or state transition. A mock can verify its own contract, not a different real consumer. A tool call or protocol handoff is verified by its actual receipt, log, or resulting artifact, not by a model's account of what it would do.

In the report, identify each path as verified or unverified and name the evidence boundary: static inspection, fixture, simulated prompt, mock, or real host and consumer. Never claim an unavailable host was tested or let a successful simulation stand in for an unobserved lifecycle.
