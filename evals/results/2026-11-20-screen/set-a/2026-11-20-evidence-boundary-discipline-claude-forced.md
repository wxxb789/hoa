# evidence-boundary-discipline

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `evidence-boundary-discipline` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9333333333333333; sample stddev: 0.11547005383792512.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9333333333333333; sample stddev: 0.11547005383792512.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 271036.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 24555 | 13.029 |
| none | 2 | valid | fenced | 24287 | 12.001 |
| none | 3 | valid | fenced | 24554 | 12.268 |
| terse | 1 | valid | bare | 24648 | 11.569 |
| terse | 2 | valid | fenced | 24654 | 13.266 |
| terse | 3 | valid | fenced | 24851 | 12.523 |
| skill | 1 | valid | fenced | 41123 | 14.832 |
| skill | 2 | valid | bare | 41380 | 15.75 |
| skill | 3 | valid | bare | 40984 | 15.233 |
