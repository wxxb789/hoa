# research-stream-consolidation

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `research-stream-consolidation` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.8333333333333334; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.09622504486493767.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.09622504486493767.

CLI-reported tokens: 459071.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 38174 | 19.644 |
| none | 2 | valid | fenced | 37911 | 19.429 |
| none | 3 | valid | fenced | 38665 | 23.536 |
| terse | 1 | valid | bare | 51060 | 32.272 |
| terse | 2 | valid | fenced | 38512 | 20.892 |
| terse | 3 | valid | fenced | 77950 | 53.88 |
| skill | 1 | valid | fenced | 55264 | 26.488 |
| skill | 2 | valid | fenced | 67838 | 30.843 |
| skill | 3 | valid | fenced | 53697 | 22.244 |
