# agent-operating-contract-evolution

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `agent-operating-contract-evolution` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 2/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 764075.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | none | 53848 | 19.23 |
| none | 2 | valid | none | 102019 | 29.457 |
| none | 3 | valid | none | 91207 | 29.489 |
| terse | 1 | control skill access | none | 71112 | 28.654 |
| terse | 2 | valid | none | 68251 | 28.591 |
| terse | 3 | valid | none | 79743 | 32.194 |
| skill | 1 | valid | none | 86718 | 33.904 |
| skill | 2 | valid | none | 124756 | 37.768 |
| skill | 3 | valid | none | 86421 | 32.029 |
