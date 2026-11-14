import { describe, expect, it } from "vitest";
import { mapRun, type RunFiles } from "../state";
import { applyEventLine, createCounters, snapshotCounters, type CounterSnapshot } from "../events";
import type { PidVerdict } from "../liveness";

const NOW = Date.parse("2026-11-14T00:30:00.000Z");
const DIR = "C:\\runs\\2026-11-14\\stage-implement";

function files(overrides: Partial<RunFiles> = {}): RunFiles {
  return {
    dir: DIR,
    date: "2026-11-14",
    slug: "stage-implement",
    state: {
      present: true,
      readable: true,
      values: {
        name: "stage-implement",
        state: "running",
        started: "2026-11-14T00:00:00+00:00",
        model: "provider/model",
        thinking: "max",
        pid: 111,
        agent_pid: 222,
      },
    },
    lock: { pid: 111, agentPid: 222, backend: "windows", startedAt: "2026-11-14T00:00:00+00:00" },
    finalized: { present: false, exitCode: null },
    stats: null,
    answer: { exists: false, bytes: null },
    events: { exists: true, bytes: 4096, readable: true },
    sessionIdFromFile: null,
    dirModifiedAt: "2026-11-14T00:29:00.000Z",
    ...overrides,
  };
}

function counters(overrides: Partial<CounterSnapshot> = {}): CounterSnapshot {
  return {
    hasCounters: true,
    turns: 3,
    toolCalls: 7,
    costUsd: 0.25,
    errorCount: 0,
    lastError: null,
    currentTool: null,
    lastEventAt: "2026-11-14T00:29:30.000Z",
    lines: 120,
    badLines: 0,
    truncated: false,
    droppedBytes: 0,
    ...overrides,
  };
}

function verdicts(alive: number[]): Map<number, PidVerdict> {
  return new Map(alive.map((pid) => [pid, "alive" as PidVerdict]));
}

