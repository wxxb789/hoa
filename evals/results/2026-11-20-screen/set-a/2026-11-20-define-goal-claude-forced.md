# define-goal

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `define-goal` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.8571428571428571; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.8571428571428571; sample stddev: 0.0.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.8095238095238095; sample stddev: 0.08247860988423221.

CLI-reported tokens: 292898.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 25328 | 13.942 |
| none | 2 | valid | bare | 25768 | 14.582 |
| none | 3 | valid | bare | 25554 | 13.681 |
| terse | 1 | valid | fenced | 25646 | 14.375 |
| terse | 2 | valid | fenced | 26023 | 17.576 |
| terse | 3 | valid | fenced | 25846 | 14.877 |
| skill | 1 | valid | fenced | 45742 | 17.382 |
| skill | 2 | valid | fenced | 46511 | 20.747 |
| skill | 3 | valid | fenced | 46480 | 20.497 |
