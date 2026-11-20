# ghc-search

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `ghc-search` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 279540.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 25037 | 8.96 |
| none | 2 | valid | fenced | 25026 | 8.547 |
| none | 3 | valid | fenced | 25081 | 8.648 |
| terse | 1 | valid | bare | 25547 | 9.452 |
| terse | 2 | valid | fenced | 33257 | 9.288 |
| terse | 3 | valid | bare | 25507 | 9.816 |
| skill | 1 | valid | fenced | 39935 | 11.174 |
| skill | 2 | valid | fenced | 39850 | 11.123 |
| skill | 3 | valid | fenced | 40300 | 11.214 |
