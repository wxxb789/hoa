# set-b-hoa-skill-port

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-port` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.

CLI-reported tokens: 327237.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 34511 | 13.965 |
| none | 2 | valid | bare | 25906 | 11.532 |
| none | 3 | valid | fenced | 26179 | 12.659 |
| terse | 1 | valid | fenced | 27637 | 17.96 |
| terse | 2 | valid | bare | 26136 | 11.32 |
| terse | 3 | valid | fenced | 27094 | 14.417 |
| skill | 1 | valid | bare | 47541 | 14.707 |
| skill | 2 | valid | bare | 63893 | 19.369 |
| skill | 3 | valid | fenced | 48340 | 13.581 |
