# Necessity and WS4 pilots: 2026-11-20

Runner, tasks, and fixtures: commit `5290f64b366b42845ed41e1ec6c46340e632e0e0`.
Native Windows, Claude Code 2.1.328, `claude-haiku-5.5`, low effort. Every trial
had a fresh temporary profile and synthetic fixture, with no web, shell,
workers, or MCP servers. The old artifacts were removed because they were
produced by an earlier runner and included an unredacted host path. The WS4
rerun uses the corrected fixed-directory task from the original pilot.

Run these commands from the repository root at the pinned commit, with the
same Claude Code model and an authorized endpoint configured:

```sh
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --model claude-haiku-5.5 --repeats 1 --max-turns 10 --max-budget-usd 0.75 --timeout 300
uv run --script evals/run_necessity_eval.py evals/tasks/ws4-fallback-fixed-paths.json --model claude-haiku-5.5 --repeats 1 --max-turns 24 --max-budget-usd 1.50 --timeout 300 --acceptance
```

Use `--results DIR` to avoid existing result files. The commands reproduce the
setup and scoring, not identical model responses.

| Pilot | Result | Tokens | CLI cost |
|---|---|---:|---:|
| [Claim audit, installed](2026-11-20-claim-audit.json) | 5/5, no observed skill load | 26,904 | $0.00223 |
| [Claim audit, baseline](2026-11-20-claim-audit.json) | 5/5, no observed skill access | 27,148 | $0.00170 |
| [WS4 fallback, fixed paths](2026-11-20-ws4-fallback-fixed-paths.json) | 3/3, observed skill load | 100,512 | $0.00579 |

Total: **154,564 tokens** against a 150,000-350,000 estimate and a roughly
1,000,000-token stop. Counts are CLI-reported input, output, cache creation,
and cache reads. CLI cost is an estimate, not the bill. The baseline reported
`num_turns: 11` despite the runner passing `--max-turns 10`; the recorded
limit is the requested CLI setting.

**Necessity: inconclusive.** One pair (`k=1`), `report-claim-audit` revision 2.
Both arms corrected the count, omissions, unaccepted entry, and pending
decision, and both withheld signoff. No tool trace showed the installed arm
loading the skill. This does not distinguish an ineffective skill from a
ceiling effect or a treatment that never reached the model.

**WS4: marker acceptance passed.** The trace records a successful load of
`hoa-repo-reckoning` revision 2. The collected report and scope match the
`verification: single-context` and external-lane markers in the rubric.
This was a synthetic snapshot, not a live repository audit. The report was
hand-written without `findings.py`, a ledger, or an independent verifier;
the runner did not independently verify the model's claim that it left the
subject unchanged.
