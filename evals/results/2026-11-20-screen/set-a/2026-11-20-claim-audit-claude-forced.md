# claim-audit

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `report-claim-audit` rev 2.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.0.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.0.

CLI-reported tokens: 276368.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 25550 | 11.732 |
| none | 2 | valid | fenced | 25439 | 10.857 |
| none | 3 | valid | bare | 25420 | 12.763 |
| terse | 1 | valid | bare | 25503 | 10.102 |
| terse | 2 | valid | bare | 25641 | 11.349 |
| terse | 3 | valid | fenced | 25761 | 11.357 |
| skill | 1 | valid | fenced | 40981 | 14.038 |
| skill | 2 | valid | fenced | 41209 | 14.054 |
| skill | 3 | valid | bare | 40864 | 12.266 |
