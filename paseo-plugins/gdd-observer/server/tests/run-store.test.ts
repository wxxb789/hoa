import { appendFile, mkdir, mkdtemp, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { followRun, listRuns, runPaths } from "../../shared/runs";
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
    config: () => ({ runRoot: root, tailLines: 20, ...config }),
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

/** Every entry of a run directory with its size and mtime, for the read-only assertions. */
async function directoryState(dir: string): Promise<Record<string, string>> {
  const names = await readdir(dir);
  const state: Record<string, string> = {};
  for (const name of names.sort()) {
    const info = await stat(join(dir, name));
    state[name] = `${info.size}:${info.mtimeMs}`;
  }
  return state;
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
  it("uses state totals after rotation and labels active-segment-only totals partial", async () => {
    const active = event({ type: "turn_end" });
    const files = { "events.ndjson": active, "events.1.ndjson": active.repeat(7) };
    const state = { ...JSON.parse(STATE_RUNNING), agent: "omp" };
    const dir = await writeRun("rotated", { ...files, "state.json": JSON.stringify(state) });
    const runs = store([111]);
    expect((await runs.listRuns()).runs[0]).toMatchObject({
      turns: 1, countersFrom: "events", countersPartial: true, eventsTruncated: false,
    });
    await writeFile(join(dir, "state.json"), JSON.stringify({ ...state, turns: 8, tool_calls: 0 }));
    expect((await runs.listRuns()).runs[0]).toMatchObject({
      turns: 8, countersFrom: "state", countersPartial: false, eventsTruncated: false,
    });
  });

  it("uses live DSH state totals instead of generic tool events", async () => {
    await writeRun("dsh", {
      "state.json": JSON.stringify({ ...JSON.parse(STATE_RUNNING), agent: "dsh", turns: 3, tool_calls: 5 }),
      "events.ndjson": event({ type: "tool_call" }),
    });
    expect((await store([111]).listRuns()).runs[0]).toMatchObject({
      turns: 3, toolCalls: 5, countersFrom: "state",
    });
  });

  it("reports a missing run root instead of failing", async () => {
    const missing = join(root, "absent");
    const result = await createRunStore({
      probe: fakeProbe([]),
      config: () => ({ runRoot: missing, tailLines: 20 }),
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
        event({
          type: "message_end",
          message: {
            role: "assistant",
            provider: "tencent-litellm",
            model: "GLM-5.3",
            api: "openai-completions",
            usage: { cost: { total: 0.02 } },
          },
        }),
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
    expect(run.model).toEqual({
      requested: "provider/model",
      requestedProvider: "provider",
      requestedModel: "model",
      thinking: "max",
      observed: [
        {
          provider: "tencent-litellm",
          model: "GLM-5.3",
          api: "openai-completions",
          messages: 1,
        },
      ],
    });
    expect(result.stats.total).toBe(2);
    expect(result.stats.byState).toEqual({
      running: 2,
      done: 0,
      killed: 0,
      failed: 0,
      unknown: 0,
    });
    expect(result.stats.byLiveness).toEqual({
      running: 1,
      settled: 0,
      stale: 1,
      unknown: 0,
    });
    expect(result.stats.turns).toBe(1);
    expect(result.stats.toolCalls).toBe(2);
    expect(result.stats.costUsd).toBeCloseTo(0.02, 6);
    expect(result.stats.flagged).toBe(1);

    expect(older.liveness).toBe("stale");
    expect(older.eventsBytes).toBe(0);
    expect(older.countersFrom).toBe("none");
  });

  it("counts events appended between scans once", async () => {
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

  it("counts the replacement log after an atomic replace", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": event({ type: "turn_end" }) + event({ type: "turn_end" }),
    });
    const runs = store([222]);
    expect((await runs.listRuns()).runs[0].turns).toBe(2);

    const replacement = join(dir, "events.ndjson.tmp");
    await writeFile(
      replacement,
      event({ type: "truncated", dropped_bytes: 900, retained_bytes: 60 }) +
        event({ type: "turn_end" }) +
        event({
          type: "message_end",
          message: { role: "assistant", provider: "ghc", model: "gpt-6.1-sol" },
        }),
      "utf8",
    );
    await rename(replacement, join(dir, "events.ndjson"));

    const summary = (await runs.listRuns()).runs[0];
    expect(summary.turns).toBe(1);
    expect(summary.eventLines).toBe(3);
    expect(summary.model.observed.map((usage) => usage.model)).toEqual(["gpt-6.1-sol"]);
  });

  it("does not recount a log whose tail is an unterminated line", async () => {
    const logs: string[] = [];
    const runs = createRunStore({
      probe: fakeProbe([222]),
      config: () => ({ runRoot: root, tailLines: 20 }),
      env: {},
      now: () => NOW,
      log: (message) => logs.push(message),
    });
    const half = JSON.stringify({ type: "turn_end" });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": `${event({ type: "turn_end" })}${half.slice(0, 8)}`,
    });
    expect((await runs.listRuns()).runs[0].turns).toBe(1);

    logs.length = 0;
    await appendFile(join(dir, "events.ndjson"), `${half.slice(8)}\n`, "utf8");
    const summary = (await runs.listRuns()).runs[0];
    expect(summary.turns).toBe(2);
    expect(logs.filter((message) => message.includes("recount"))).toEqual([]);
  });

  it("counts an event that straddles the read chunk boundary exactly once", async () => {
    const boundary = 256 * 1024;
    const charged = event({
      type: "message_end",
      message: {
        role: "assistant",
        provider: "ghc",
        model: "gpt-6.1-sol",
        usage: { cost: { total: 0.5 } },
      },
    });
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson":
        event({ type: "turn_end", pad: "x".repeat(boundary - 80) }) + charged + event({ type: "turn_end" }),
    });

    const summary = (await store([222]).listRuns()).runs[0];
    expect(summary.eventLines).toBe(3);
    expect(summary.turns).toBe(2);
    expect(summary.costUsd).toBeCloseTo(0.5, 6);
    expect(summary.model.observed.map((usage) => usage.model)).toEqual(["gpt-6.1-sol"]);
  });

  it("counts an appended completion of a half line exactly once", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": `${event({ type: "turn_end" })}${JSON.stringify({ type: "turn_end" }).slice(0, 10)}`,
    });
    const runs = store([222]);
    expect((await runs.listRuns()).runs[0].turns).toBe(1);

    await appendFile(join(dir, "events.ndjson"), `${JSON.stringify({ type: "turn_end" }).slice(10)}\n`, "utf8");
    const summary = (await runs.listRuns()).runs[0];
    expect(summary.turns).toBe(2);
    expect(summary.eventLines).toBe(2);
  });

  it("does not double count when two scans overlap", async () => {
    const padding = event({ type: "tool_execution_end", toolCallId: "a", toolName: "read", result: "x".repeat(2000) });
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": Array.from({ length: 200 }, () => padding).join("") + event({ type: "turn_end" }),
    });
    const runs = store([222]);

    const scans = await Promise.all([
      runs.listRuns(),
      runs.listRuns(),
      runs.listRuns(),
      runs.listRuns(),
    ]);
    for (const scan of scans) {
      expect(scan.runs[0].turns).toBe(1);
      expect(scan.runs[0].eventLines).toBe(201);
    }
  });

  it("reads a run without touching it or logging its content", async () => {
    const marker = "SECRET-MARKER-9f2";
    const dir = await writeRun("stage-implement", {
      "state.json": JSON.stringify({ ...JSON.parse(STATE_RUNNING), name: marker }),
      lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
      "events.ndjson": `${event({ type: "turn_end" })}${event({ type: "message_end", message: { role: "assistant", content: marker } })}`,
      "answer.md": marker,
    });
    const logs: string[] = [];
    const runs = createRunStore({
      probe: fakeProbe([222]),
      config: () => ({ runRoot: root, tailLines: 20 }),
      env: {},
      now: () => NOW,
      log: (message) => logs.push(message),
    });
    const before = await directoryState(dir);

    const id = `${DATE}/stage-implement`;
    await runs.listRuns();
    await runs.follow(id);
    await runs.paths(id);

    expect(await directoryState(dir)).toEqual(before);
    expect(logs.join("\n")).not.toContain(marker);
  });

  it("does not wait for unproven-pid confirmation before answering", async () => {
    await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      "events.ndjson": event({ type: "turn_end" }),
    });
    const runs = createRunStore({
      probe: {
        kind: "win32",
        verdicts: (pids) => new Map(pids.map((pid) => [pid, "unknown" as PidVerdict])),
        refresh: () => new Promise<void>(() => {}),
      },
      config: () => ({ runRoot: root, tailLines: 20 }),
      env: {},
      now: () => NOW,
    });
    const scan = await runs.listRuns();
    expect(scan.runs[0].turns).toBe(1);
    expect(scan.runs[0].liveness).toBe("unknown");
  });

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
    const id = `${DATE}/stage-implement`;
    const runs = store([222], { tailLines: 5 });
    const follow = await runs.follow(id);
    expect(follow.found).toBe(true);
    expect(follow.events).toHaveLength(5);
    expect(follow.events[4].at).toBe("2026-11-14T00:00:39.000Z");
    expect(follow.answerTail?.split("\n")).toHaveLength(5);
    expect(follow.answerTail?.endsWith("line 29")).toBe(true);
    expect(follow.summary?.turns).toBe(40);

    const paths = await runs.paths(id);
    expect(paths.found).toBe(true);
    expect(paths.paths.find((path) => path.label === "state.json")?.exists).toBe(true);
    expect(paths.paths.find((path) => path.label === "finalized")?.exists).toBe(false);
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

  it("reports a malformed and an absent run id as not found", async () => {
    const runs = store([]);
    for (const id of ["not-a-run-id", `${DATE}/absent-slug`]) {
      const paths = await runs.paths(id);
      expect(paths.found).toBe(false);
      expect(paths.paths).toEqual([]);
      expect((await runs.follow(id)).found).toBe(false);
    }
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
    const parsedList = listRuns.output.safeParse(await runs.listUpdate());
    const parsedDelta = listRuns.output.safeParse(await runs.listUpdate(parsedList.data?.revision));
    const parsedPaths = runPaths.output.safeParse(await runs.paths(id));
    const parsedFollow = followRun.output.safeParse(await runs.follow(id));
    expect(parsedDelta.data).toMatchObject({ changes: [], removed: [] });
    for (const parsed of [parsedList, parsedDelta, parsedPaths, parsedFollow]) {
      expect(parsed.success ? "" : JSON.stringify(parsed.error.issues)).toBe("");
    }
  });

  it("resolves the root from GDD_RUN_ROOT, then LOCALAPPDATA, then the documented default", async () => {
    const stateDir = await mkdtemp(join(tmpdir(), "gdd-observer-state-"));
    try {
      await writeRun("stage-implement", { "state.json": STATE_RUNNING });
      const fromEnv = await createRunStore({
        probe: fakeProbe([222]),
        config: () => ({ runRoot: "", tailLines: 20 }),
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
        config: () => ({ runRoot: "", tailLines: 20 }),
        env: { HOME: join(stateDir, "no-home"), LOCALAPPDATA: stateDir },
        now: () => NOW,
      }).listRuns();
      expect(fromLocal.runRoot).toBe(localAppRuns);
      expect(fromLocal.rootSource).toBe("localappdata");
      expect(fromLocal.runs.map((run) => run.slug)).toEqual(["from-localappdata"]);

      const unresolved = await createRunStore({
        probe: fakeProbe([]),
        config: () => ({ runRoot: "", tailLines: 20 }),
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

describe("run store lineage", () => {
  const BASE_FILES = {
    "state.json": STATE_RUNNING,
    lock: JSON.stringify({ pid: 111, agent_pid: 222 }),
    "events.ndjson": event({ type: "turn_end" }),
  };
  const LINEAGE = JSON.stringify({
    goal: "  ship the observer lineage  ",
    stage: " stage-implement ",
    parentAgentId: "Paseo.Main-1",
  });

  it("carries a validated sidecar on follow and nothing else", async () => {
    await writeRun("stage-implement", { ...BASE_FILES, "lineage.json": LINEAGE });
    await writeRun("stage-no-parent", {
      ...BASE_FILES,
      "lineage.json": JSON.stringify({ goal: "goal-only", stage: "stage-fix" }),
    });
    const runs = store([222]);
    const id = `${DATE}/stage-implement`;

    const follow = await runs.follow(id);
    expect(follow.lineage).toEqual({
      goal: "ship the observer lineage",
      stage: "stage-implement",
      parentAgentId: "Paseo.Main-1",
    });
    // The sidecar annotates the run; the standard summary and tails are untouched.
    expect(follow.summary?.turns).toBe(1);
    expect(follow.events).toHaveLength(1);
    expect(follow.answerTail).toBeNull();
    expect(followRun.output.safeParse(follow).success).toBe(true);
    // A warmed poll answers from the revision-checked cache with the same lineage.
    expect((await runs.follow(id)).lineage).toEqual(follow.lineage);

    // The parent id is optional in the published shape.
    expect((await runs.follow(`${DATE}/stage-no-parent`)).lineage).toEqual({
      goal: "goal-only",
      stage: "stage-fix",
    });

    // The scan carries no lineage, and the path listing does not read the sidecar.
    expect((await runs.listRuns()).runs[0]).not.toHaveProperty("lineage");
    expect((await runs.paths(id)).paths.some((path) => path.label === "lineage.json")).toBe(false);
  });

  it("omits lineage entirely when the sidecar is missing", async () => {
    await writeRun("stage-implement", BASE_FILES);
    const follow = await store([222]).follow(`${DATE}/stage-implement`);
    expect(follow.found).toBe(true);
    expect(follow.lineage).toBeUndefined();
    expect(follow.summary?.turns).toBe(1);
    expect(follow.events).toHaveLength(1);
    expect(followRun.output.safeParse(follow).success).toBe(true);
  });

  it("omits lineage for malformed, invalid, and oversized sidecars without disturbing the run", async () => {
    const cases: Record<string, string> = {
      "empty file": "",
      "truncated JSON": '{"goal":"goal","stage":"stage"',
      "not an object": JSON.stringify(["goal", "stage"]),
      "whitespace-only goal": JSON.stringify({ goal: "   ", stage: "stage" }),
      "invalid parent id": JSON.stringify({ goal: "goal", stage: "stage", parentAgentId: "not an id" }),
      // This file's last 4 KiB parse as valid JSON; only the size check stops the window from passing.
      oversized: `${" ".repeat(5000)}${JSON.stringify({ goal: "goal", stage: "stage" })}`,
    };
    const runs = store([222]);
    for (const [index, [name, content]] of Object.entries(cases).entries()) {
      const slug = `stage-${index}`;
      await writeRun(slug, { ...BASE_FILES, "lineage.json": content });
      const follow = await runs.follow(`${DATE}/${slug}`);
      expect(follow.found, name).toBe(true);
      expect(follow.lineage, name).toBeUndefined();
      expect(follow.summary?.turns, name).toBe(1);
      expect(follow.events, name).toHaveLength(1);
      expect(followRun.output.safeParse(follow).success, name).toBe(true);
    }
  });

  it("omits lineage when the sidecar path is not a readable document", async () => {
    const dir = await writeRun("stage-implement", BASE_FILES);
    await mkdir(join(dir, "lineage.json"));
    const follow = await store([222]).follow(`${DATE}/stage-implement`);
    expect(follow.lineage).toBeUndefined();
    expect(follow.summary?.turns).toBe(1);
    expect(follow.events).toHaveLength(1);
  });

  it("re-reads a replaced sidecar on the next follow", async () => {
    const dir = await writeRun("stage-implement", {
      ...BASE_FILES,
      "lineage.json": JSON.stringify({ goal: "first", stage: "stage-a" }),
    });
    const runs = store([222]);
    const id = `${DATE}/stage-implement`;
    expect((await runs.follow(id)).lineage?.goal).toBe("first");

    await writeFile(
      join(dir, "lineage.json"),
      JSON.stringify({ goal: "second sidecar", stage: "stage-b" }),
      "utf8",
    );
    expect((await runs.follow(id)).lineage).toEqual({ goal: "second sidecar", stage: "stage-b" });
  });

  it("reads a sidecar that fills the cap exactly", async () => {
    const document = JSON.stringify({ goal: "boundary", stage: "stage-boundary" });
    const padded = `${" ".repeat(4096 - document.length)}${document}`;
    expect(padded).toHaveLength(4096);
    await writeRun("stage-implement", { ...BASE_FILES, "lineage.json": padded });
    const follow = await store([222]).follow(`${DATE}/stage-implement`);
    expect(follow.lineage).toEqual({ goal: "boundary", stage: "stage-boundary" });
  });
});

describe("liveness probe", () => {
  it("proves this process is alive and rejects invalid pids on this host", () => {
    const probe = createLivenessProbe();
    const verdicts = probe.verdicts([process.pid, 0]);
    expect(verdicts.get(process.pid)).toBe("alive");
    expect(verdicts.get(0)).toBe("unknown");
    if (process.platform !== "win32") {
      const absentPid = 2_147_483_632;
      expect(probe.verdicts([absentPid]).get(absentPid)).toBe("dead");
    }
  });
});
