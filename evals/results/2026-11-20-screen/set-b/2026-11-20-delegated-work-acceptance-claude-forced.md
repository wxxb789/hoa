# delegated-work-acceptance

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `delegated-work-acceptance` rev 7.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.7222222222222222; sample stddev: 0.09622504486493767.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- skill: 1/3 passed; loaded 3; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.

CLI-reported tokens: 334835.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 27484 | 17.031 |
| none | 2 | valid | fenced | 27947 | 18.018 |
| none | 3 | valid | fenced | 28087 | 18.035 |
| terse | 1 | valid | bare | 27896 | 17.331 |
| terse | 2 | valid | bare | 27737 | 16.442 |
| terse | 3 | valid | fenced | 27918 | 17.67 |
| skill | 1 | valid | fenced | 50088 | 20.796 |
| skill | 2 | valid | bare | 50353 | 21.582 |
| skill | 3 | valid | fenced | 67325 | 30.506 |
