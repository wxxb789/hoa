# official-document-verification

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `official-document-verification` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 277335.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 24798 | 11.13 |
| none | 2 | valid | fenced | 24607 | 10.882 |
| none | 3 | valid | fenced | 24862 | 11.815 |
| terse | 1 | valid | bare | 34149 | 13.154 |
| terse | 2 | valid | fenced | 25089 | 12.019 |
| terse | 3 | valid | fenced | 24757 | 10.393 |
| skill | 1 | valid | fenced | 39671 | 13.37 |
| skill | 2 | valid | fenced | 39713 | 12.976 |
| skill | 3 | valid | fenced | 39689 | 13.139 |
