# Necessity and WS4 pilots: 2026-11-19

Source checkout: `db7761c`. Runner: native Windows, Claude Code 2.1.328,
`claude-haiku-5.5`, low effort. Fresh temporary profile and synthetic fixture
for every trial. No web, shell, workers or MCP servers were available to the
agent. Counts below include input, cache creation, cache reads and output
reported by the CLI; cost is the CLI estimate, not the bill.

| Pilot | Result | Tokens | CLI cost |
|---|---|---:|---:|
| [Claim audit, installed](2026-11-19-claim-audit.json) | 5/5, no observed skill load | 24,504 | $0.00197 |
| [Claim audit, baseline](2026-11-19-claim-audit.json) | 5/5, no skill access in trace | 24,603 | $0.00150 |
| [WS4 fallback, first attempt](2026-11-19-ws4-fallback.json) | 0/2; artifact paths did not match the rubric | 111,553 | $0.00767 |
| [WS4 fallback, fixed paths](2026-11-19-ws4-fallback-fixed-paths.json) | 3/3; both markers verified in files | 93,628 | $0.00493 |

Total: **254,288 tokens**. Before execution, the plan was 300k–800k tokens
with a roughly 2M-token stop, up to 10 turns and $0.75 per claim arm,
and up to 24 turns and $1.50 per WS4 invocation. The WS4 retry used the
same bounds.

**Necessity: inconclusive.** One pair (`k=1`), `report-claim-audit` revision
2. Both arms corrected the count, the omitted and unaccepted items and the
pending decision; both withheld signoff. No tool trace showed the installed
arm reading the skill. This does not distinguish an ineffective skill from
a ceiling effect or an unexposed treatment, and is not grounds to retire it.
The qualitative recommendation was retained but not scored.

**WS4 §9.2: marker behavior passed on a small synthetic snapshot**, not the
live cockpit repo. The first prompt allowed a nested audit directory, which
the rubric did not collect. Its reported outputs could not be verified and
the initial failure is retained. The retry fixed the handoff paths before
running. The successful trace shows a direct read of `SKILL.md` for
`hoa-repo-reckoning` revision 2; the report opens with
`verification: single-context`, and the scope and report mark the external
lane not run. The report's two cited observations match the fixture's
README and workflow. It was hand-written without `findings.py`, ledger,
or a separate critic/verifier pass. The model reported leaving the subject
untouched; this run did not independently verify the scratch subject after
the agent exited. This is not a full panel, reproduction, or follow-through
acceptance, and does not establish a gdd versus alternative-runner result.
