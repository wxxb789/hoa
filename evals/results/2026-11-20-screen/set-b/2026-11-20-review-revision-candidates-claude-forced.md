# review-revision-candidates

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `review-revision-candidates` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- terse: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- skill: 0/3 passed; loaded 3; pass^k: False; mean score: 0.2222222222222222; sample stddev: 0.38490017945975047.

CLI-reported tokens: 402712.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 38095 | 21.846 |
| none | 2 | valid | fenced | 38122 | 22.755 |
| none | 3 | valid | fenced | 37694 | 20.479 |
| terse | 1 | valid | fenced | 38391 | 21.944 |
| terse | 2 | valid | fenced | 38372 | 22.447 |
| terse | 3 | valid | fenced | 38807 | 24.804 |
| skill | 1 | valid | fenced | 57598 | 25.668 |
| skill | 2 | valid | fenced | 58038 | 27.004 |
| skill | 3 | valid | fenced | 57595 | 25.983 |
