# research-stream-consolidation

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `research-stream-consolidation` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 764433.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | none | 66804 | 48.08 |
| none | 2 | valid | none | 49778 | 34.874 |
| none | 3 | valid | none | 68509 | 49.174 |
| terse | 1 | valid | none | 76935 | 56.253 |
| terse | 2 | valid | none | 79427 | 49.237 |
| terse | 3 | valid | none | 99742 | 67.438 |
| skill | 1 | valid | none | 122178 | 63.641 |
| skill | 2 | valid | none | 100947 | 58.819 |
| skill | 3 | valid | none | 100113 | 47.804 |
