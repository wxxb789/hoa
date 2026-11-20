# evidence-backed-analytical-writing

Verdict: **no-difference** (codex, forced, k=3).
Model: `gpt-6.2-sol`; CLI: `codex-cli 0.171.0`; skill: `evidence-backed-analytical-writing` rev 3.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 425739.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 36914 | 17.844 |
| none | 2 | valid | bare | 36803 | 14.938 |
| none | 3 | valid | bare | 36983 | 16.936 |
| terse | 1 | valid | bare | 50320 | 16.561 |
| terse | 2 | valid | bare | 37294 | 16.816 |
| terse | 3 | valid | bare | 48925 | 16.418 |
| skill | 1 | valid | bare | 58871 | 22.19 |
| skill | 2 | valid | bare | 60052 | 19.873 |
| skill | 3 | valid | bare | 59577 | 20.986 |
