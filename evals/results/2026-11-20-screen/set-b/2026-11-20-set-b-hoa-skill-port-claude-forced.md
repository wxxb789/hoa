# set-b-hoa-skill-port

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-port` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.

CLI-reported tokens: 331411.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | control skill access | fenced | 26327 | 11.921 |
| none | 2 | control skill access | bare | 26202 | 13.344 |
| none | 3 | control skill access | fenced | 26244 | 11.96 |
| terse | 1 | control skill access | fenced | 34944 | 14.26 |
| terse | 2 | control skill access | fenced | 34800 | 14.981 |
| terse | 3 | control skill access | bare | 27123 | 15.323 |
| skill | 1 | valid | bare | 47593 | 15.07 |
| skill | 2 | valid | fenced | 47422 | 15.055 |
| skill | 3 | valid | bare | 60756 | 19.206 |
