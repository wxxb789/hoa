# hoa-skill-review

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-review` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 348986.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 26393 | 16.268 |
| none | 2 | valid | fenced | 35246 | 20.569 |
| none | 3 | valid | bare | 34972 | 19.294 |
| terse | 1 | valid | fenced | 35789 | 22.426 |
| terse | 2 | valid | fenced | 35453 | 20.584 |
| terse | 3 | valid | bare | 35349 | 18.829 |
| skill | 1 | valid | bare | 46289 | 27.111 |
| skill | 2 | valid | fenced | 56516 | 20.257 |
| skill | 3 | valid | bare | 42979 | 19.287 |
