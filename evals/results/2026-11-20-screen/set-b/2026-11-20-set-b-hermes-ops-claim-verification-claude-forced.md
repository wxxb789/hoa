# set-b-hermes-ops-claim-verification

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hermes-ops-claim-verification` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.

CLI-reported tokens: 369237.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 39561 | 20.209 |
| none | 2 | valid | bare | 27235 | 14.17 |
| none | 3 | control skill access | bare | 52840 | 27.918 |
| terse | 1 | control skill access | bare | 35685 | 16.145 |
| terse | 2 | control skill access | bare | 40522 | 21.182 |
| terse | 3 | control skill access | bare | 27902 | 16.371 |
| skill | 1 | valid | bare | 48209 | 15.711 |
| skill | 2 | valid | bare | 49136 | 16.729 |
| skill | 3 | valid | bare | 48147 | 15.526 |
