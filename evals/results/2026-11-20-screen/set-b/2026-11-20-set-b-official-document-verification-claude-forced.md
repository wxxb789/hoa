# set-b-official-document-verification

Verdict: **skill-wins** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `official-document-verification` rev 5.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- terse: 1/3 passed; loaded 0; pass^k: False; mean score: 0.7777777777777778; sample stddev: 0.1924500897298753.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 309902.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 27951 | 18.004 |
| none | 2 | valid | bare | 27998 | 15.216 |
| none | 3 | valid | bare | 28089 | 17.399 |
| terse | 1 | valid | bare | 27973 | 15.701 |
| terse | 2 | valid | fenced | 28468 | 19.049 |
| terse | 3 | valid | bare | 27964 | 16.843 |
| skill | 1 | valid | bare | 32905 | 16.428 |
| skill | 2 | valid | bare | 54089 | 20.448 |
| skill | 3 | valid | fenced | 54465 | 21.843 |
