# L2 audit rigor

L2 turns patterns into cautious, testable findings. It is not a quota-driven
diagnosis engine.

The report narrative may use untracked `report_language` (default `en-US`),
while citation identifiers and numeric evidence remain unchanged.

## Admission rule

A blind-spot claim is eligible only when it has at least **two independent
origins** in the supplied bundle. Independence is `origin_fingerprint`
inequality. A transcript, auto-summary, synced copy, session branch, repeated
excerpt, or restatement of one origin counts once.

For every candidate:

1. write the narrow observation first;
2. search for counter-evidence in the available coverage;
3. attach re-resolvable citations from distinct origins;
4. pass the citations through `scripts/audit.py`;
5. rank survivors by **impact × unawareness**, explaining both components from
   evidence instead of treating rank as fact.

`0 blind spots` is a valid and often useful result. Insufficient evidence is a
report outcome, not a reason to weaken the admission rule.

## Labels

- **Observation:** directly visible, bounded fact, such as a repeated explicit
  event or stated choice.
- **Inference:** a cautious interpretation derived from observations; state why
  plausible counter-evidence did not defeat it.
- **Speculation:** a question or hypothesis to test next. It can appear in On
  the Horizon but **is never evidence** and cannot support a blind-spot claim.

Avoid clinical, personality, or motive claims. Prefer behavior-focused phrasing
that an operator can verify or falsify.

## Citation resolution and coverage

Before publishing, re-resolve a citation sample against the actual files and
bundle. `audit.py` mechanically drops a claim if a locator is absent, out of
range, unmatched to a bundle origin, or leaves fewer than two distinct origins.
Drop it from prose too. If a citation cannot be safely exposed in a shareable
artifact, retain only an untracked internal version or omit the claim.

Every conclusion must name its time window and available sources. Never make a
claim about any manifest source whose status is not `available`; “not found”
does not demonstrate non-use.
