# hoa-skill-port

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-port` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 718540.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 60239 | 30.091 |
| none | 2 | valid | bare | 61333 | 24.854 |
| none | 3 | valid | fenced | 63742 | 29.029 |
| terse | 1 | valid | bare | 62811 | 28.398 |
| terse | 2 | valid | bare | 63195 | 27.289 |
| terse | 3 | valid | bare | 78078 | 30.418 |
| skill | 1 | valid | bare | 97969 | 37.962 |
| skill | 2 | valid | bare | 134341 | 47.514 |
| skill | 3 | valid | fenced | 96832 | 35.789 |
