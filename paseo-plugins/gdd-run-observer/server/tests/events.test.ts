import { describe, expect, it } from "vitest";
import { applyEventLine, createCounters, parseEventWindow, snapshotCounters, summarizeValue } from "../events";

function line(event: unknown): string {
  return JSON.stringify(event);
}

describe("applyEventLine", () => {
  it("requires recognized instrumentation before declaring event counters available", () => {
    const counters = createCounters();
    for (const type of ["paseo_status", "truncated", "future_lifecycle"]) {
      applyEventLine(counters, line({ type }));
      expect(snapshotCounters(counters).hasCounters).toBe(false);
    }
    applyEventLine(counters, line({ type: "session", id: "s1" }));
    const snapshot = snapshotCounters(counters);
    expect(snapshot.hasCounters).toBe(true);
    expect(snapshot.turns).toBe(0);
    expect(snapshot.toolCalls).toBe(0);
    expect(snapshot.costUsd).toBe(0);
    applyEventLine(counters, line({ type: "paseo_status", state: "done" }));
    expect(snapshotCounters(counters).hasCounters).toBe(true);
  });

  it("counts turns, tool calls, and assistant cost the way the launcher finalizer does", () => {
    const counters = createCounters();
    applyEventLine(counters, line({ type: "session", id: "s1", timestamp: "2026-11-14T00:00:00.000Z" }));
    applyEventLine(counters, line({ type: "turn_start" }));
    applyEventLine(counters, line({ type: "tool_execution_start", toolCallId: "t1", toolName: "read", args: { path: "a" } }));
    applyEventLine(counters, line({ type: "tool_execution_end", toolCallId: "t1", toolName: "read", result: { content: [] } }));
    applyEventLine(counters, line({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.25 } } } }));
    applyEventLine(counters, line({ type: "message_end", message: { role: "user", usage: { cost: { total: 9 } } } }));
    applyEventLine(counters, line({ type: "message_end", message: { role: "assistant", usage: { cost: 0.5 } } }));
    applyEventLine(counters, line({ type: "turn_end" }));

    const snapshot = snapshotCounters(counters);
    expect(snapshot.turns).toBe(1);
    expect(snapshot.toolCalls).toBe(1);
    expect(snapshot.costUsd).toBeCloseTo(0.75, 6);
    expect(snapshot.currentTool).toBeNull();
    expect(snapshot.lastEventAt).toBe("2026-11-14T00:00:00.000Z");
    expect(snapshot.lines).toBe(8);
    expect(snapshot.badLines).toBe(0);
  });

  it("reports the last started tool that has not ended", () => {
    const counters = createCounters();
    applyEventLine(counters, line({ type: "tool_execution_start", toolCallId: "a", toolName: "read" }));
    applyEventLine(counters, line({ type: "tool_execution_start", toolCallId: "b", toolName: "bash", intent: "Run tests" }));
    applyEventLine(counters, line({ type: "tool_execution_end", toolCallId: "a", toolName: "read" }));
    expect(snapshotCounters(counters).currentTool).toEqual({ name: "bash", intent: "Run tests" });

    applyEventLine(counters, line({ type: "tool_execution_end", toolCallId: "b", toolName: "bash" }));
    expect(snapshotCounters(counters).currentTool).toBeNull();
    expect(snapshotCounters(counters).toolCalls).toBe(2);
  });

  it("keeps the last five tool errors and counts them all", () => {
    const counters = createCounters();
    for (let index = 0; index < 7; index += 1) {
      applyEventLine(counters, line({ type: "tool_execution_error", toolCallId: `t${index}`, toolName: "bash", error: `boom ${index}` }));
    }
    const snapshot = snapshotCounters(counters);
    expect(snapshot.errorCount).toBe(7);
    expect(snapshot.lastError).toContain("boom 6");
  });

  it("tolerates blank lines, garbage, and non-object payloads", () => {
    const counters = createCounters();
    expect(applyEventLine(counters, "")).toBeNull();
    expect(applyEventLine(counters, "   ")).toBeNull();
    expect(applyEventLine(counters, "not json at all")).toBeNull();
    expect(applyEventLine(counters, "[1,2,3]")).toBeNull();
    expect(applyEventLine(counters, line({ noType: true }))).toBeNull();
    const snapshot = snapshotCounters(counters);
    expect(snapshot.lines).toBe(0);
    // Blank lines are skipped silently; three payloads are counted as unusable.
    expect(snapshot.badLines).toBe(3);
  });

  it("treats a truncated marker as loss accounting, not as an event", () => {
    const counters = createCounters();
    const event = applyEventLine(counters, line({ type: "truncated", dropped_bytes: 4096, retained_bytes: 100 }));
    const snapshot = snapshotCounters(counters);
    expect(event?.type).toBe("truncated");
    expect(event?.detail).toBe("4096 bytes dropped");
    expect(snapshot.truncated).toBe(true);
    expect(snapshot.droppedBytes).toBe(4096);
    expect(snapshot.turns).toBe(0);
    expect(snapshot.toolCalls).toBe(0);
  });

  it("normalizes numeric and ISO timestamps", () => {
    const counters = createCounters();
    applyEventLine(counters, line({ type: "turn_start", timestamp: 1_760_000_000_000 }));
    expect(snapshotCounters(counters).lastEventAt).toBe(new Date(1_760_000_000_000).toISOString());
    applyEventLine(counters, line({ type: "turn_end", timestamp: "2026-11-14T01:00:00.000Z" }));
    expect(snapshotCounters(counters).lastEventAt).toBe("2026-11-14T01:00:00.000Z");
  });

  it("advances lastEventAt from native Paseo lifecycle timestamps", () => {
    const counters = createCounters();
    // refresh_locked writes `at`, not the headless instrumented stream's `timestamp`.
    for (const event of [
      { type: "paseo_status", at: "2026-11-14T01:00:00+00:00", state: "running", status: "running" },
      { type: "paseo_status", at: "2026-11-14T01:00:01+00:00", state: "unknown", status: null },
      { type: "paseo_status", at: "2026-11-14T01:00:02+00:00", state: "failed", status: "error" },
    ]) {
      const compact = applyEventLine(counters, line(event));
      expect(snapshotCounters(counters).lastEventAt).toBe(event.at);
      expect(compact?.at).toBe(event.at);
    }
    expect(snapshotCounters(counters).hasCounters).toBe(false);
  });

  it("keeps native Paseo lifecycle states distinguishable in compact details", () => {
    const events = [
      { state: "running", status: "initializing" },
      { state: "running", status: "running" },
      { state: "running", status: "idle" }, // Pending permissions keep an idle agent running.
      { state: "unknown", status: null }, // An inspect outage is not a terminal failure.
      { state: "failed", status: "error" },
      { state: "done", status: "idle" },
      { state: "killed", status: "closed" },
    ].map((lifecycle) => ({ type: "paseo_status", at: "2026-11-14T01:00:00+00:00", ...lifecycle }));
    const compact = parseEventWindow(events.map(line).join("\n"), events.length);
    expect(compact.map((event) => event.detail)).toEqual([
      '{"state":"running","status":"initializing"}',
      '{"state":"running","status":"running"}',
      '{"state":"running","status":"idle"}',
      '{"state":"unknown","status":null}',
      '{"state":"failed","status":"error"}',
      '{"state":"done","status":"idle"}',
      '{"state":"killed","status":"closed"}',
    ]);
  });

  it("describes tool events with bounded, redacted argument summaries", () => {
    const counters = createCounters();
    const event = applyEventLine(
      counters,
      line({
        type: "tool_execution_start",
        toolCallId: "big",
        toolName: "bash",
        intent: "Run the suite",
        args: { command: "npm test", content: "x".repeat(50_000) },
      }),
    );
    expect(event?.tool).toBe("bash");
    expect(event?.intent).toBe("Run the suite");
    expect(event?.detail).toContain("npm test");
    expect(event?.detail).toContain("[…]");
    expect(event?.detail?.length).toBeLessThanOrEqual(161);
  });

  it("keeps only the requested event window", () => {
    const text = [
      line({ type: "turn_start" }),
      line({ type: "tool_execution_start", toolCallId: "1", toolName: "read" }),
      "garbage",
      line({ type: "turn_end" }),
      line({ type: "message_end", message: { role: "assistant" } }),
    ].join("\n");
    const events = parseEventWindow(text, 2);
    expect(events.map((event) => event.type)).toEqual(["turn_end", "message_end"]);
    expect(events[1].role).toBe("assistant");
  });
});

describe("summarizeValue", () => {
  it("returns null for empty input and clips long strings", () => {
    expect(summarizeValue(undefined)).toBeNull();
    expect(summarizeValue(null)).toBeNull();
    expect(summarizeValue("short")).toBe("short");
    expect(summarizeValue("y".repeat(300), 10)).toBe(`${"y".repeat(10)}…`);
  });
});
