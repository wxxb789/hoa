# set-b-agent-operating-contract-evolution

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `agent-operating-contract-evolution` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 1/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 2/3 passed; loaded 0; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.1924500897298753.
- skill: 2/3 passed; loaded 3; pass^k: False; mean score: 0.8888888888888888; sample stddev: 0.1924500897298753.

CLI-reported tokens: 340122.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 27211 | 14.873 |
| none | 2 | valid | fenced | 37413 | 16.626 |
| none | 3 | agent failed (exit 1) | none | 37286 | 17.818 |
| terse | 1 | valid | bare | 27649 | 15.33 |
| terse | 2 | valid | bare | 27573 | 16.182 |
| terse | 3 | valid | fenced | 37812 | 18.356 |
| skill | 1 | valid | bare | 47920 | 17.212 |
| skill | 2 | valid | fenced | 48548 | 19.313 |
| skill | 3 | valid | fenced | 48710 | 20.115 |
