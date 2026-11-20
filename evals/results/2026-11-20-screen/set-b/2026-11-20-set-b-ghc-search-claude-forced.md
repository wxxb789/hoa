# set-b-ghc-search

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `ghc-search` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 332496.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | control skill access | fenced | 36450 | 18.982 |
| none | 2 | control skill access | fenced | 36946 | 21.853 |
| none | 3 | valid | fenced | 26456 | 15.367 |
| terse | 1 | control skill access | fenced | 37184 | 21.833 |
| terse | 2 | control skill access | fenced | 36771 | 19.171 |
| terse | 3 | control skill access | fenced | 36968 | 19.935 |
| skill | 1 | valid | fenced | 40764 | 15.092 |
| skill | 2 | valid | fenced | 40663 | 14.865 |
| skill | 3 | valid | fenced | 40294 | 13.595 |
