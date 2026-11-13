# Phase 2 — verify before believing anything

The agent's report is a claim, never evidence:

- Settle the tree before gating: sample `git status --porcelain` and the newest mtime under changed
  paths twice a few seconds apart, and run gates only when both samples match. A failure within seconds
  of a `done` report is suspect by default — re-run once on the settled tree before calling it real.
- **Resolve local gate concurrency from the project profile, not from CI's default.** Take the worker
  count from the profile or a `GDD_*` key with a conservative documented default; on a host smaller than
  the CI runner, the default parallelism triggers an OOM kill that reads like a code regression. Record
  the resolved value with the gate evidence, so two runs of one commit can be compared honestly.
- If an interrupted gate did not reach its `restore` step, the artifact directory is dirty (a half-built
  `dist/`); restore it before re-running.
- Read model and provider metadata early before `events.ndjson` truncates (`events_truncated`); when the
  run record says `model: null`, cite the CLI config's default as config default, never as the run's fact.
- Run the repo's gates yourself and read real exit codes.
- **Exit 0 means the process ended, not that the phase finished.** Read the run's final assistant text
  (`answer.md`): a report ending with "the gate is running, waiting for its result" ended mid-gate.
  Resume it, or run the remaining gates yourself — never accept the exit code as completion.
- **A non-zero gate that names a missing build output is a prerequisite failure, not a regression.**
  Read the message before calling it a delta; produce the artifacts and re-run.
- Map every contract clause to a test name or evidence row; a clause with no test is unfinished work.
- **A proof test is only proof if it fails when the feature is deleted.** A loop over a collection
  that is empty without the feature, an input that already declares the value the assertion demands,
  and an assertion that reads the same source the code reads all stay green with the change reverted.
  Vacuous coverage is the one defect that hides every other defect in the same file.
- **An assertion that only checks a count is not verification.** A clause "proven" by
  `assert(checks > 0)` stays green after the entire section it guards is deleted — read the
  assertion's substance, not its existence. Raise a weak proof test as its own increment and tell the
  operator; do not let it be absorbed silently into the current apply round.
- Diff the plan's file list against `git status`; missing tests or docs are the usual gap.
- Re-run gates on the FINAL tree, even if they passed earlier — a resumed run keeps adding code and
  the counts move.
- Research-outcome increment: the deliverable is a decision, not a feature →
  [`references/evidence-fairness.md`](../evidence-fairness.md) before accepting any
  "faster/cheaper" claim.

## When a gate is red for a reason the change did not cause

Gate red for a reason the change did not cause, on a branch that must ship: fix it as its own
commit and disclose it — decide, don't silently absorb.

## Pitfalls this phase answers

- **A non-zero gate exit does not say *why*.** Wrappers flatten "the tool is missing", "the machine
  killed the process" and "the code regressed" into the same `exit 1` — observed in three repos, where
  a missing `omp`/`bun`/pinned `gitleaks` and a SIGKILL both read as a red suite. Before dispatching a
  `fix` round on `rc=1`, grep the gate output for prerequisite markers (`not found`, `command not found`,
  `is required to run`, `requires Gitleaks`, `ENOENT`, a missing `bin/`/`dist/`), check for a signal or
  an OOM kill (`exit 137`, `-9`, `status: null`, a `dmesg`/`Killed` line), and only then treat it as a
  code failure. Export the project's toolchain `PATH` (mise shims, `DOTNET_ROOT`, `GITLEAKS_VERSION`) in
  the **same subshell** as the gate command — a fix dispatched against a missing tool burns a round for
  nothing.
- **A self-reported "done" with no gate output is unverified.** Ask for exit codes, then run them.
- **Put the project's own toolchain first on `PATH` before running its gates.** An ambient interpreter
  below the project's floor fails in a way that reads like a code defect.
