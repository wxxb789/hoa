# delegated-work-acceptance

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `delegated-work-acceptance` rev 7.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9523809523809523; sample stddev: 0.08247860988423228.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 305774.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 25010 | 10.104 |
| none | 2 | valid | bare | 25444 | 10.059 |
| none | 3 | valid | bare | 35668 | 16.552 |
| terse | 1 | valid | bare | 25637 | 12.413 |
| terse | 2 | valid | bare | 25700 | 9.364 |
| terse | 3 | valid | bare | 25749 | 11.047 |
| skill | 1 | valid | bare | 47627 | 13.606 |
| skill | 2 | valid | bare | 47458 | 12.611 |
| skill | 3 | valid | bare | 47481 | 13.556 |
