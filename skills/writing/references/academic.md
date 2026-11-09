# Academic writing

For papers, sections, abstracts, reviews, related-work, rebuttals.

## Structure
- **Full paper:** abstract → intro (gap + contribution, stated explicitly) → related work →
  method → experiments/results → limitations → conclusion → (refs).
- **Single section:** claim → evidence → method/derivation → limitation/threat to validity.
- **Abstract (≈150–250w):** context (1–2 sentences) → gap → what we do → key result with a
  number → significance. No citations in the abstract.

## Tone
- Precise, hedged, impersonal-ish. "We show that…", "results suggest…", "this indicates…".
- State uncertainty explicitly: confidence intervals, ablations, failure cases.
- Passive voice acceptable where it improves objectivity; otherwise prefer active "We".
- No hype: ban "revolutionary", "huge", "novel" (let the work show novelty), "obviously".

## Evidence discipline
- Every empirical claim is backed by a number, a citation, or a figure/table reference.
- Numbers carry units + variance (mean ± std, n=…). Report seeds / runs for ML.
- Define every term/symbol before first use. Introduce acronyms once: "X (full form)".
- Distinguish what you *measured* from what you *infer*. Don't overclaim causation.

## Formatting
- Cite as the venue requires (\\cite{} / [N]). Don't invent references — mark `[CITE: topic]`.
- Tables for quantitative comparison; figures for trends. Caption = self-contained.
- Equations numbered if referenced later.

## Don'ts
- No rhetorical questions, no emoji, no first-person bragging.
- No unbacked superlatives, no marketing CTA, no "in this fast-moving field".
- Don't bury the contribution — it must be unmissable in the intro's last paragraph.

## AI-smell to watch (academic-adjusted)
- "穷尽反驳" / addressing every objection is a NORM here, not an AI tell — don't suppress it.
- DO watch: uniform paragraph rhythm, hedge-everything with no actual stance, synonym-swapping
  the same construct, connectors over-used ("Furthermore, it is important to note that").
- Real academic writing still has a clear thesis and admits specific limitations.

## Quick checklist before done
- [ ] Contribution stated explicitly and early
- [ ] Every claim backed (number/cite/figure)
- [ ] Limitations section is honest and specific
- [ ] Terms defined before use; no invented citations
