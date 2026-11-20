# set-b-hermes-models

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hermes-models` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.3333333333333333; sample stddev: 0.3333333333333333.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.5555555555555556; sample stddev: 0.19245008972987523.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.

CLI-reported tokens: 339074.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 30224 | 23.923 |
| none | 2 | valid | bare | 31107 | 26.527 |
| none | 3 | valid | none | 30063 | 24.093 |
| terse | 1 | valid | fenced | 31060 | 24.291 |
| terse | 2 | valid | fenced | 30664 | 23.009 |
| terse | 3 | valid | fenced | 30983 | 25.331 |
| skill | 1 | valid | fenced | 50787 | 27.804 |
| skill | 2 | valid | fenced | 52049 | 27.434 |
| skill | 3 | valid | bare | 52137 | 27.16 |
