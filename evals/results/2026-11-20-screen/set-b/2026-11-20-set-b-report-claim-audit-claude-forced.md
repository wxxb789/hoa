# set-b-report-claim-audit

Verdict: **skill-wins** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `report-claim-audit` rev 2.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.1924500897298753.
- terse: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 426101.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 36929 | 16.359 |
| none | 2 | valid | bare | 38259 | 17.376 |
| none | 3 | valid | fenced | 51493 | 27.256 |
| terse | 1 | valid | fenced | 38948 | 19.818 |
| terse | 2 | valid | bare | 49370 | 22.704 |
| terse | 3 | valid | fenced | 38611 | 17.428 |
| skill | 1 | valid | bare | 57536 | 23.888 |
| skill | 2 | valid | bare | 57422 | 23.415 |
| skill | 3 | valid | fenced | 57533 | 24.219 |
