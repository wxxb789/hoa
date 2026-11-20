# hoa-skill-create

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-create` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9629629629629629; sample stddev: 0.06415002990995845.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9629629629629629; sample stddev: 0.06415002990995845.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 691588.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 53474 | 31.284 |
| none | 2 | valid | fenced | 71842 | 30.914 |
| none | 3 | valid | fenced | 80722 | 35.606 |
| terse | 1 | valid | fenced | 86140 | 33.766 |
| terse | 2 | valid | fenced | 72177 | 35.21 |
| terse | 3 | valid | fenced | 55935 | 27.1 |
| skill | 1 | valid | fenced | 94682 | 35.86 |
| skill | 2 | valid | fenced | 81795 | 31.963 |
| skill | 3 | valid | extracted | 94821 | 33.511 |
