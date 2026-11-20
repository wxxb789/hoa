# set-b-hoa-skill-review

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-review` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.5773502691896257.
- skill: 1/3 passed; loaded 3; pass^k: False; mean score: 0.5; sample stddev: 0.5.

CLI-reported tokens: 294635.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 25833 | 15.003 |
| none | 2 | valid | fenced | 25976 | 16.496 |
| none | 3 | valid | bare | 25622 | 13.966 |
| terse | 1 | valid | fenced | 25889 | 14.312 |
| terse | 2 | valid | fenced | 26324 | 16.942 |
| terse | 3 | valid | none | 25801 | 14.182 |
| skill | 1 | valid | fenced | 46153 | 17.592 |
| skill | 2 | valid | bare | 46472 | 18.75 |
| skill | 3 | valid | none | 46565 | 17.644 |
