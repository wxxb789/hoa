import { appendFile, mkdir, mkdtemp, rename, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { followRun, listRuns, runDetail } from "../../shared/runs";
import { createLivenessProbe, type LivenessProbe, type PidVerdict } from "../liveness";
import { createRunStore, type StoreConfig } from "../run-store";

const DATE = "2026-11-14";
const STARTED = "2026-11-14T00:00:00+00:00";
const NOW = Date.parse("2026-11-14T00:10:00.000Z");

let root = "";

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "gdd-observer-test-"));
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

function fakeProbe(alive: number[]): LivenessProbe {
  return {
    kind: "posix",
    verdicts(pids) {
      const verdicts = new Map<number, PidVerdict>();
      for (const pid of pids) verdicts.set(pid, alive.includes(pid) ? "alive" : "dead");
      return verdicts;
    },
    async refresh() {},
  };
}

function store(alive: number[] = [], config: Partial<StoreConfig> = {}, env: NodeJS.ProcessEnv = {}) {
  return createRunStore({
    probe: fakeProbe(alive),
    config: () => ({ runRoot: root, pollIntervalMs: 2000, tailLines: 20, ...config }),
    env,
    now: () => NOW,
  });
}

async function writeRun(
  slug: string,
  files: Record<string, string>,
  date = DATE,
): Promise<string> {
  const dir = join(root, date, slug);
  await mkdir(dir, { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    await writeFile(join(dir, name), content, "utf8");
  }
  return dir;
}

function event(payload: Record<string, unknown>): string {
  return `${JSON.stringify(payload)}\n`;
}

const STATE_RUNNING = JSON.stringify({
  name: "stage-implement",
  state: "running",
  exit: null,
  started: STARTED,
  duration_s: null,
  model: "provider/model",
  thinking: "max",
  max_time: "6h",
  session_id: "session-1",
  pid: 111,
  agent_pid: 222,
  events_bytes: 10,
  events_truncated: false,
  events_dropped_bytes: 0,
});

describe("run store", () => {
  it("reports a missing run root instead of failing", async () => {
    const missing = join(root, "absent");
    const result = await createRunStore({
      probe: fakeProbe([]),
      config: () => ({ runRoot: missing, pollIntervalMs: 2000, tailLines: 20 }),
      env: {},
      now: () => NOW,
    }).listRuns();
    expect(result.rootExists).toBe(false);
    expect(result.runs).toEqual([]);
    expect(result.runRoot).toBe(missing);
    expect(result.rootSource).toBe("setting");
  });

  it("lists runs newest first with liveness, counters, and the open tool", async () => {
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222, backend: "windows", started_at: STARTED }),
      "events.ndjson":
        event({ type: "session", id: "session-1", timestamp: "2026-11-14T00:00:01.000Z" }) +
        event({ type: "turn_end", timestamp: "2026-11-14T00:00:02.000Z" }) +
        event({ type: "tool_execution_start", toolCallId: "a", toolName: "read", args: { path: "a.md" } }) +
        event({ type: "tool_execution_end", toolCallId: "a", toolName: "read" }) +
        event({
          type: "tool_execution_start",
          toolCallId: "b",
          toolName: "bash",
          intent: "Run tests",
          args: { command: "npm test" },
        }) +
        event({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.02 } } } }),
      "answer.md": "partial answer\n",
    });
    await writeRun(
      "older-stage",
      { "state.json": JSON.stringify({ name: "older", state: "running", started: "2026-11-13T22:00:00+00:00", pid: 999 }) },
      "2026-11-13",
    );

    const result = await store([222]).listRuns();
    expect(result.rootExists).toBe(true);
    expect(result.runs.map((run) => run.id)).toEqual([`${DATE}/stage-implement`, "2026-11-13/older-stage"]);

    const [run, older] = result.runs;
    expect(run.state).toBe("running");
    expect(run.liveness).toBe("running");
    expect(run.livePids).toEqual([222]);
    expect(run.turns).toBe(1);
    expect(run.toolCalls).toBe(2);
    expect(run.costUsd).toBeCloseTo(0.02, 6);
    expect(run.currentTool).toBe("bash");
    expect(run.currentToolIntent).toBe("Run tests");
    expect(run.countersFrom).toBe("events");
    expect(run.elapsedS).toBe(600);
    expect(run.hasAnswer).toBe(true);
    expect(run.answerChars).toBe(15);
    expect(run.eventLines).toBe(6);
    expect(run.sessionId).toBe("session-1");
    expect(run.pids).toEqual({ pid: 111, agentPid: 222 });

    expect(older.liveness).toBe("stale");
    expect(older.eventsBytes).toBe(0);
    expect(older.countersFrom).toBe("none");
  });

  it("only reads appended bytes between scans", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": event({ type: "turn_end" }),
    });
    const runs = store([222]);
    expect((await runs.listRuns()).runs[0].turns).toBe(1);

    await appendFile(join(dir, "events.ndjson"), event({ type: "turn_end" }), "utf8");
    const second = await runs.listRuns();
    expect(second.runs[0].turns).toBe(2);
    expect(second.runs[0].eventLines).toBe(2);
  });

  it("counts appended events once across concurrent list, follow, and detail handlers", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": "",
    });
    const runs = store([222]);
    await runs.listRuns();
    await appendFile(join(dir, "events.ndjson"),
      event({ type: "turn_end" }) +
      event({ type: "tool_execution_start", toolCallId: "a", toolName: "read" }) +
      event({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.02 } } } }),
      "utf8");

    const id = `${DATE}/stage-implement`;
    const responses = await Promise.all(Array.from({ length: 10 }, async () => {
      const [listed, followed, detail] = await Promise.all([
        runs.listRuns(), runs.follow(id), runs.runDetail(id),
      ]);
      return [listed.runs[0], followed.summary, detail.summary];
    }));
    const subsequent = (await runs.listRuns()).runs[0];
    for (const summary of [subsequent, ...responses.flat()]) {
      expect(summary?.turns).toBe(1);
      expect(summary?.toolCalls).toBe(1);
      expect(summary?.costUsd).toBeCloseTo(0.02, 6);
      expect(summary?.eventLines).toBe(3);
    }
  });

  it("counts an event straddling the 256 KiB read boundary exactly once", async () => {
    const first = event({ type: "session", id: "session-1", padding: "x".repeat(256 * 1024 - 128) });
    const second = event({ type: "turn_end", padding: "y".repeat(256) });
    expect(Buffer.byteLength(first)).toBeLessThan(256 * 1024);
    expect(Buffer.byteLength(first + second)).toBeGreaterThan(256 * 1024);
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": first + second,
    });
    const runs = store([222]);
    for (let scan = 0; scan < 2; scan += 1) {
      const summary = (await runs.listRuns()).runs[0];
      expect(summary.turns).toBe(1);
      expect(summary.eventLines).toBe(2);
    }
  });

  it("retains an incomplete event once until a later append completes it", async () => {
    const line = event({ type: "turn_end", padding: "x".repeat(256 * 1024) });
    const split = 256 * 1024 - 10;
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": event({ type: "session", id: "session-1" }) + line.slice(0, split),
    });
    const runs = store([222]);
    expect((await runs.listRuns()).runs[0].turns).toBe(0);
    expect((await runs.listRuns()).runs[0].turns).toBe(0);
    await appendFile(join(dir, "events.ndjson"), line.slice(split), "utf8");
    const summary = (await runs.listRuns()).runs[0];
    expect(summary.turns).toBe(1);
    expect(summary.eventLines).toBe(2);
  });

  it("recounts from scratch when the launcher splices the log", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson":
        event({ type: "turn_end" }) + event({ type: "turn_end" }) + event({ type: "turn_end" }),
    });
    const runs = store([222]);
    expect((await runs.listRuns()).runs[0].turns).toBe(3);

    const spliced =
      event({ type: "truncated", dropped_bytes: 5000, retained_bytes: 120 }) + event({ type: "turn_end" });
    await writeFile(join(dir, "events.ndjson"), spliced, "utf8");
    const summary = (await runs.listRuns()).runs[0];
    expect(summary.turns).toBe(1);
    expect(summary.eventLines).toBe(2);
    expect(summary.eventsTruncated).toBe(true);
    expect(summary.eventsDroppedBytes).toBe(5000);
    expect(summary.warnings).toContain("log-truncated");
  });

  it.each(["list", "follow", "detail"] as const)(
    "recounts retained metrics in the same %s scan after atomic replacement",
    async (scan) => {
      const head =
        event({ type: "turn_end" }) +
        event({ type: "tool_execution_start", toolCallId: "a", toolName: "read" }) +
        event({ type: "tool_execution_end", toolCallId: "a", toolName: "read" }) +
        event({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.02 } } } });
      const original = head +
        event({ type: "tool_execution_start", toolCallId: "dropped", toolName: "old-tool" }) +
        event({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.5 } } } }) +
        event({ type: "tool_execution_error", error: "dropped error" });
      const dir = await writeRun("stage-implement", {
        "state.json": STATE_RUNNING,
        "events.ndjson": original,
      });
      const runs = store([222]);
      expect((await runs.listRuns()).runs[0]).toMatchObject({
        turns: 1, toolCalls: 2, costUsd: 0.52, currentTool: "old-tool", errorCount: 1, eventLines: 7,
      });

      const lastEventAt = "2026-11-14T00:00:03.000Z";
      const retainedError = { type: "tool_execution_error", error: "retained error", timestamp: lastEventAt };
      const retained = head +
        event({ type: "truncated", dropped_bytes: 5000 }) +
        event({ type: "turn_end" }) +
        event({ type: "tool_execution_start", toolCallId: "b", toolName: "bash", intent: "Run tests" }) +
        event({ type: "message_end", message: { role: "assistant", usage: { cost: { total: 0.03 } } } }) +
        event(retainedError);
      // Match the writer's head + marker + tail replacement, not an in-place truncate.
      const path = join(dir, "events.ndjson");
      const replacement = join(dir, "events.ndjson.tmp");
      const before = await stat(path);
      await writeFile(replacement, retained, "utf8");
      await rename(replacement, path);
      const after = await stat(path);
      expect(`${after.ino}:${after.birthtimeMs}`).not.toBe(`${before.ino}:${before.birthtimeMs}`);
      expect(after.size).toBeGreaterThan(before.size);

      const id = `${DATE}/stage-implement`;
      const summary = scan === "list" ? (await runs.listRuns()).runs[0]
        : scan === "follow" ? (await runs.follow(id)).summary
        : (await runs.runDetail(id)).summary;
      const expected = {
        turns: 2,
        toolCalls: 2,
        costUsd: 0.05,
        countersFrom: "events",
        countersPartial: true,
        currentTool: "bash",
        currentToolIntent: "Run tests",
        errorCount: 1,
        lastError: JSON.stringify(retainedError),
        lastEventAt,
        eventLines: 9,
        eventsTruncated: true,
        eventsDroppedBytes: 5000,
      };
      expect(summary).toMatchObject(expected);
      expect(summary?.warnings).toContain("log-truncated");
      expect((await runs.listRuns()).runs[0]).toMatchObject(expected);
    },
  );

  it("prefers launcher counters once a run finalized", async () => {
    await writeRun("stage-implement", {
      "state.json": JSON.stringify({
        name: "stage-implement",
        state: "done",
        exit: 0,
        started: STARTED,
        ended: "2026-11-14T00:05:00+00:00",
        duration_s: 300,
        turns: 8,
        tool_calls: 15,
        cost_usd: 0.4,
        answer_chars: 6,
        pid: 111,
      }),
      "events.ndjson": event({ type: "turn_end" }),
      finalized: "0",
      "answer.md": "hello\n",
      "events.stats.json": JSON.stringify({
        total_bytes: 100,
        retained_bytes: 100,
        dropped_bytes: 0,
        truncated: false,
      }),
    });
    const summary = (await store([]).listRuns()).runs[0];
    expect(summary.state).toBe("done");
    expect(summary.liveness).toBe("settled");
    expect(summary.countersFrom).toBe("state");
    expect(summary.turns).toBe(8);
    expect(summary.toolCalls).toBe(15);
    expect(summary.costUsd).toBe(0.4);
    expect(summary.durationS).toBe(300);
    expect(summary.hasAnswer).toBe(true);
  });

  it("never reports success for a run without state.json", async () => {
    await writeRun("crash-without-state", {
      lock: JSON.stringify({ pid: 555 }),
      "events.ndjson": event({ type: "turn_end" }),
    });
    const summary = (await store([]).listRuns()).runs[0];
    expect(summary.state).toBe("unknown");
    expect(summary.liveness).toBe("stale");
    expect(summary.warnings).toContain("state-missing");
  });

  it("bounds the event tail and the answer tail to the requested line count", async () => {
    const events = Array.from({ length: 40 }, (_, index) => event({ type: "turn_end", timestamp: `2026-11-14T00:00:${String(index).padStart(2, "0")}.000Z` })).join("");
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": events,
      "answer.md": Array.from({ length: 30 }, (_, index) => `line ${index}`).join("\n"),
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
    });
    const runs = store([222], { tailLines: 5 });
    const detail = await runs.runDetail(`${DATE}/stage-implement`);
    expect(detail.found).toBe(true);
    expect(detail.events).toHaveLength(5);
    expect(detail.events[4].at).toBe("2026-11-14T00:00:39.000Z");
    expect(detail.answerTail?.split("\n")).toHaveLength(5);
    expect(detail.answerTail?.endsWith("line 29")).toBe(true);
    expect(detail.paths.map((path) => path.label)).toContain("finalized");
    expect(detail.paths.find((path) => path.label === "state.json")?.exists).toBe(true);
    expect(detail.paths.find((path) => path.label === "finalized")?.exists).toBe(false);
    const summary = detail.summary;
    expect(summary?.turns).toBe(40);

    const follow = await runs.follow(`${DATE}/stage-implement`);
    expect(follow.found).toBe(true);
    expect(follow.summary?.turns).toBe(40);
    expect(follow.events).toHaveLength(5);
  });

  it("tolerates garbage lines in the event log", async () => {
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": `${event({ type: "turn_end" })}not-json\n\n{"type":"turn_end"}\n`,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
    });
    const summary = (await store([222]).listRuns()).runs[0];
    expect(summary.turns).toBe(2);
    expect(summary.eventLines).toBe(2);
  });

  it("keeps the first complete non-ASCII event in detail and follow tails", async () => {
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": event({ type: "tool_execution_start", toolCallId: "a", toolName: "read", intent: "读取配置文件" }),
    });
    const runs = store([222]);
    const id = `${DATE}/stage-implement`;
    for (const result of [await runs.runDetail(id), await runs.follow(id)]) {
      expect(result.events).toHaveLength(1);
      expect(result.events[0].type).toBe("tool_execution_start");
      expect(result.events[0].intent).toBe("读取配置文件");
    }
  });

  it("reports an unknown run id as not found", async () => {
    const result = await store([]).runDetail("not-a-run-id");
    expect(result.found).toBe(false);
    expect(result.summary).toBeNull();
    expect(result.paths).toEqual([]);
  });

  it("produces payloads that satisfy the published RPC schemas", async () => {
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222, backend: "windows", started_at: STARTED }),
      "events.ndjson":
        event({ type: "turn_end" }) +
        event({ type: "tool_execution_start", toolCallId: "a", toolName: "bash", intent: "Run tests" }) +
        event({ type: "truncated", dropped_bytes: 12 }),
      "answer.md": "done\n",
    });
    const runs = store([222]);
    const id = `${DATE}/stage-implement`;
    const parsedList = listRuns.output.safeParse(await runs.listRuns());
    const parsedDetail = runDetail.output.safeParse(await runs.runDetail(id, 5));
    const parsedFollow = followRun.output.safeParse(await runs.follow(id));
    for (const parsed of [parsedList, parsedDetail, parsedFollow]) {
      expect(parsed.success ? "" : JSON.stringify(parsed.error.issues)).toBe("");
    }
  });

  it("resolves the root from GDD_RUN_ROOT, then LOCALAPPDATA, then the documented default", async () => {
    const stateDir = await mkdtemp(join(tmpdir(), "gdd-observer-state-"));
    try {
      await writeRun("stage-implement", { "state.json": STATE_RUNNING });
      const fromEnv = await createRunStore({
        probe: fakeProbe([222]),
        config: () => ({ runRoot: "", pollIntervalMs: 2000, tailLines: 20 }),
        env: { GDD_RUN_ROOT: root, HOME: stateDir, LOCALAPPDATA: stateDir },
        now: () => NOW,
      }).listRuns();
      expect(fromEnv.runRoot).toBe(root);
      expect(fromEnv.rootSource).toBe("env");
      expect(fromEnv.runs.map((run) => run.slug)).toEqual(["stage-implement"]);

      const localAppRuns = join(stateDir, "gdd", "runs");
      await mkdir(join(localAppRuns, DATE, "from-localappdata"), { recursive: true });
      await writeFile(join(localAppRuns, DATE, "from-localappdata", "state.json"), STATE_RUNNING, "utf8");
      const fromLocal = await createRunStore({
        probe: fakeProbe([222]),
        config: () => ({ runRoot: "", pollIntervalMs: 2000, tailLines: 20 }),
        env: { HOME: join(stateDir, "no-home"), LOCALAPPDATA: stateDir },
        now: () => NOW,
      }).listRuns();
      expect(fromLocal.runRoot).toBe(localAppRuns);
      expect(fromLocal.rootSource).toBe("localappdata");
      expect(fromLocal.runs.map((run) => run.slug)).toEqual(["from-localappdata"]);

      const unresolved = await createRunStore({
        probe: fakeProbe([]),
        config: () => ({ runRoot: "", pollIntervalMs: 2000, tailLines: 20 }),
        env: { HOME: join(stateDir, "empty-home") },
        now: () => NOW,
      }).listRuns();
      expect(unresolved.rootExists).toBe(false);
      expect(unresolved.rootSource).toBe("default");
      expect(unresolved.runRoot).toBe(join(stateDir, "empty-home", ".local", "state", "gdd", "runs"));
    } finally {
      await rm(stateDir, { recursive: true, force: true });
    }
  });
});

describe("liveness probe", () => {
  it(
    "proves this process is alive and confirms a reserved pid through the OS listing",
    async () => {
      const probe = createLivenessProbe();
      const bogus = 2_147_483_632;
      const first = probe.verdicts([process.pid, bogus, 0]);
      expect(first.get(process.pid)).toBe("alive");
      expect(["unknown", "dead"]).toContain(first.get(bogus) ?? "unknown");
      expect(probe.verdicts([0]).get(0)).toBe("unknown");

      await probe.refresh([bogus]);
      expect(probe.verdicts([bogus]).get(bogus)).toBe("dead");
    },
    30_000,
  );
});
