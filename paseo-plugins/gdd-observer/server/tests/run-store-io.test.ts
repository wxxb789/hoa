import { appendFile, mkdir, mkdtemp, rename, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LivenessProbe, PidVerdict } from "../liveness";
import { createRunStore, type StoreConfig } from "../run-store";

type Read = { path: string; position: number; bytes: number };

/**
 * A read the suite parks: `held` reports that a pass is inside it, `release` lets that pass finish
 * it, and `snapshot` runs the real read before parking, so the caller's bytes predate the hold.
 */
type HeldRead = {
  path: string;
  position: number;
  snapshot: boolean;
  held: Promise<void>;
  /** The mock's side of the hold, which only `holdRead` and the read wrapper touch. */
  gate: Promise<void>;
  /** The wrapper takes the oldest unclaimed entry that fits, and leaves it registered. */
  claimed: boolean;
  arrive(): void;
  release(): void;
};

/**
 * The store reaches the filesystem through `open` and the handle it returns, so counting opens and
 * bytes read there is the cost contract of this suite: it is the same boundary the store uses, not
 * a copy of its logic. `failOpen` injects a read failure deterministically, and `holds` parks a
 * read at a chosen path and offset until the test releases it.
 */
const io = vi.hoisted(() => ({
  opens: new Map<string, number>(),
  reads: [] as Read[],
  failOpen: new Set<string>(),
  holds: [] as HeldRead[],
}));

vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const realOpen = actual.open as (...args: unknown[]) => Promise<Record<string, unknown>>;
  const countedOpen = async (...args: unknown[]): Promise<unknown> => {
    const path = String(args[0]);
    if (io.failOpen.has(path)) {
      const error: NodeJS.ErrnoException = new Error(`EACCES: injected read failure for ${path}`);
      error.code = "EACCES";
      throw error;
    }
    const handle = await realOpen(...args);
    io.opens.set(path, (io.opens.get(path) ?? 0) + 1);
    return new Proxy(handle, {
      get(target, property) {
        if (property === "read") {
          // The method needs the handle as its receiver: extracted bare, it loses `this`.
          const read = (
            target.read as unknown as (...inner: unknown[]) => Promise<{ bytesRead: number }>
          ).bind(target);
          return async (...readArgs: unknown[]) => {
            const position = typeof readArgs[3] === "number" ? readArgs[3] : -1;
            const hold = io.holds.find(
              (candidate) =>
                !candidate.claimed && candidate.path === path && candidate.position === position,
            );
            if (hold) {
              // A claimed hold stays registered, so cleanup can still open its gate.
              hold.claimed = true;
              if (!hold.snapshot) {
                hold.arrive();
                await hold.gate;
              } else {
                const captured = await read(...readArgs);
                io.reads.push({ path, position, bytes: captured.bytesRead });
                hold.arrive();
                await hold.gate;
                return captured;
              }
            }
            const result = await read(...readArgs);
            io.reads.push({ path, position, bytes: result.bytesRead });
            return result;
          };
        }
        const value = Reflect.get(target, property, target);
        return typeof value === "function"
          ? (value as (...inner: unknown[]) => unknown).bind(target)
          : value;
      },
    });
  };
  return { ...actual, open: countedOpen };
});

/**
 * Park the next read of `path` that begins at `position` until the test releases it, reporting the
 * arrival on `held`: a pass can be kept inside a read while another pass runs to a chosen point,
 * with no sleep and no assumption about how the platform schedules the two. A `snapshot` hold runs
 * the real read first, which is how a pass is given the bytes of the revision it started on. The
 * hold is registered in `io.holds` as it is created and left there until cleanup, and the read
 * wrapper claims the oldest entry that fits.
 */
function holdRead(path: string, position: number, snapshot = false): HeldRead {
  let arrive: () => void = () => {};
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    arrive = resolve;
  });
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const hold: HeldRead = {
    path,
    position,
    snapshot,
    held,
    gate,
    claimed: false,
    arrive: () => arrive(),
    release: () => release(),
  };
  io.holds.push(hold);
  return hold;
}

const DATE = "2026-11-14";
const STARTED = "2026-11-14T00:00:00+00:00";
const ENDED = "2026-11-14T00:05:00+00:00";
const NOW = Date.parse("2026-11-14T00:10:00.000Z");
/** Two distinct modification times, so a same-size rewrite is distinguishable without a clock race. */
const TIME_ONE = new Date("2026-11-14T00:20:00.000Z");
const TIME_TWO = new Date("2026-11-14T01:20:00.000Z");

