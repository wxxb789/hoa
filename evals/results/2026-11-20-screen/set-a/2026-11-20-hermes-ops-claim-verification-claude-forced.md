# hermes-ops-claim-verification

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hermes-ops-claim-verification` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 294585.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 24106 | 8.957 |
| none | 2 | valid | bare | 24205 | 9.219 |
| none | 3 | valid | fenced | 24594 | 9.854 |
| terse | 1 | valid | bare | 24677 | 9.148 |
| terse | 2 | valid | fenced | 24490 | 8.525 |
| terse | 3 | valid | fenced | 24576 | 8.86 |
| skill | 1 | valid | bare | 57737 | 13.227 |
| skill | 2 | valid | bare | 44883 | 10.026 |
| skill | 3 | valid | bare | 45317 | 10.888 |
