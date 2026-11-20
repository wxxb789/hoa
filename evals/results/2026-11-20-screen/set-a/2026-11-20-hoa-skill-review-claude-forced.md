# hoa-skill-review

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-review` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 325171.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | control skill access | bare | 26898 | 18.46 |
| none | 2 | control skill access | fenced | 34481 | 17.914 |
| none | 3 | control skill access | fenced | 26283 | 16.185 |
| terse | 1 | control skill access | fenced | 35562 | 20.6 |
| terse | 2 | control skill access | fenced | 35407 | 19.249 |
| terse | 3 | control skill access | bare | 35846 | 23.005 |
| skill | 1 | valid | bare | 42262 | 16.233 |
| skill | 2 | valid | bare | 45602 | 19.214 |
| skill | 3 | valid | bare | 42830 | 19.199 |
