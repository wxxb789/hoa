# set-b-ghc-search

Verdict: **skill-wins** (claude, natural, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `ghc-search` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.5555555555555556; sample stddev: 0.19245008972987523.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 342254.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 37175 | 24.118 |
| none | 2 | valid | fenced | 36096 | 16.391 |
| none | 3 | valid | fenced | 36189 | 18.142 |
| terse | 1 | valid | fenced | 59118 | 30.641 |
| terse | 2 | valid | fenced | 36831 | 19.823 |
| terse | 3 | valid | fenced | 36423 | 17.747 |
| skill | 1 | valid | fenced | 29718 | 15.036 |
| skill | 2 | valid | bare | 41143 | 19.429 |
| skill | 3 | valid | fenced | 29561 | 13.6 |
