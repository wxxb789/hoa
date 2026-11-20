# B8: orchestration comparison on a real goal, 2026-11-20

Goal: release retired account queues in `wxxb789/ghc-proxy` (`docs/TODO.md:13`), from frozen baseline `a65f826`
(v0.12.5). Both candidates received the same goal contract, the same author model (Codex `gpt-6.2-sol`, medium) and
pre-installed dependencies in separate worktrees, and ran serially on one Windows host. Results were compared, not
merged. A common reviewer ran the goal gate, a held-out acceptance test, a retention probe and scratch risk tests on both.
The originally chosen goal (an `anc` SQLite artifact) was withdrawn in its plan, and `no-mistakes` was deferred for
budget.

| | Native Paseo (`create_agent`) | gdd (Codex route) |
|---|---|---|
| Wall time | about 3.5 min | about 34 min |
| Uncached tokens | 78k | 738k (operator plus 7 launched runs) |
| Runs | 1 | 4 authoring, 1 simplify, 2 review |
| Defects found and fixed inside the workflow | 0 | 3 (2 real defects) |
| Goal gate and held-out test | pass | pass |
| Retention probe (baseline: 4 retired queues updated) | 1 | 1 |
| Explicit `undefined` drops an earlier override (also in baseline) | low | low |
| Queue warmed before publish misses earlier updates | medium | low |

Reading: on a 1-2 hour change, gdd's review loop caught real defects and lowered one remaining defect from medium to
low, at about ten times the wall time and tokens. Neither workflow caught the inherited `undefined` override defect.
One goal and one run per arm: this is a case study, not a benchmark.
