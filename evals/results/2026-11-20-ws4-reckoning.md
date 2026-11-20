# WS4: Repository reckoning behavioral acceptance

Two paired runs reviewed hoa at `fd3bd52` with Codex and `gpt-6.2-sol`.
Neither round used `gh` or host/runtime inventory. Round 1 had no web search;
both arms in round 2 had web search via `ghc-search`, and the skill arm used
the revised workflow.

| Round | Arm | Full recall | Weighted recall | A1 / A2 / B1 | Verification discipline | Uncached tokens (including sub-agents) |
|---|---|---:|---:|---|---|---:|
| 1 | Skill | 2/24 | 2.5/24 | full / none / none | Independent checks documented for 6/6 findings | 1,286,969 |
| 1 | Plain prompt | 2/24 | 4.5/24 | full / none / none | 12/12 verdicts, no separate verifier artifacts | 207,149 |
| 2 | Revised skill | 3/24 | 5.0/24 | full / none / none | Independent checks documented for 10/10 findings | 2,720,349 |
| 2 | Plain prompt | 4/24 | 6.5/24 | full / none / none | 12/12 verdicts, source cross-checks but no per-finding verifier artifacts | 203,466 |

Weighted recall counts a full match as 1 and a partial match as 0.5. The
24-item key came from a Claude Code review with `gh`, web, host inventory, and
live-session evidence. That evidence mismatch limits what the scores say about
absolute recall under either round's conditions.

**Owner decision (2026-11-20):** Both skill runs failed acceptance and trailed
the plain prompt on weighted recall while using 6.2x and 13.4x its uncached
tokens. The panel's only advantage was documented per-finding independent
verification. Keep the name as a hidden, explicit prompt shortcut; retire the
panel and ledger workflow for this skill.
