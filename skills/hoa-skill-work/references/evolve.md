# Evolve an existing skill

Begin from the real failing path or the user's specific improvement target.
Read the skill and every reference or local contract on that path. Inspect
relevant tests, examples, callers, and target-host behavior so the change
addresses what the skill actually does, not only the line that drew attention.

## Locate the cause and preserve provenance

When the request describes a failure, reproduce it before editing when the
required host and inputs are available. Use the actual user-facing task and
inspect the resulting artifact or action. If reproduction is unavailable,
identify exactly what is missing and treat the report as evidence without
claiming independent reproduction. For a requested improvement without a
failure, define the intended observable change before choosing a rewrite.

Trace the failure to the layer that owns it: activation metadata, skill
instructions, a referenced procedure, an invoked tool, the runtime, or the
downstream consumer. Make the smallest change at that layer. A body edit cannot
repair a host lifecycle that was never reached, and a trigger edit cannot
repair a poor result after successful activation.

Before removing or materially generalizing a mandate, search for its rationale
in available tests, comments, issues, documentation, and relevant history.
Preserve an evidence-backed mandate while the condition it protects still
applies. When no rationale is found, record that absence and decide whether the
line still constrains a plausible failure mode; absence alone is not proof that
it was harmless. For every removal, state what now decides the behavior. If no
permitted source can establish provenance, say that it could not be recovered.

## Make the smallest durable change

Keep unaffected activation paths, outputs, and consumer contracts intact. A
changed handoff requires updating every in-scope caller and consumer together;
do not leave an obsolete branch, alias, or contradictory instruction. When
repeated case-specific patches have accumulated, replace them with the outcome
and condition that explain all of the cases, then check each prior path against
that rule.

Do not expand a requested skill edit into unrelated repository rules,
configuration, external publication, or destructive changes. Use the
authority stated in `SKILL.md` and follow any stricter project or host gate.

## Verify and close

For a behavior-bearing change, use [the evaluation protocol](evaluate.md) to
compare the old and revised skill on equivalent tasks and check the nearest
affected restraint path. For a mechanical-only change with behavior impact
ruled out, use its deterministic-check branch and record why behavior
evaluation was skipped. Also run the target repository's relevant deterministic
checks when available, but report them separately from behavior evidence.
Summarize the changed paths and outcome, the smallest cause addressed,
provenance for removed mandates, validation actually performed, and anything
still unverified.
