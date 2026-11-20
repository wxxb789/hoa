# review-revision-candidates

Verdict: **no-difference** (codex, forced, k=3).
Model: `gpt-6.2-sol`; CLI: `codex-cli 0.171.0`; skill: `review-revision-candidates` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 486111.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 37545 | 15.493 |
| none | 2 | valid | bare | 37592 | 15.221 |
| none | 3 | valid | bare | 37558 | 15.146 |
| terse | 1 | valid | bare | 52436 | 21.03 |
| terse | 2 | valid | bare | 51918 | 18.605 |
| terse | 3 | valid | bare | 37582 | 15.033 |
| skill | 1 | valid | bare | 73963 | 30.038 |
| skill | 2 | valid | bare | 79327 | 37.302 |
| skill | 3 | valid | bare | 78190 | 28.533 |
