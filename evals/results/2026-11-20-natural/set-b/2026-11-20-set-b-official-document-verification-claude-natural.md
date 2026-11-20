# set-b-official-document-verification

Verdict: **inconclusive** (claude, natural, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `official-document-verification` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- terse: 0/3 passed; loaded 0; pass^k: False; mean score: 0.6666666666666666; sample stddev: 0.0.
- skill: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.

CLI-reported tokens: 264440.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 28003 | 17.019 |
| none | 2 | valid | bare | 28156 | 17.449 |
| none | 3 | valid | bare | 28125 | 18.149 |
| terse | 1 | valid | fenced | 28175 | 16.724 |
| terse | 2 | valid | fenced | 28129 | 15.403 |
| terse | 3 | valid | bare | 40710 | 24.322 |
| skill | 1 | valid | bare | 27742 | 14.535 |
| skill | 2 | valid | fenced | 27617 | 16.148 |
| skill | 3 | valid | fenced | 27783 | 17.274 |