describe("mapRun", () => {
  it("keeps metrics unavailable for an adapter-shaped lifecycle-only event stream", () => {
    const parsed = createCounters();
    applyEventLine(parsed, JSON.stringify({
      type: "paseo_status",
      at: "2026-11-14T00:29:30.000Z",
      state: "running",
      status: "running",
    }));
    const summary = mapRun({
      files: files({
        state: { present: true, readable: true, values: { backend: "paseo", state: "running" } },
        lock: null,
      }),
      counters: snapshotCounters(parsed),
      verdicts: new Map(),
    }, NOW);
    expect(summary.eventLines).toBe(1);
    expect({
      turns: summary.turns,
      toolCalls: summary.toolCalls,
      costUsd: summary.costUsd,
      countersFrom: summary.countersFrom,
    }).toEqual({ turns: null, toolCalls: null, costUsd: null, countersFrom: "none" });
  });

  it("reports a live process as running with counters derived from the event log", () => {
    const summary = mapRun({ files: files(), counters: counters(), verdicts: verdicts([222]) }, NOW);
    expect(summary.state).toBe("running");
    expect(summary.liveness).toBe("running");
    expect(summary.livePids).toEqual([222]);
    expect(summary.countersFrom).toBe("events");
    expect(summary.turns).toBe(3);
    expect(summary.toolCalls).toBe(7);
    expect(summary.costUsd).toBe(0.25);
    expect(summary.elapsedS).toBe(1800);
    expect(summary.warnings).toEqual([]);
  });

  it("uses launcher measurements instead of lifecycle-only event counters", () => {
    const parsed = createCounters();
    applyEventLine(parsed, JSON.stringify({ type: "paseo_status", state: "running", status: "running" }));
    const summary = mapRun({
      files: files({
        state: { present: true, readable: true, values: { turns: 2, tool_calls: 4, cost_usd: 0.1 } },
      }),
      counters: snapshotCounters(parsed),
      verdicts: new Map(),
    }, NOW);
    expect(summary.countersFrom).toBe("state");
    expect(summary.turns).toBe(2);
    expect(summary.toolCalls).toBe(4);
    expect(summary.costUsd).toBe(0.1);
  });

  it("reports measured zeros once a recognized agent event stream is available", () => {
    const parsed = createCounters();
    applyEventLine(parsed, JSON.stringify({ type: "session", id: "s1" }));
    const summary = mapRun({ files: files(), counters: snapshotCounters(parsed), verdicts: new Map() }, NOW);
    expect(summary.countersFrom).toBe("events");
    expect(summary.turns).toBe(0);
    expect(summary.toolCalls).toBe(0);
    expect(summary.costUsd).toBe(0);
  });

  it("prefers launcher counters once the run finalized", () => {
    const summary = mapRun(
      {
        files: files({
          state: {
            present: true,
            readable: true,
            values: {
              name: "stage-implement",
              state: "done",
              exit: 0,
              duration_s: 90.5,
              turns: 9,
              tool_calls: 21,
              cost_usd: 0.5,
              answer_chars: 42,
            },
          },
          finalized: { present: true, exitCode: 0 },
          answer: { exists: true, bytes: 42 },
        }),
        counters: counters({ turns: 1, toolCalls: 2, costUsd: 0.01 }),
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.state).toBe("done");
    expect(summary.liveness).toBe("settled");
    expect(summary.countersFrom).toBe("state");
    expect(summary.turns).toBe(9);
    expect(summary.toolCalls).toBe(21);
    expect(summary.durationS).toBe(90.5);
    expect(summary.answerChars).toBe(42);
    expect(summary.hasAnswer).toBe(true);
  });

  it("treats finalized as authoritative over a stale running state", () => {
    const summary = mapRun(
      {
        files: files({ finalized: { present: true, exitCode: 130 } }),
        counters: counters(),
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.state).toBe("killed");
    expect(summary.liveness).toBe("settled");
    expect(summary.exitCode).toBe(130);
  });

  it("classifies failed runs from the exit code", () => {
    const summary = mapRun(
      {
        files: files({
          state: { present: true, readable: true, values: { name: "x", state: "running" } },
          finalized: { present: true, exitCode: 2 },
        }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.state).toBe("failed");
    expect(summary.countersFrom).toBe("none");
    expect(summary.turns).toBeNull();
  });

  it("reports a dead process without finalized as stale, never done", () => {
    const summary = mapRun(
      {
        files: files(),
        counters: counters(),
        verdicts: new Map([
          [111, "dead"],
          [222, "dead"],
        ]),
      },
      NOW,
    );
    expect(summary.liveness).toBe("stale");
    expect(summary.state).toBe("running");
    expect(summary.livePids).toEqual([]);
  });

  it("keeps liveness unknown when the probe cannot prove death", () => {
    const summary = mapRun(
      {
        files: files(),
        counters: counters(),
        verdicts: new Map([[111, "dead"], [222, "unknown"]]),
      },
      NOW,
    );
    expect(summary.liveness).toBe("unknown");
    expect(summary.warnings).toContain("liveness-unknown");
  });

  it("reports a missing state.json as unknown rather than success", () => {
    const summary = mapRun(
      {
        files: files({
          state: { present: false, readable: false, values: {} },
          lock: null,
          events: { exists: true, bytes: 0, readable: true },
        }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.state).toBe("unknown");
    expect(summary.liveness).toBe("unknown");
    expect(summary.exitCode).toBeNull();
    expect(summary.warnings).toContain("state-missing");
    expect(summary.warnings).toContain("no-pids");
  });

  it("flags an unreadable state.json and an unreadable log", () => {
    const summary = mapRun(
      {
        files: files({
          state: { present: true, readable: false, values: {} },
          events: { exists: true, bytes: 12, readable: false },
          lock: null,
        }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.warnings).toContain("state-unreadable");
    expect(summary.warnings).toContain("log-unreadable");
  });

  it("accounts for truncation from state, stats sidecar, and the splice marker", () => {
    const summary = mapRun(
      {
        files: files({
          state: {
            present: true,
            readable: true,
            values: { name: "x", state: "running", pid: 111, events_dropped_bytes: 1000 },
          },
          stats: { totalBytes: 9000, retainedBytes: 8000, droppedBytes: 2500, truncated: true },
        }),
        counters: counters({ truncated: true, droppedBytes: 1500, currentTool: { name: "bash", intent: "Run tests" } }),
        verdicts: verdicts([111]),
      },
      NOW,
    );
    expect(summary.eventsTruncated).toBe(true);
    expect(summary.eventsDroppedBytes).toBe(2500);
    expect(summary.countersPartial).toBe(true);
    expect(summary.warnings).toContain("log-truncated");
    expect(summary.currentTool).toBe("bash");
    expect(summary.currentToolIntent).toBe("Run tests");
  });

  it("exposes the last error from counters over the state file", () => {
    const summary = mapRun(
      {
        files: files({
          state: {
            present: true,
            readable: true,
            values: { name: "x", state: "running", pid: 111, errors: ["older failure"] },
          },
        }),
        counters: counters({ errorCount: 2, lastError: "newest failure" }),
        verdicts: verdicts([111]),
      },
      NOW,
    );
    expect(summary.lastError).toBe("newest failure");
    expect(summary.errorCount).toBe(2);
  });

  it("falls back to the state error list when no log was parsed", () => {
    const summary = mapRun(
      {
        files: files({
          state: {
            present: true,
            readable: true,
            values: { name: "x", state: "failed", errors: ["first", "last"], duration_s: 12 },
          },
        }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.lastError).toBe("last");
    expect(summary.errorCount).toBe(2);
  });

  it("derives duration and exit data from a lock-only run", () => {
    const summary = mapRun(
      {
        files: files({
          state: { present: false, readable: false, values: {} },
          lock: { pid: 4242, agentPid: null, backend: "posix", startedAt: "2026-11-14T00:00:00+00:00" },
          finalized: { present: true, exitCode: 0 },
        }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(summary.state).toBe("done");
    expect(summary.pids).toEqual({ pid: 4242, agentPid: null });
    expect(summary.liveness).toBe("settled");
  });

  it("reads the session id from state.json or the sidecar file", () => {
    const fromState = mapRun(
      {
        files: files({
          state: { present: true, readable: true, values: { name: "x", session_id: "abc", pid: 1 } },
        }),
        counters: null,
        verdicts: verdicts([1]),
      },
      NOW,
    );
    expect(fromState.sessionId).toBe("abc");

    const fromSidecar = mapRun(
      {
        files: files({ sessionIdFromFile: "def", lock: null }),
        counters: null,
        verdicts: new Map(),
      },
      NOW,
    );
    expect(fromSidecar.sessionId).toBe("def");
  });
});
