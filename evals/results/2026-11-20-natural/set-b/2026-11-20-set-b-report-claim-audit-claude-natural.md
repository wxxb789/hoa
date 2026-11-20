# set-b-report-claim-audit

Verdict: **inconclusive** (claude, natural, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `report-claim-audit` rev 2.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 2/3 passed; loaded 0; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.1924500897298753.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- skill: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.

CLI-reported tokens: 344696.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 38346 | 17.841 |
| none | 2 | valid | fenced | 38162 | 16.441 |
| none | 3 | valid | bare | 38251 | 16.961 |
| terse | 1 | valid | bare | 38997 | 18.986 |
| terse | 2 | valid | bare | 38906 | 18.171 |
| terse | 3 | valid | fenced | 37255 | 14.688 |
| skill | 1 | valid | fenced | 37566 | 15.768 |
| skill | 2 | valid | fenced | 38574 | 17.545 |
| skill | 3 | valid | fenced | 38639 | 18.005 |
