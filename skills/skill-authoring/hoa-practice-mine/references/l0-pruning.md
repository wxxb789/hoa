# Level 0: prune session roots

Read before judging skeletons or selecting the pivots that advance to L1.

```bash
hoa mine judge \
  --stage l0 \
  --input "$OUT/skeletons.jsonl" \
  --output "$OUT/l0-scored.jsonl"
```

## Select L1 pivots

```bash
hoa mine filter-spans \
  --l0 "$OUT/l0-scored.jsonl" \
  --spans "$OUT/spans.jsonl" \
  --output "$OUT/l1-candidates.jsonl"
```

Retain sessions with `anomaly_probe >= 0.20`, `user_correction_probe >= 0.20`,
raw `durability >= 0.45` (`>= 0.225` normalized for the bundled L0 scale),
`p_clean < 0.80` (`routine_clean` and `one_off_code_bug` probability mass),
or non-zero `hook_errors`. On large backlogs where the loose OR retains too many
sessions, pass `--strict` (requiring `(anomaly AND durability) OR correction OR
hook_errors`) and tune `--min-anomaly` / `--min-durability` / `--min-correction`.
`filter-spans` fails open for model refusals and
request failures: it keeps those sessions eligible for pivot selection and
counts only model refusals in `l0_refusal_sessions`. If `judge` writes a ledger
but exits `1` for failed requests, investigate the failures and use the ledger
for fail-open filtering; do not treat failed rows as clean. Audit the top 5–8
pruned sessions near the boundary before zooming into L1, plus a small random
sample of deep-negative pruned sessions on high-stakes runs (a second model at
L1 only sees L0 survivors and cannot rescue L0 false negatives).

## Handling quantized or polarized backends

`filter-spans` reports `calibration_profile` (observational metrics only; no
auto-tuning). When `quantized_001` is `true`, `extreme_predicate_rate > 0.30`,
or the loose OR retains `> 75%` of sessions, switch to `--strict` so
keyword-sensitive `anomaly_probe` spikes cannot push routine sessions through
without corroborating `durability` or `user_correction_probe`.
