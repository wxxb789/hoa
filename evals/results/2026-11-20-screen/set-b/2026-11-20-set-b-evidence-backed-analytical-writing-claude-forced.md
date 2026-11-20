# set-b-evidence-backed-analytical-writing

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `evidence-backed-analytical-writing` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 332995.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 30800 | 25.578 |
| none | 2 | valid | bare | 30568 | 24.77 |
| none | 3 | valid | bare | 31627 | 27.185 |
| terse | 1 | valid | bare | 30932 | 24.911 |
| terse | 2 | valid | bare | 32107 | 29.891 |
| terse | 3 | valid | fenced | 32251 | 30.454 |
| skill | 1 | valid | bare | 50631 | 23.237 |
| skill | 2 | valid | bare | 52115 | 28.593 |
| skill | 3 | valid | fenced | 41964 | 33.715 |
