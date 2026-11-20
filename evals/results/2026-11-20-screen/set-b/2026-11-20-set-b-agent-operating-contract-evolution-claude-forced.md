# set-b-agent-operating-contract-evolution

Verdict: **inconclusive** (claude, forced, k=3).
Model: `claude-haiku-5.5`; CLI: `2.1.329 (Claude Code)`; skill: `agent-operating-contract-evolution` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 1/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- terse: 0/3 passed; loaded 0; pass^k: None; mean score: None; sample stddev: None.
- skill: 0/3 passed; loaded 3; pass^k: None; mean score: None; sample stddev: None.

CLI-reported tokens: 351033.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | fenced | 27251 | 15.57 |
| none | 2 | control skill access | fenced | 27718 | 15.005 |
| none | 3 | valid | fenced | 37573 | 18.487 |
| terse | 1 | valid | fenced | 35780 | 17.263 |
| terse | 2 | valid | bare | 28358 | 17.0 |
| terse | 3 | control skill access | bare | 36432 | 19.037 |
| skill | 1 | agent failed (exit 1) | none | 61192 | 15.806 |
| skill | 2 | valid | fenced | 48245 | 18.966 |
| skill | 3 | valid | bare | 48484 | 20.989 |
