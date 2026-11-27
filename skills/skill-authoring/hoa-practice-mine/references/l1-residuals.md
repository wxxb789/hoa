# Level 1: orthogonal heads and residual reflection

Read before scanning `l1-candidates.jsonl`, inspecting residuals, or revising
an L1 rubric. The input is the pivot spans from L0-surviving sessions.

## Choose the round

- **Bundled rubrics:** use `l1-v2` directly after `anchor-check` has passed for
  your endpoint. This halves model calls compared with scoring both versions.
- **Custom taxonomy only:** judge `--stage l1-v1` into
  `$OUT/l1-r1-scored.jsonl`, then run `residuals` with that stage and scored
  file, the candidate spans, and `--output "$OUT/r1-residuals.json"`. Use
  `--rubrics <file>` when supplying a custom rubric document. Inspect Round 1
  before editing the taxonomy; hand deeper refinement off to `rubric-tune`.

## Inspect the residual report

In `r1-residuals.json` or `r2-residuals.json`, inspect these pools. Pull adjacent
spans when truncated.

1. **Epistemic OOD pool** (`ood_residual = p_anom * (p_novel + 0.5 * max(0.0, 1.0 - p_routine - max_known))`,
   where `max_known` is the largest probability among known, non-routine buckets):
   add a positive bucket only for genuine unknown mechanisms.
2. **High-anomaly gray-zone pool** (`P(anomaly) >= 0.80` with a normalized
   guardrail score in `[0.25, 0.70]` or Shannon entropy `>= 1.50`): inspect
   routine noise and add explicit negative exclusions if needed.
3. **Refusal pool**: `refusal_count` sums model refusals (`reason: model_refusal`)
   and failed requests (any other `reason`, such as HTTP errors or timeouts).
   Fix the endpoint for the latter; for the former, inspect the framing and strip
   any new fixed injection shell with `--redact-regex`.
4. **Distribution profile (`calibration_profile`)**: check `quantized_001`,
   `extreme_predicate_rate`, and `head_discordance_pred_high_routine_rate` to
   spot quantized or keyword-overtriggered backends. Bundled `l1-v2` gates
   `select-survivors` on `anomaly_probe` (`--min-anomaly`, default `0.50`) and
   excludes `evidence_backing` in `{no_lesson_evidence, single_app_only}`.

Use `confusion_pairs` to find recurring overlap between two known positive
buckets. Inspect examples before merging labels that call for the same action.

## Check the anchors, then score Round 2

For the bundled rubrics, run the anchor check before the direct `l1-v2` pass
unless it has already passed for this endpoint. For a custom revision, prepare
one rubric file that preserves the locked anchors and `l1-v1` baseline and
carries the revised `l1-v2`. Pass `--rubrics <file>` to `anchor-check`, both
Round 2 commands, and `select-survivors` in L3.

```bash
hoa mine anchor-check --baseline-stage l1-v1 --candidate-stage l1-v2
```

Continue only if the anchor check passes.

```bash
hoa mine judge --stage l1-v2 \
  --input "$OUT/l1-candidates.jsonl" --output "$OUT/l1-r2-scored.jsonl"
hoa mine residuals --stage l1-v2 \
  --scored "$OUT/l1-r2-scored.jsonl" --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/r2-residuals.json"
```

Inspect Round 2, then apply the [stopping criterion](methodology.md#stopping-criterion)
before advancing. Do not refine a rubric at the expense of the anchors.

## Optional cross-model disagreement audit (offline)

When an operator authorizes a second decision model (for example, pairing a
calibrated continuous primary model with a high-recall quantized challenger),
score the same candidate spans with both models via separate `hoa mine judge`
calls, then join the two ledgers offline:

```bash
hoa mine disagreements \
  --stage l1-v2 \
  --left "$OUT/l1-primary.jsonl" \
  --right "$OUT/l1-challenger.jsonl" \
  --spans "$OUT/l1-candidates.jsonl" \
  --top-k 20 \
  --output "$OUT/disagreements.json"
```

For custom ledgers outside the bundled stage schema, omit `--stage` and pass
`--predicate`, `--choice`, `--routine-label`, and optional `--score` / `--score-max`.
Inspect `left_only_top`, `right_only_top`, and `taxonomy_split_top` (ranked by
continuous incident/survivor mass deltas rather than brittle hard cutoffs) and
treat `head_conflict_top` (high predicate with routine choice) as a diagnostic
signal rather than positive admission.
