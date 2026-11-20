# set-b-define-goal

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `define-goal` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.19245008972987523.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.19245008972987523.
- skill: 1/3 passed; loaded 3; pass^k: False; mean score: 0.4444444444444444; sample stddev: 0.5091750772173156.

CLI-reported tokens: 303091.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 28177 | 21.361 |
| none | 2 | valid | fenced | 27922 | 18.941 |
| none | 3 | valid | bare | 27879 | 19.205 |
| terse | 1 | valid | bare | 30110 | 31.508 |
| terse | 2 | valid | extracted | 28960 | 23.089 |
| terse | 3 | valid | bare | 30095 | 28.604 |
| skill | 1 | valid | bare | 37875 | 25.377 |
| skill | 2 | valid | fenced | 53527 | 35.386 |
| skill | 3 | valid | bare | 38546 | 28.306 |
