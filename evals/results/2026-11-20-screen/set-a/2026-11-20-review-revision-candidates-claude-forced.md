# review-revision-candidates

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `review-revision-candidates` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 467222.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 54520 | 21.137 |
| none | 2 | valid | bare | 44004 | 17.467 |
| none | 3 | valid | bare | 58294 | 27.282 |
| terse | 1 | valid | bare | 45375 | 20.396 |
| terse | 2 | valid | bare | 46812 | 18.72 |
| terse | 3 | valid | bare | 43666 | 19.006 |
| skill | 1 | valid | bare | 54244 | 21.904 |
| skill | 2 | valid | bare | 54100 | 22.797 |
| skill | 3 | valid | bare | 66207 | 26.901 |
