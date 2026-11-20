# B8: orchestration comparison on a real goal, 2026-11-20

Goal: release retired account queues in `wxxb789/ghc-proxy` (`docs/TODO.md:13`), from frozen baseline `a65f826`
(v0.12.5). Both candidates received the same goal contract, the same author model (Codex `gpt-6.2-sol`, medium) and
pre-installed dependencies in separate worktrees, and ran serially on one Windows host. Results were compared, not
merged. A common reviewer ran the goal gate, a held-out acceptance test, a retention probe and scratch risk tests on both.
The originally chosen goal (an `anc` SQLite artifact) was withdrawn in its plan. A `no-mistakes` arm was added on
2026-11-21 (see below).

| | Native Paseo (`create_agent`) | gdd (Codex route) | no-mistakes |
|---|---|---|---|
| Wall time | about 3.5 min | about 34 min | about 40 min (incl. setup retries) |
| Uncached tokens | 78k | 738k (operator plus 7 launched runs) | not measured |
| Runs | 1 | 4 authoring, 1 simplify, 2 review | 1 authoring; review stage failed (provider 403) |
| Defects found and fixed inside the workflow | 0 | 3 (2 real defects) | 0 |
| Goal gate and held-out test | pass | pass | pass |
| Retention probe (baseline: 4 retired queues updated) | 1 | 1 | not run |
| Explicit `undefined` drops an earlier override (also in baseline) | low | low | low |
| Queue warmed before publish misses earlier updates | medium | low | medium |

Reading: on a 1-2 hour change, gdd's review loop caught real defects and lowered one remaining defect from medium to
low, at about ten times the wall time and tokens. Neither workflow caught the inherited `undefined` override defect.
One goal and one run per arm: this is a case study, not a benchmark.

The `no-mistakes` arm (local gate only; rebase, push, PR and CI stages skipped) produced a passing fix with its own
regression test, but its review stage never ran: the review agent requested `gpt-6.2-sol` through a provider that
returned 403. With no review, its result matches native Paseo on every common check, at roughly ten times the wall time,
most of it gate setup and daemon retries.
