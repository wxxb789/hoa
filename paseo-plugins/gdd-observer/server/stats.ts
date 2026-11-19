import type { RunStats, RunSummary } from "../shared/runs";

export function summarizeRuns(runs: readonly RunSummary[]): RunStats {
  const byState: RunStats["byState"] = { running: 0, done: 0, killed: 0, failed: 0, unknown: 0 };
  const byLiveness: RunStats["byLiveness"] = {
    running: 0,
    settled: 0,
    stale: 0,
    unknown: 0,
  };
  let turns = 0;
  let toolCalls = 0;
  let costUsd = 0;
  let countedRuns = 0;
  let partialRuns = 0;
  let flagged = 0;

  for (const run of runs) {
    byState[run.state] += 1;
    byLiveness[run.liveness] += 1;
    turns += run.turns ?? 0;
    toolCalls += run.toolCalls ?? 0;
    costUsd += run.costUsd ?? 0;
    if (run.turns !== null || run.toolCalls !== null || run.costUsd !== null) countedRuns += 1;
    if (run.countersPartial) partialRuns += 1;
    if (run.warnings.length > 0) flagged += 1;
  }

  return {
    total: runs.length,
    byState,
    byLiveness,
    turns,
    toolCalls,
    costUsd,
    countedRuns,
    partialRuns,
    flagged,
  };
}