const STATE_RUNNING = JSON.stringify({
  name: "stage-implement",
  state: "running",
  started: STARTED,
  model: "provider/model",
  pid: 111,
  agent_pid: 222,
});
const LOCK = JSON.stringify({ pid: 111, agent_pid: 222 });

let root = "";
let alternate = "";

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "gdd-store-io-"));
  alternate = await mkdtemp(join(tmpdir(), "gdd-store-io-alt-"));
  io.opens.clear();
  io.reads.length = 0;
  io.failOpen.clear();
});

afterEach(async () => {
  // A hold a failing assertion left queued or parked would keep a pass inside a read, with its file
  // handle open, past cleanup: opening every gate lets that pass resume and close it.
  for (const hold of io.holds.splice(0)) hold.release();
  await rm(root, { recursive: true, force: true });
  await rm(alternate, { recursive: true, force: true });
});

function event(payload: Record<string, unknown>): string {
  return `${JSON.stringify(payload)}\n`;
}

/** A JSON line of exactly `width` characters including its newline, so a rewrite can hold the size. */
function fixedLine(type: string, width: number, extra: Record<string, unknown> = {}): string {
  const base = JSON.stringify({ ...extra, type, pad: "" });
  const filler = "x".repeat(Math.max(0, width - 1 - base.length));
  return `${JSON.stringify({ ...extra, type, pad: filler })}\n`;
}

