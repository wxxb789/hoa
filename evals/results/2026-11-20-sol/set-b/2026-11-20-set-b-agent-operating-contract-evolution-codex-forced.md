# set-b-agent-operating-contract-evolution

Verdict: **no-difference** (codex, forced, k=3).
Model: `gpt-6.2-sol`; CLI: `codex-cli 0.171.0`; skill: `agent-operating-contract-evolution` rev 6.

Thresholds: `{"max_terse_gap": 0.05, "min_mean_gain": 0.1, "min_natural_load_rate": 1.0, "min_pass_rate": 1.0}`.

- none: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- terse: 3/3 passed; loaded 0; pass^k: True; mean score: 1.0; sample stddev: 0.0.
- skill: 3/3 passed; loaded 3; pass^k: True; mean score: 1.0; sample stddev: 0.0.

CLI-reported tokens: 425538.

| Arm | Trial | Validity | Answer format | Tokens | Seconds |
|---|---:|---|---|---:|---:|
| none | 1 | valid | bare | 37530 | 18.481 |
| none | 2 | valid | bare | 37609 | 17.841 |
| none | 3 | valid | bare | 37496 | 18.362 |
| terse | 1 | valid | bare | 37961 | 19.341 |
| terse | 2 | valid | bare | 38057 | 21.4 |
| terse | 3 | valid | bare | 37843 | 18.157 |
| skill | 1 | valid | bare | 66395 | 25.725 |
| skill | 2 | valid | bare | 66198 | 25.229 |
| skill | 3 | valid | bare | 66449 | 20.194 |
