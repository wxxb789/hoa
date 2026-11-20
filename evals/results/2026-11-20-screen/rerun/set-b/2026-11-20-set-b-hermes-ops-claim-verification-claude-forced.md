# set-b-hermes-ops-claim-verification

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hermes-ops-claim-verification` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.4444444444444444; sample stddev: 0.19245008972987523.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.4444444444444444; sample stddev: 0.19245008972987523.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.

CLI-reported tokens: 352745.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 39090 | 15.516 |
| none | 2 | valid | bare | 27297 | 13.61 |
| none | 3 | valid | fenced | 27624 | 13.481 |
| terse | 1 | valid | fenced | 27284 | 14.419 |
| terse | 2 | valid | fenced | 28285 | 16.915 |
| terse | 3 | valid | bare | 40183 | 20.153 |
| skill | 1 | valid | bare | 49490 | 17.456 |
| skill | 2 | valid | bare | 48310 | 14.854 |
| skill | 3 | valid | bare | 65182 | 22.103 |
