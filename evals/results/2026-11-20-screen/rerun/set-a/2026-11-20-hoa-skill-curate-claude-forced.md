# hoa-skill-curate

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-curate` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 360387.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 37647 | 25.982 |
| none | 2 | valid | bare | 37226 | 22.9 |
| none | 3 | valid | fenced | 26637 | 15.862 |
| terse | 1 | valid | fenced | 35368 | 16.672 |
| terse | 2 | valid | fenced | 35355 | 16.75 |
| terse | 3 | valid | bare | 44553 | 21.084 |
| skill | 1 | valid | bare | 47807 | 17.439 |
| skill | 2 | valid | fenced | 47989 | 18.774 |
| skill | 3 | valid | fenced | 47805 | 18.42 |
