# set-b-evidence-boundary-discipline

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `evidence-boundary-discipline` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.19245008972987523.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.1111111111111111; sample stddev: 0.19245008972987523.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.4444444444444444; sample stddev: 0.19245008972987523.

CLI-reported tokens: 279895.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 26473 | 14.616 |
| none | 2 | valid | fenced | 26454 | 21.442 |
| none | 3 | valid | fenced | 27134 | 17.62 |
| terse | 1 | valid | bare | 27317 | 15.781 |
| terse | 2 | valid | fenced | 27047 | 18.282 |
| terse | 3 | valid | fenced | 27077 | 16.098 |
| skill | 1 | valid | fenced | 32773 | 16.316 |
| skill | 2 | valid | fenced | 42874 | 16.918 |
| skill | 3 | valid | fenced | 42746 | 16.096 |
