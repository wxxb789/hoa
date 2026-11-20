# set-b-hoa-skill-review

Verdict: **no-difference** (codex, forced, k=3).
Model: `gpt-6.2-sol`; CLI: `codex-cli 0.171.0`; skill: `hoa-skill-review` rev 4.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 568043.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 36940 | 14.224 |
| none | 2 | valid | bare | 36927 | 14.284 |
| none | 3 | valid | bare | 36962 | 13.577 |
| terse | 1 | valid | bare | 37193 | 14.186 |
| terse | 2 | valid | bare | 37159 | 14.858 |
| terse | 3 | valid | bare | 37106 | 15.965 |
| skill | 1 | valid | bare | 124830 | 49.819 |
| skill | 2 | valid | bare | 147071 | 45.554 |
| skill | 3 | valid | bare | 73855 | 26.819 |
