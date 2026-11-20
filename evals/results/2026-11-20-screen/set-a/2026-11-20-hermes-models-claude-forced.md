# hermes-models

Verdict: **no-difference** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `hermes-models` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.9629629629629629; sample stddev: 0.06415002990995845.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 608275.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 42855 | 21.554 |
| none | 2 | valid | fenced | 42770 | 14.904 |
| none | 3 | valid | fenced | 53769 | 17.777 |
| terse | 1 | valid | bare | 62838 | 19.852 |
| terse | 2 | valid | bare | 43546 | 16.632 |
| terse | 3 | valid | fenced | 54037 | 18.15 |
| skill | 1 | valid | fenced | 83692 | 19.554 |
| skill | 2 | valid | fenced | 98141 | 23.388 |
| skill | 3 | valid | fenced | 126627 | 26.851 |
