# evidence-backed-analytical-writing

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `evidence-backed-analytical-writing` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 2/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.5773502691896257.

CLI-reported tokens: 262545.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 24638 | 11.944 |
| none | 2 | valid | bare | 24819 | 14.288 |
| none | 3 | valid | bare | 24626 | 11.806 |
| terse | 1 | valid | bare | 24812 | 11.327 |
| terse | 2 | valid | bare | 24866 | 13.257 |
| terse | 3 | valid | bare | 24725 | 11.3 |
| skill | 1 | valid | bare | 34409 | 15.538 |
| skill | 2 | valid | bare | 33775 | 12.83 |
| skill | 3 | valid | extracted | 45875 | 15.468 |
