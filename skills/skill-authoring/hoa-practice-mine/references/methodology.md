# Session History Mining Methodology

## Why Naive Multi-Pass Linear Funnels Fail

1. **Closed-set Softmax OOD blindness.** In a standard mutually exclusive `choice`
   over `{noise, bucket_1, ..., bucket_k}`, an out-of-distribution (OOD) incident
   that matches none of the positive buckets shares zero features with `bucket_i`
   and gets pushed into the catch-all `noise` bucket with `P(noise) > 0.95`
   (epistemic uncertainty masquerading as high confidence). Entropy only peaks
   when an input straddles two *known* buckets (aleatoric ambiguity).
   **Fix:** Pair an unbiased, category-free `anomaly_probe` (`predicate`) with an
   explicit `unclassified_novel_*` escape-hatch choice. Rank OOD with
   `ood_residual = p_anom * (p_novel + 0.5 * max(0.0, 1.0 - p_routine - max_known))`,
   where `max_known` is the largest probability of a known non-routine bucket.
   For aleatoric ambiguity, inspect `confusion_pairs`: recurring high-overlap
   pairs of known positive buckets are merge candidates when both call for the
   same action.
2. **Repeated KV-cache prefill waste.** On `/v1/decisions`, encoding the state
   window dominates latency and cost (~95%+), whereas evaluating 3–4 independent
   orthogonal questions on the same encoded state is nearly free. Splitting
   orthogonal dimensions (evidence backing, failure mechanism, target owner,
   cross-repo durability) into serial passes wastes prefill and forces artificial
   competition between non-mutually-exclusive traits.
3. **Trajectory severance under blind chunking.** Agent sessions are Markov
   trajectories: a root cause at line 20 may surface at line 90 and be diagnosed
   at line 140. Fixed-line chunking severs cause from diagnosis.
   **Fix:** Build a whole-session **Session Skeleton** (`L0`) retaining 100% of
   human turns, tool/hook errors, and boundary claims while folding clean local
   read/edit streaks into single summary lines. Prune whole clean sessions at `L0`
   before zooming into overlapping causal turn-windows (`L1`).
4. **Prompt calibration drift across iterations.** Editing rubric wording shifts
   the Softmax temperature and baseline probabilities. Apparent "bimodal
   sharpening" without a locked validation set can simply reflect pushing gray-zone
   positives into `noise`.
   **Fix:** Gate every rubric revision on a locked 16-item Gold Anchor Set (8 true
   positives + 8 deceptive negatives). Accept a revision only when false negatives,
   false positives, and refusals all stay `0` and
   `worst_case_gap = min(score_pos) - max(score_neg)` is non-decreasing on the
   same endpoint. Do not compare `worst_case_gap` across different backends, and
   do not treat a low `unclassified_novel_*` rate as proof of zero misses.

## Source adapters

For store schemas, discovery rules, and exact evidence locators, read only the
adapters for the sources in scope: [Claude Code](sources/claude-code.md),
[OMP](sources/omp.md), or [Codex](sources/codex.md).

## Stopping Criterion

Stop iterating `L1` rubrics as soon as:
1. Anchor `false_negatives == 0` and `worst_case_gap` improved or held steady;
2. `unclassified_novel_*` top-choice share drops below `1%` (or `< 3` spans);
3. Sampling the negative boundary (`max_neg_audit`) reveals zero missed cross-repo lessons.

Proceed immediately to `L3` baseline novelty reconciliation against live repository
files rather than over-tuning taxonomy labels.
