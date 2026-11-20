# hoa-skill-curate

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hoa-skill-curate` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.8666666666666667; sample stddev: 0.23094010767585033.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 479058.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 37278 | 23.528 |
| none | 2 | valid | fenced | 26434 | 15.836 |
| none | 3 | valid | bare | 26366 | 14.8 |
| terse | 1 | control skill access | bare | 44156 | 18.523 |
| terse | 2 | control skill access | fenced | 35467 | 16.709 |
| terse | 3 | control skill access | fenced | 36017 | 17.192 |
| skill | 1 | valid | bare | 91047 | 29.423 |
| skill | 2 | valid | bare | 74584 | 22.818 |
| skill | 3 | valid | fenced | 107709 | 39.847 |
