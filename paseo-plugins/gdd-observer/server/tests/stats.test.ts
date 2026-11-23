import { describe, expect, it } from "vitest";
import type { RunSummary } from "../../shared/runs";
import { summarizeRuns } from "../../shared/stats";

function run(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "2026-11-14/stage-implement",
    date: "2026-11-14",
    slug: "stage-implement",
    name: "stage-implement",
    runDir: "C:\\runs\\2026-11-14\\stage-implement",
    state: "running",
    liveness: "running",
    finalized: false,
    exitCode: null,
    startedAt: "2026-11-14T00:00:00+00:00",
    endedAt: null,
    durationS: null,
    elapsedS: 60,
    model: {
      requested: null,
      requestedProvider: null,
      requestedModel: null,
      thinking: null,
      observed: [],
    },
    maxTime: null,
    sessionId: null,
    turns: null,
    toolCalls: null,
    costUsd: null,
    countersFrom: "none",
    countersPartial: false,
    currentTool: null,
    currentToolIntent: null,
    lastError: null,
    errorCount: 0,
    answerChars: null,
    hasAnswer: false,
    eventsBytes: 0,
    eventsDroppedBytes: 0,
    eventsTruncated: false,
    eventLines: 0,
    pids: { pid: null, agentPid: null },
    livePids: [],
    lastEventAt: null,
    dirModifiedAt: null,
    warnings: [],
    ...overrides,
  };
}

describe("summarizeRuns", () => {
  it("counts every state and liveness verdict, including the ones that never occur", () => {
    const stats = summarizeRuns([
      run(),
      run({ state: "done", liveness: "settled", exitCode: 0 }),
      run({ state: "failed", liveness: "settled", exitCode: 1 }),
      run({ state: "killed", liveness: "settled", exitCode: 130 }),
      run({ state: "running", liveness: "stale" }),
      run({ state: "unknown", liveness: "unknown" }),
    ]);
    expect(stats.total).toBe(6);
    expect(stats.byState).toEqual({ running: 2, done: 1, killed: 1, failed: 1, unknown: 1 });
    expect(stats.byLiveness).toEqual({ running: 1, settled: 3, stale: 1, unknown: 1 });
  });

  it("adds only what a run reports and counts the runs that reported", () => {
    const stats = summarizeRuns([
      run({ turns: 3, toolCalls: 7, costUsd: 0.25 }),
      run({ turns: null, toolCalls: null, costUsd: null }),
      run({ turns: 1, toolCalls: 2, costUsd: 0.05 }),
    ]);
    expect(stats.turns).toBe(4);
    expect(stats.toolCalls).toBe(9);
    expect(stats.costUsd).toBeCloseTo(0.3, 6);
    expect(stats.countedRuns).toBe(2);
  });

  it("counts partial counters separately from the totals", () => {
    const stats = summarizeRuns([
      run({ turns: 2, countersPartial: false }),
      run({ turns: 5, countersPartial: true }),
      run({ countersPartial: false }),
    ]);
    expect(stats.turns).toBe(7);
    expect(stats.partialRuns).toBe(1);
  });

  it("flags every run carrying at least one warning", () => {
    const stats = summarizeRuns([
      run(),
      run({ warnings: ["state-missing"] }),
      run({ warnings: ["log-truncated", "no-pids"] }),
    ]);
    expect(stats.flagged).toBe(2);
  });

  it("reports an empty scan as zeros rather than as absent fields", () => {
    const stats = summarizeRuns([]);
    expect(stats.total).toBe(0);
    expect(stats.byState).toEqual({ running: 0, done: 0, killed: 0, failed: 0, unknown: 0 });
    expect(stats.byLiveness).toEqual({ running: 0, settled: 0, stale: 0, unknown: 0 });
    expect(stats.flagged).toBe(0);
  });
});