async function writeRun(
  slug: string,
  files: Record<string, string | Uint8Array>,
  where = root,
  date = DATE,
): Promise<string> {
  const dir = join(where, date, slug);
  await mkdir(dir, { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    await writeFile(join(dir, name), content);
  }
  return dir;
}

function fakeProbe(alive: number[] = []): LivenessProbe {
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

function makeStore(alive: number[] = [], config: Partial<StoreConfig> = {}) {
  const settings: StoreConfig = { runRoot: root, tailLines: 5, ...config };
  const logs: string[] = [];
  const store = createRunStore({
    probe: fakeProbe(alive),
    config: () => settings,
    env: {},
    now: () => NOW,
    log: (message) => logs.push(message),
  });
  return { store, settings, logs };
}

function eventPath(dir: string): string {
  return join(dir, "events.ndjson");
}

function readsOf(path: string): Read[] {
  return io.reads.filter((read) => read.path === path);
}

function bytesReadOf(path: string): number {
  return readsOf(path).reduce((total, read) => total + read.bytes, 0);
}

/**
 * The read budget of an append: the counting pass checks the single byte just before the prefix it
 * had consumed — the boundary probe that keeps splice detection — and both it and the tail window
 * then read only the bytes that were added. Nothing may start before the old end of the file, which
 * would be a re-read of the retained prefix. The one boundary byte is charged explicitly here.
 */
function expectAppendReads(reads: Read[], oldSize: number, consumed: number, appended: number): void {
  const probes = reads.filter((read) => read.position === consumed - 1 && read.bytes === 1);
  expect(probes).toHaveLength(1);
  for (const read of reads) {
    if (probes.includes(read)) continue;
    expect(read.position).toBeGreaterThanOrEqual(oldSize);
  }
  const content = reads.filter((read) => !probes.includes(read));
  expect(content.reduce((total, read) => total + read.bytes, 0)).toBeLessThanOrEqual(2 * appended);
}

function typesOf(events: { type: string }[]): string[] {
  return events.map((entry) => entry.type);
}

describe("run store file revisions", () => {
  it("answers an unchanged list and follow without reading the retained log again", async () => {
    const log =
      event({ type: "turn_end" }) +
      event({ type: "tool_execution_start", toolCallId: "a", toolName: "read" }) +
      event({ type: "turn_end" });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": log,
      "answer.md": "partial answer\n",
      "session.id": "session-1\n",
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const cold = await store.listRuns();
    expect(cold.runs[0].turns).toBe(2);
    expect(cold.runs[0].eventLines).toBe(3);
    expect(cold.runs[0].sessionId).toBe("session-1");
    // The cold pass reads the log once, which is what makes the warm assertions below mean anything.
    expect(io.opens.get(events)).toBe(1);
    expect(bytesReadOf(events)).toBe(Buffer.byteLength(log));

    const firstFollow = await store.follow(id);
    expect(typesOf(firstFollow.events)).toEqual(["turn_end", "tool_execution_start", "turn_end"]);
    expect(firstFollow.answerTail).toBe("partial answer");

    const opensBefore = io.opens.get(events) ?? 0;
    const readsBefore = readsOf(events).length;
    const stateReadsBefore = readsOf(join(dir, "state.json")).length;

    const warm = await store.listRuns();
    const secondFollow = await store.follow(id);

    expect(warm.runs[0].turns).toBe(2);
    expect(secondFollow.events).toEqual(firstFollow.events);
    expect(secondFollow.answerTail).toBe("partial answer");
    // No open means no one-byte boundary probe either; no read means no parse of retained bytes.
    expect(io.opens.get(events)).toBe(opensBefore);
    expect(readsOf(events).length).toBe(readsBefore);
    expect(readsOf(join(dir, "state.json")).length).toBe(stateReadsBefore);
  });

  it("reads only appended bytes and shows the event a split line completes", async () => {
    const marker = "SECRET-MARKER-io-1";
    const full = JSON.stringify({ type: "turn_end" });
    const log = event({ type: "turn_end" }) + full.slice(0, 10);
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": log,
      "answer.md": marker,
    });
    const { store, logs } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const cold = await store.listRuns();
    expect(cold.runs[0].turns).toBe(1);
    expect(cold.runs[0].eventLines).toBe(1);
    // An unfinished line that is not yet valid JSON is not shown, exactly as before the cache.
    const firstFollow = await store.follow(id);
    expect(typesOf(firstFollow.events)).toEqual(["turn_end"]);

    const seen = io.reads.length;
    const appended = `${full.slice(10)}\n` + event({ type: "turn_end" });
    await appendFile(events, appended, "utf8");

    const warm = await store.listRuns();
    const secondFollow = await store.follow(id);

    expect(warm.runs[0].turns).toBe(3);
    expect(warm.runs[0].eventLines).toBe(3);
    expect(typesOf(secondFollow.events)).toEqual(["turn_end", "turn_end", "turn_end"]);
    expect(logs.filter((message) => message.includes("recount"))).toEqual([]);
    expect(logs.join("\n")).not.toContain(marker);

    const added = io.reads.slice(seen).filter((read) => read.path === events);
    // The ten bytes of the unfinished line were read but never counted, so they are not consumed.
    const consumed = Buffer.byteLength(log) - Buffer.byteLength(full.slice(0, 10));
    expectAppendReads(added, Buffer.byteLength(log), consumed, Buffer.byteLength(appended));
  });

  it("shows a valid unfinished event once it is complete and never twice", async () => {
    const tool = JSON.stringify({
      type: "tool_execution_start",
      toolCallId: "a",
      toolName: "bash",
      intent: "Run the suite",
    });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": event({ type: "turn_end" }) + tool,
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const cold = await store.follow(id);
    // The event is complete JSON without its newline, which is still an event the client shows.
    expect(typesOf(cold.events)).toEqual(["turn_end", "tool_execution_start"]);
    expect(cold.events[1].intent).toBe("Run the suite");

    await appendFile(events, `\n${event({ type: "turn_end" })}`, "utf8");
    const warm = await store.listRuns();
    const rest = await store.follow(id);

    expect(warm.runs[0].turns).toBe(2);
    expect(warm.runs[0].toolCalls).toBe(1);
    expect(warm.runs[0].eventLines).toBe(3);
    expect(typesOf(rest.events)).toEqual(["turn_end", "tool_execution_start", "turn_end"]);
    expect(rest.events[1].intent).toBe("Run the suite");
  });

  it("counts and displays an event whose character arrives in two writes", async () => {
    const line =
      JSON.stringify({
        type: "tool_execution_start",
        toolCallId: "a",
        toolName: "bash",
        intent: "café ☕",
      }) + "\n";
    const full = Buffer.from(event({ type: "turn_end" }) + line, "utf8");
    const cutoff = full.indexOf(Buffer.from("é", "utf8")) + 1;
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": full.subarray(0, cutoff),
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const cold = await store.listRuns();
    expect(cold.runs[0].turns).toBe(1);
    expect(cold.runs[0].toolCalls).toBe(0);
    const half = await store.follow(id);
    expect(typesOf(half.events)).toEqual(["turn_end"]);

    const seen = io.reads.length;
    await appendFile(events, full.subarray(cutoff));
    const warm = await store.listRuns();
    const rest = await store.follow(id);

    expect(warm.runs[0].toolCalls).toBe(1);
    expect(warm.runs[0].eventLines).toBe(2);
    expect(typesOf(rest.events)).toEqual(["turn_end", "tool_execution_start"]);
    expect(rest.events[1].intent).toBe("café ☕");
    // Everything up to and including the first line's newline was counted; the rest of the file is
    // the unfinished line, whose bytes arrive in this append.
    const consumed = full.indexOf(0x0a) + 1;
    expectAppendReads(
      io.reads.slice(seen).filter((read) => read.path === events),
      cutoff,
      consumed,
      full.length - cutoff,
    );
  });

  it("serves a changed tail length immediately from the same held bytes", async () => {
    const log = Array.from({ length: 12 }, (_, index) =>
      event({ type: "turn_end", timestamp: `2026-11-14T00:00:${String(index).padStart(2, "0")}.000Z` }),
    ).join("");
    const answer = `${Array.from({ length: 12 }, (_, index) => `line ${index}`).join("\n")}\n`;
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": log,
      "answer.md": answer,
    });
    const { store } = makeStore([222], { tailLines: 3 });
    const id = `${DATE}/stage-implement`;

    const short = await store.follow(id);
    expect(short.events).toHaveLength(3);
    expect(short.events[2].at).toBe("2026-11-14T00:00:11.000Z");
    expect(short.answerTail?.split("\n")).toEqual(["line 9", "line 10", "line 11"]);

    // One more same-length poll holds the revisions fixed before the measurement: the first pass
    // after the writer's writes can still see metadata the filesystem has not settled (a change time
    // that moves once more on this platform), and a cache must read again when a revision really
    // moved. This is not a retry or a wait — it is the poll that follows in the live store.
    const warmed = await store.follow(id);
    expect(warmed.events).toEqual(short.events);
    const seen = io.reads.length;

    const long = await store.follow(id, 12);
    expect(long.events).toHaveLength(12);
    expect(long.events[0].at).toBe("2026-11-14T00:00:00.000Z");
    expect(long.answerTail?.split("\n")).toEqual(
      Array.from({ length: 12 }, (_, index) => `line ${index}`),
    );
    // A changed limit must be served from what is already held: the failure names any read made.
    expect(
      io.reads
        .slice(seen)
        .map((read) => `${read.path.slice(dir.length + 1)}@${read.position}+${read.bytes}`),
    ).toEqual([]);

    const single = await store.follow(id, 1);
    expect(single.events.map((entry) => entry.at)).toEqual(["2026-11-14T00:00:11.000Z"]);
    expect(single.answerTail).toBe("line 11");
    expect(
      io.reads
        .slice(seen)
        .map((read) => `${read.path.slice(dir.length + 1)}@${read.position}+${read.bytes}`),
    ).toEqual([]);
  });

  it("recounts a same-size rewrite the metadata exposes instead of keeping stale numbers", async () => {
    const width = 200;
    const message = {
      role: "assistant",
      provider: "ghc",
      model: "gpt-6.1-sol",
      usage: { cost: { total: 0.5 } },
    };
    const before = fixedLine("turn_end", width).repeat(3);
    const after =
      fixedLine("turn_end", width) +
      fixedLine("message_end", width, { message }) +
      fixedLine("turn_end", width);
    expect(Buffer.byteLength(after)).toBe(Buffer.byteLength(before));
    // A line boundary sits where the counters had consumed the log, so only the metadata differs.
    expect(before.charCodeAt(2 * width - 1)).toBe(0x0a);
    expect(after.charCodeAt(2 * width - 1)).toBe(0x0a);

    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": before,
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);
    await utimes(events, TIME_ONE, TIME_ONE);

    const cold = await store.listRuns();
    expect(cold.runs[0].turns).toBe(3);
    expect(cold.runs[0].costUsd).toBe(0);
    const firstFollow = await store.follow(id);
    expect(typesOf(firstFollow.events)).toEqual(["turn_end", "turn_end", "turn_end"]);

    const seen = io.reads.length;
    await writeFile(events, after, "utf8");
    await utimes(events, TIME_TWO, TIME_TWO);

    const warm = await store.listRuns();
    const secondFollow = await store.follow(id);

    expect(warm.runs[0].turns).toBe(2);
    expect(warm.runs[0].costUsd).toBeCloseTo(0.5, 6);
    expect(warm.runs[0].eventLines).toBe(3);
    expect(warm.runs[0].model.observed.map((usage) => usage.model)).toEqual(["gpt-6.1-sol"]);
    expect(typesOf(secondFollow.events)).toEqual(["turn_end", "message_end", "turn_end"]);

    const recount = io.reads.slice(seen).filter((read) => read.path === events);
    expect(recount.some((read) => read.position === 0)).toBe(true);
    expect(recount.reduce((total, read) => total + read.bytes, 0)).toBeGreaterThanOrEqual(
      Buffer.byteLength(after),
    );
  });

  it("recounts a same-size replacement and a shrunken log from byte zero", async () => {
    const width = 40;
    const original = fixedLine("turn_end", width).repeat(5);
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": original,
    });
    const { store } = makeStore([222]);
    const events = eventPath(dir);

    const cold = await store.listRuns();
    expect(cold.runs[0].turns).toBe(5);

    const replacement = join(dir, "events.replacement");
    await writeFile(
      replacement,
      fixedLine("turn_end", width) +
        fixedLine("session", width) +
        fixedLine("turn_end", width) +
        fixedLine("session", width) +
        fixedLine("session", width),
      "utf8",
    );
    await rename(replacement, events);

    const seenReplacement = io.reads.length;
    const replaced = await store.listRuns();
    expect(replaced.runs[0].turns).toBe(2);
    expect(replaced.runs[0].eventLines).toBe(5);
    expect(
      io.reads.slice(seenReplacement).some((read) => read.path === events && read.position === 0),
    ).toBe(true);

    await writeFile(events, fixedLine("turn_end", width), "utf8");
    const seenShrink = io.reads.length;
    const shrunk = await store.listRuns();
    expect(shrunk.runs[0].turns).toBe(1);
    expect(shrunk.runs[0].eventLines).toBe(1);
    expect(io.reads.slice(seenShrink).some((read) => read.path === events && read.position === 0)).toBe(
      true,
    );
  });

  it("rebuilds the followed tail when the counting pass detects an in-place splice", async () => {
    const before =
      event({
        type: "tool_execution_start",
        toolCallId: "a",
        toolName: "bash",
        intent: "stale intent",
      }) +
      fixedLine("turn_end", 40, { timestamp: "2026-11-14T00:00:01.000Z" }) +
      fixedLine("turn_end", 40, { timestamp: "2026-11-14T00:00:02.000Z" });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": before,
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const cold = await store.follow(id, 10);
    expect(typesOf(cold.events)).toEqual(["tool_execution_start", "turn_end", "turn_end"]);
    expect(cold.summary?.turns).toBe(2);

    // The launcher's splice, written in place and larger than what it replaces: only the boundary
    // the counters consumed — or a marker in the new bytes — says the retained prefix is gone.
    const spliced =
      event({ type: "truncated", dropped_bytes: 5000, retained_bytes: 120 }) +
      fixedLine("turn_end", 200, { timestamp: "2026-11-14T00:30:00.000Z" });
    expect(Buffer.byteLength(spliced)).toBeGreaterThan(Buffer.byteLength(before));
    expect(spliced.charCodeAt(Buffer.byteLength(before) - 1)).not.toBe(0x0a);
    await writeFile(events, spliced, "utf8");

    const warm = await store.follow(id, 10);
    expect(warm.summary?.turns).toBe(1);
    expect(warm.summary?.eventsTruncated).toBe(true);
    expect(warm.summary?.eventsDroppedBytes).toBe(5000);
    expect(typesOf(warm.events)).toEqual(["truncated", "turn_end"]);
    expect(warm.events[1].at).toBe("2026-11-14T00:30:00.000Z");
    expect(warm.events.some((entry) => entry.intent === "stale intent")).toBe(false);
  });

  it("never publishes an invalidated tail from an append read that resumes after the recount", async () => {
    const before =
      event({
        type: "tool_execution_start",
        toolCallId: "a",
        toolName: "bash",
        intent: "stale intent",
      }) +
      fixedLine("turn_end", 40, { timestamp: "2026-11-14T00:00:01.000Z" }) +
      fixedLine("turn_end", 40, { timestamp: "2026-11-14T00:00:02.000Z" });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": before,
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    // The warm follow is what leaves the events a later splice removes in the tail cache.
    const warm = await store.follow(id, 10);
    expect(typesOf(warm.events)).toEqual(["tool_execution_start", "turn_end", "turn_end"]);
    expect(warm.summary?.turns).toBe(2);

    const appended = event({ type: "turn_end", timestamp: "2026-11-14T00:10:00.000Z" });
    await appendFile(events, appended, "utf8");
    const oldSize = Buffer.byteLength(before);
    const consumed = oldSize + Buffer.byteLength(appended);

    // A splice written in place and larger than both the log it replaces and the prefix the counting
    // pass consumed: only the byte that prefix called a boundary can report the loss.
    const spliced =
      event({ type: "truncated", dropped_bytes: 5000, retained_bytes: 120 }) +
      fixedLine("turn_end", 400, { timestamp: "2026-11-14T00:30:00.000Z" });
    expect(Buffer.byteLength(spliced)).toBeGreaterThan(consumed);
    expect(spliced.charCodeAt(consumed - 1)).not.toBe(0x0a);
    // No line boundary between the held size and the splice's last byte, so the held pass's
    // extension read parses no line of its own: what it can show is the prefix it already held.
    expect(spliced.slice(oldSize, -1)).not.toContain("\n");

    // The counting pass's append read and the tail pass's extension read both begin at `oldSize`, so
    // only the order they arrive in tells them apart. The first snaps its bytes before the splice
    // lands, which keeps the counting pass on the log it started with; the second parks the tail
    // pass with that log's prefix in hand. The read at byte 0 is the recount a concurrent follow
    // makes once it finds the consumed boundary gone, and it drops the tail cache on the way there.
    const appendRead = holdRead(events, oldSize, true);
    const extensionRead = holdRead(events, oldSize);
    const recountRead = holdRead(events, 0);

    const older = store.follow(id, 10);
    await appendRead.held;
    await writeFile(events, spliced, "utf8");
    appendRead.release();
    await extensionRead.held;

    const concurrent = store.follow(id, 10);
    await recountRead.held;
    recountRead.release();
    extensionRead.release();
    const [olderFollow, concurrentFollow] = await Promise.all([older, concurrent]);

    // The older pass counted a revision the splice then replaced, and that revision's counters are
    // what its summary may report. Its tail may not be that revision's prefix: published under the
    // spliced file's revision, it would outlive every later poll.
    expect(olderFollow.summary?.turns).toBe(3);
    expect(concurrentFollow.summary?.turns).toBe(1);
    expect(concurrentFollow.summary?.eventsTruncated).toBe(true);
    expect(concurrentFollow.summary?.eventsDroppedBytes).toBe(5000);

    for (const follow of [olderFollow, concurrentFollow]) {
      expect(typesOf(follow.events)).toEqual(["truncated", "turn_end"]);
      expect(follow.events[1].at).toBe("2026-11-14T00:30:00.000Z");
      expect(follow.events.some((entry) => entry.intent === "stale intent")).toBe(false);
      expect(follow.events.some((entry) => entry.at === "2026-11-14T00:10:00.000Z")).toBe(false);
    }

    // The unchanged poll after both is the one that must not keep serving what the splice removed,
    // and the tail it serves has to describe the log its own summary counted.
    const later = await store.follow(id, 10);
    expect(later.events).toEqual(olderFollow.events);
    expect(later.events).toEqual(concurrentFollow.events);
    expect(later.summary?.turns).toBe(1);
    expect(later.events.filter((entry) => entry.type === "turn_end")).toHaveLength(
      later.summary?.turns ?? 0,
    );
  });

  it("re-reads state, stats, answer and model files when their content changes", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": event({ type: "turn_end" }),
      "answer.md": "one\n",
    });
    const { store } = makeStore([222]);

    const cold = await store.listRuns();
    expect(cold.runs[0].state).toBe("running");
    expect(cold.runs[0].liveness).toBe("running");
    expect(cold.runs[0].model.requested).toBe("provider/model");
    expect(cold.runs[0].countersFrom).toBe("events");
    expect(cold.runs[0].answerChars).toBe(4);

    await writeFile(
      join(dir, "state.json"),
      JSON.stringify({
        name: "stage-implement",
        state: "done",
        started: STARTED,
        ended: ENDED,
        duration_s: 300,
        turns: 8,
        tool_calls: 15,
        cost_usd: 0.4,
        model: "ghc/gpt-6.1-sol",
        pid: 111,
        agent_pid: 222,
      }),
      "utf8",
    );
    await writeFile(join(dir, "finalized"), "0", "utf8");
    await writeFile(
      join(dir, "events.stats.json"),
      JSON.stringify({
        total_bytes: 100,
        retained_bytes: 100,
        dropped_bytes: 0,
        truncated: false,
      }),
      "utf8",
    );
    await writeFile(join(dir, "answer.md"), "a longer answer\n", "utf8");

    const warm = await store.listRuns();
    const run = warm.runs[0];
    expect(run.state).toBe("done");
    expect(run.liveness).toBe("settled");
    expect(run.countersFrom).toBe("state");
    expect(run.turns).toBe(8);
    expect(run.toolCalls).toBe(15);
    expect(run.costUsd).toBeCloseTo(0.4, 6);
    expect(run.model.requested).toBe("ghc/gpt-6.1-sol");
    expect(run.answerChars).toBe(16);
    expect(run.warnings).not.toContain("state-missing");
    expect(warm.stats.byState.done).toBe(1);
    expect(warm.stats.turns).toBe(8);
  });

  it("re-reads the answer tail after a same-size rewrite", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "answer.md": "one\n",
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const answer = join(dir, "answer.md");
    await utimes(answer, TIME_ONE, TIME_ONE);

    const cold = await store.follow(id);
    expect(cold.answerTail).toBe("one");

    await writeFile(answer, "two\n", "utf8");
    await utimes(answer, TIME_TWO, TIME_TWO);

    const warm = await store.follow(id);
    expect(warm.answerTail).toBe("two");
  });

  it("retries a missing log and a failed read instead of freezing a verdict", async () => {
    const missingDir = await writeRun("crash-without-log", { lock: JSON.stringify({ pid: 555 }) });
    const { store } = makeStore([]);
    const events = eventPath(missingDir);

    const missing = await store.listRuns();
    const missingRun = missing.runs.find((run) => run.slug === "crash-without-log");
    expect(missingRun?.countersFrom).toBe("none");
    expect(missingRun?.warnings).toContain("log-unreadable");

    await writeFile(events, fixedLine("turn_end", 40).repeat(3), "utf8");
    const created = await store.listRuns();
    const createdRun = created.runs.find((run) => run.slug === "crash-without-log");
    expect(createdRun?.countersFrom).toBe("events");
    expect(createdRun?.turns).toBe(3);

    // A run whose first read fails has nothing folded yet, so the failure is reported, and the
    // next pass reads the log from its start rather than remembering a verdict.
    const unreadableDir = await writeRun("unreadable-log", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": fixedLine("turn_end", 40).repeat(3),
    });
    const unreadableEvents = eventPath(unreadableDir);
    io.failOpen.add(unreadableEvents);
    const failed = await store.listRuns();
    const failedRun = failed.runs.find((run) => run.slug === "unreadable-log");
    expect(failedRun?.warnings).toContain("log-unreadable");
    expect(failedRun?.turns).toBeNull();
    const failedFollow = await store.follow(`${DATE}/unreadable-log`);
    expect(failedFollow.found).toBe(true);
    expect(failedFollow.events).toEqual([]);

    io.failOpen.delete(unreadableEvents);
    const recovered = await store.listRuns();
    const recoveredRun = recovered.runs.find((run) => run.slug === "unreadable-log");
    expect(recoveredRun?.warnings).not.toContain("log-unreadable");
    expect(recoveredRun?.turns).toBe(3);
    expect(recoveredRun?.eventLines).toBe(3);
  });

  it("keeps counters and tails exact when callers overlap", async () => {
    const lines = Array.from({ length: 200 }, (_, index) =>
      event({
        type: "tool_execution_end",
        toolCallId: `t${index}`,
        toolName: "read",
        result: "x".repeat(1000),
      }),
    );
    const log = lines.join("") + event({ type: "turn_end" });
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": log,
      "answer.md": "answer\n",
    });
    const { store } = makeStore([222], { tailLines: 100 });
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    const [listA, followA, followB, listB] = await Promise.all([
      store.listRuns(),
      store.follow(id, 120),
      store.follow(id, 60),
      store.listRuns(),
    ]);
    for (const list of [listA, listB]) {
      expect(list.runs[0].turns).toBe(1);
      expect(list.runs[0].eventLines).toBe(201);
    }
    expect(followA.summary?.eventLines).toBe(201);
    expect(followA.events).toHaveLength(120);
    expect(followB.events).toHaveLength(60);
    expect(followA.events.slice(-60)).toEqual(followB.events);

    await appendFile(events, event({ type: "turn_end" }), "utf8");
    const [listC, followC, followD] = await Promise.all([
      store.listRuns(),
      store.follow(id, 120),
      store.follow(id, 60),
    ]);
    expect(listC.runs[0].turns).toBe(2);
    expect(listC.runs[0].eventLines).toBe(202);
    expect(followC.events).toHaveLength(120);
    expect(followD.events).toHaveLength(60);
    expect(followC.events.slice(-60)).toEqual(followD.events);
    expect(followC.events[119].type).toBe("turn_end");
    expect(followC.events[119].at).toBeNull();
  });

  it("bounds both tails to their byte window and extends them with appended bytes", async () => {
    const huge = fixedLine("turn_end", 400 * 1024);
    const appendedEvent = event({ type: "turn_end", timestamp: "2026-11-14T00:00:01.000Z" });
    const answer = `${Array.from({ length: 9000 }, (_, index) => `line ${String(index).padStart(4, "0")}`).join("\n")}\n`;
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": huge,
      "answer.md": answer,
    });
    const { store } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    // The longest tail a caller may ask for, which is the request the window bounds are about.
    const cold = await store.follow(id, 2000);
    // The window is the last 256 KiB, which lies inside the one enormous line: no complete line.
    expect(cold.events).toEqual([]);
    const answerTail = cold.answerTail ?? "";
    const answerLines = answerTail.split("\n");
    expect(answerLines).toHaveLength(2000);
    expect(answerLines[answerLines.length - 1]).toBe("line 8999");
    expect(answerLines[0] > "line 6000").toBe(true);
    expect(Buffer.byteLength(answerTail)).toBeLessThanOrEqual(64 * 1024);

    const seen = io.reads.length;
    await appendFile(events, appendedEvent, "utf8");
    await appendFile(join(dir, "answer.md"), "line 9000\n", "utf8");

    const warm = await store.follow(id, 2000);
    expect(typesOf(warm.events)).toEqual(["turn_end"]);
    expect(warm.events[0].at).toBe("2026-11-14T00:00:01.000Z");
    const extended = warm.answerTail ?? "";
    expect(extended.endsWith("line 9000")).toBe(true);
    expect(extended.split("\n")).toHaveLength(2000);
    expect(Buffer.byteLength(extended)).toBeLessThanOrEqual(64 * 1024);

    // Each file pays only for its own append: the counter probe plus the new bytes, once per reader.
    const added = io.reads.slice(seen);
    expectAppendReads(
      added.filter((read) => read.path === events),
      Buffer.byteLength(huge),
      Buffer.byteLength(huge),
      Buffer.byteLength(appendedEvent),
    );
    const answerReads = added.filter((read) => read.path === join(dir, "answer.md"));
    expect(answerReads.reduce((total, read) => total + read.bytes, 0)).toBeLessThanOrEqual(
      Buffer.byteLength("line 9000\n"),
    );
  });

  it("clears run caches on a root change and on dispose", async () => {
    const dir = await writeRun("stage-implement", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson": fixedLine("turn_end", 40).repeat(3),
    });
    await writeRun(
      "stage-implement",
      {
        "state.json": STATE_RUNNING,
        lock: LOCK,
        "events.ndjson": fixedLine("turn_end", 40),
      },
      alternate,
    );
    const { store, settings, logs } = makeStore([222]);
    const id = `${DATE}/stage-implement`;
    const events = eventPath(dir);

    await store.listRuns();
    await store.follow(id);
    const warmReads = readsOf(events).length;

    settings.runRoot = alternate;
    const other = await store.listRuns();
    expect(other.runRoot).toBe(alternate);
    expect(other.runs[0].turns).toBe(1);
    expect(readsOf(events).length).toBe(warmReads);
    expect(logs.some((message) => message.includes("run root changed"))).toBe(true);

    settings.runRoot = root;
    const seenReturn = io.reads.length;
    const back = await store.listRuns();
    expect(back.runRoot).toBe(root);
    expect(back.runs[0].turns).toBe(3);
    expect(
      io.reads.slice(seenReturn).some((read) => read.path === events && read.position === 0),
    ).toBe(true);

    store.dispose();
    const seenDispose = io.reads.length;
    const afterDispose = await store.listRuns();
    expect(afterDispose.runs[0].turns).toBe(3);
    expect(
      io.reads.slice(seenDispose).some((read) => read.path === events && read.position === 0),
    ).toBe(true);
  });

  it("keeps exact all-run stats across a warmed scan", async () => {
    await writeRun("done-run", {
      "state.json": JSON.stringify({
        name: "done-run",
        state: "done",
        started: STARTED,
        ended: ENDED,
        turns: 4,
        tool_calls: 6,
        cost_usd: 0.25,
        pid: 111,
      }),
      finalized: "0",
      "events.ndjson": event({ type: "turn_end" }),
    });
    await writeRun("running-run", {
      "state.json": STATE_RUNNING,
      lock: LOCK,
      "events.ndjson":
        event({ type: "turn_end" }) +
        event({ type: "tool_execution_start", toolCallId: "a", toolName: "read" }),
    });
    const { store } = makeStore([222]);

    const cold = await store.listRuns();
    const warm = await store.listRuns();

    expect(cold.stats.total).toBe(2);
    expect(cold.stats.byState.done).toBe(1);
    expect(cold.stats.byState.running).toBe(1);
    expect(cold.stats.turns).toBe(5);
    expect(cold.stats.toolCalls).toBe(7);
    expect(cold.stats.costUsd).toBeCloseTo(0.25, 6);
    expect(warm.stats).toEqual(cold.stats);
    expect(warm.runs).toEqual(cold.runs);
  });
});
