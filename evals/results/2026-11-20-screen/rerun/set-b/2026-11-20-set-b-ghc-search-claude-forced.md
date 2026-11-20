# set-b-ghc-search

Verdict: **skill-wins** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `ghc-search` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 339638.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 36388 | 20.126 |
| none | 2 | valid | fenced | 36215 | 18.114 |
| none | 3 | valid | fenced | 36619 | 19.198 |
| terse | 1 | valid | fenced | 36400 | 18.667 |
| terse | 2 | valid | fenced | 36358 | 17.959 |
| terse | 3 | valid | fenced | 36176 | 17.378 |
| skill | 1 | valid | fenced | 40282 | 15.967 |
| skill | 2 | valid | fenced | 40832 | 15.795 |
| skill | 3 | valid | fenced | 40368 | 13.905 |
