# Necessity screening, 2026-11-20

Claude Code with `claude-haiku-5.5`, forced mode, three arms (`none`, `terse`, `skill`), N=3 per arm, on the frozen
task sets A (`evals/tasks/`) and B (`evals/tasks/set-b/`, tree `34c1f567635a`). Screening is cheap and coarse: a
`no-difference` verdict at N=3 does not show a skill is unnecessary.

The first pass (`set-a/`, `set-b/`) invalidated control trials that merely searched for the skill. The runner fix
(#110, result schema 3) separates probes from contamination; the eight affected task sets were rerun once, unchanged,
into `rerun/`. Where a rerun exists it supersedes the first-pass file.

| Verdict | Subject (set) |
|---|---|
| `skill-wins` | report-claim-audit (B), official-document-verification (B), hoa-skill-curate (B), ghc-search (B, rerun) |
| `inconclusive` | agent-operating-contract-evolution (B, rerun: one `none` trial exited 1) |
| `no-difference` | the other 29 subject-set pairs |

Lower mean checks for the `skill` arm below the verdict threshold, queued for the stronger-model re-check:
evidence-backed-analytical-writing (A: 4/6 vs 6/6), hoa-skill-review (B, first pass: 2/4 vs 4/4 for `none`),
review-revision-candidates (B: 0.67/3 vs 2.33/3).

Token use (input + output + cache creation; cache reads separate): first pass 3,164,546 uncached and 10,037,043 cache
read; reruns 770,933 uncached and 2,477,872 cache read.
