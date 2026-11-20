# set-b-hoa-skill-curate

Verdict: **skill-wins** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-curate` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.3333333333333333; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.19245008972987523.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 317803.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 28324 | 18.205 |
| none | 2 | valid | fenced | 27264 | 21.072 |
| none | 3 | valid | fenced | 27997 | 17.509 |
| terse | 1 | valid | fenced | 29102 | 19.349 |
| terse | 2 | valid | fenced | 28500 | 16.993 |
| terse | 3 | valid | fenced | 27942 | 16.011 |
| skill | 1 | valid | fenced | 49338 | 18.269 |
| skill | 2 | valid | bare | 49740 | 20.225 |
| skill | 3 | valid | bare | 49596 | 19.622 |
