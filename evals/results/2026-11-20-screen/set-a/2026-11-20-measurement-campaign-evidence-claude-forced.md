# measurement-campaign-evidence

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `measurement-campaign-evidence` rev 2.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 282727.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 26826 | 12.035 |
| none | 2 | valid | bare | 27238 | 13.335 |
| none | 3 | valid | bare | 35502 | 13.378 |
| terse | 1 | valid | bare | 27382 | 11.412 |
| terse | 2 | valid | bare | 27540 | 12.132 |
| terse | 3 | valid | bare | 27405 | 11.547 |
| skill | 1 | valid | bare | 33386 | 13.867 |
| skill | 2 | valid | bare | 44072 | 15.039 |
| skill | 3 | valid | bare | 33376 | 13.003 |
