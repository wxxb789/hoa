# set-b-hoa-skill-create

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-create` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.1111111111111111; sample stddev: 0.19245008972987523.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.19245008972987523.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.5555555555555556; sample stddev: 0.19245008972987523.

CLI-reported tokens: 326699.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 28909 | 25.836 |
| none | 2 | valid | fenced | 27973 | 20.136 |
| none | 3 | valid | fenced | 28295 | 23.14 |
| terse | 1 | valid | fenced | 28862 | 24.423 |
| terse | 2 | valid | fenced | 28643 | 22.26 |
| terse | 3 | valid | fenced | 30025 | 29.981 |
| skill | 1 | valid | fenced | 58879 | 29.424 |
| skill | 2 | valid | fenced | 51376 | 38.684 |
| skill | 3 | valid | fenced | 43737 | 32.109 |
