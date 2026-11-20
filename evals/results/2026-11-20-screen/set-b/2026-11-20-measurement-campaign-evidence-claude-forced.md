# measurement-campaign-evidence

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `measurement-campaign-evidence` rev 2.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9166666666666666; sample stddev: 0.14433756729740643.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 298547.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 27213 | 15.114 |
| none | 2 | valid | bare | 26820 | 21.487 |
| none | 3 | valid | fenced | 27059 | 16.074 |
| terse | 1 | valid | bare | 27590 | 17.136 |
| terse | 2 | valid | bare | 27251 | 17.914 |
| terse | 3 | valid | bare | 27992 | 18.484 |
| skill | 1 | valid | bare | 44928 | 18.465 |
| skill | 2 | valid | bare | 44963 | 20.841 |
| skill | 3 | valid | fenced | 44731 | 17.529 |
