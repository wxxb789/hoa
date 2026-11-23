import { randomUUID } from "node:crypto";
import type { Stats } from "node:fs";
import { open, readdir, stat, type FileHandle } from "node:fs/promises";
import { dirname, join } from "node:path";
import { isDeepStrictEqual } from "node:util";
import type {
  EventStats,
  FollowRunOutput,
  ListRunsDelta,
  ListRunsOutput,
  ListRunsUpdate,
  RunEvent,
  RunPathsOutput,
  RunSummary,
} from "../shared/runs";
import { MAX_TAIL_LINES, runLineageSchema } from "../shared/runs";
import {
  applyEventLine,
  asRecord,
  createCounters,
  snapshotCounters,
} from "./events";
import type { CounterSnapshot, RunCounters } from "./events";
import type { LivenessProbe, PidVerdict } from "./liveness";
import { resolveRunRoot, type RunRootResolution } from "./run-root";
import { summarizeRuns } from "../shared/stats";
import {
  mapRun,
  pidsOf,
  stateCountersTakePrecedence,
  type RunAnswer,
  type RunEventLog,
  type RunFiles,
  type RunFinalized,
  type RunLock,
  type RunStateFile,
} from "./state";

export type StoreConfig = { runRoot: string; tailLines: number };

export type StoreDeps = {
  probe: LivenessProbe;
  config(): StoreConfig;
  env?: NodeJS.ProcessEnv;
  now?(): number;
  log?(message: string): void;
};

export type RunStore = {
  listRuns(): Promise<ListRunsOutput>;
  listUpdate(knownRevision?: string): Promise<ListRunsUpdate>;
  paths(id: string): Promise<RunPathsOutput>;
  follow(id: string, tailLines?: number): Promise<FollowRunOutput>;
  dispose(): void;
};

/**
 * Files the launcher writes into a run directory, named once: every reader and the detail view's
 * path listing come from here, so renaming one is a single edit. `session.id` is read for the
 * session id but is not part of the listing.
 */
const RUN_FILES = {
  state: "state.json",
  events: "events.ndjson",
  previousEvents: "events.1.ndjson",
  stats: "events.stats.json",
  answer: "answer.md",
  lock: "lock",
  finalized: "finalized",
  prompt: "prompt.md",
  runnerOut: "runner.out",
  stderr: "stderr.log",
} as const;
const SESSION_FILE = "session.id";
/**
 * The GDD dispatcher's lineage sidecar: written once beside the launcher's files, listed with
 * neither the scan nor the path listing, and read only for the selected run's `runs.follow`.
 */
const LINEAGE_FILE = "lineage.json";

const DATE_DIR = /^\d{4}-\d{2}-\d{2}$/;
const TAIL_BYTES = 256 * 1024;
const ANSWER_TAIL_BYTES = 64 * 1024;
const COUNTER_CHUNK = 256 * 1024;
const JSON_READ_BYTES = 1024 * 1024;
const SESSION_READ_BYTES = 4096;
/**
 * The sidecar is one small document; a file past this bound is refused rather than parsed, so a
 * window that cut off its head cannot pass as lineage.
 */
const LINEAGE_READ_BYTES = 4096;
/** A body past this size is re-read each pass rather than held; the run files that matter are small. */
const BODY_CACHE_BYTES = 16 * 1024;
const BODY_CACHE_BUDGET = 16 * 1024 * 1024;
const SCAN_CONCURRENCY = 12;
const FINALIZED_RECHECK_MS = 30_000;
const ROOT_GRACE_MS = 30_000;
const EVENT_CACHE_BUDGET = 16 * 1024 * 1024;
const ANSWER_CACHE_BUDGET = 2 * 1024 * 1024;
/** Bound on the tail parser's scratch bookkeeping, which must not grow with a batch of tool starts. */
const SCRATCH_OPEN_TOOLS = 1024;
const NO_BYTES = Buffer.alloc(0);

type Tailer = {
  offset: number;
  pending: Buffer;
  counters: RunCounters;
  unreadable: boolean;
  /** File identity: a replaced file is a different file no matter what its size or times say. */
  identity: string;
  /** Revision the counters describe, once it was read to its last byte; empty before that. */
  revision: string;
  /** Size that revision had, which is how an append is told from a same-size rewrite. */
  revisionSize: number;
};

/**
 * A file body held by revision: a scan of an untouched run is answered from bytes already read
 * instead of the disk. A hit means the path still names the same file, at the same size, with the
 * same modification and change times — the signals the filesystem offers for "unchanged", whose
 * resolution is the limit rather than a guarantee that the content is equal.
 */
type BodyEntry = {
  dir: string;
  revision: string;
  want: number;
  text: string;
  weight: number;
};

/** One parsed event and the byte its line began at, which is how a window boundary is applied. */
type TailLine = { event: RunEvent; start: number };

/**
 * The event log's bounded tail, kept so an append costs only the bytes it added: `lines` holds the
 * events of terminated lines, `pending` the trailing bytes that are not a line yet, and a new event
 * is parsed when its last byte arrives rather than the whole window being read again.
 */
type EventTailState = {
  weight: number;
  identity: string;
  revision: string;
  size: number;
  windowStart: number;
  lines: TailLine[];
  pending: Buffer;
  pendingStart: number;
  pendingEvent: RunEvent | null | undefined;
  /** The unfinished line began before the window, so its held bytes are only a fragment. */
  pendingLost: boolean;
};

/** The answer file's bounded tail, held the same way: raw bytes that appends extend. */
type AnswerTailState = {
  weight: number;
  identity: string;
  revision: string;
  size: number;
  bytes: Buffer;
  lines: string[] | null;
};

type Counted = { counters: CounterSnapshot | null; unreadable: boolean; events: RunEventLog };
type FinalizedEntry = { run: RunSummary; directoryRevision: string; checkedAt: number };
type ListChanges = Pick<ListRunsDelta, "changes" | "removed" | "order">;
type ListSnapshot = {
  scan: ListRunsOutput;
  revision: string;
  previous?: { revision: string; changes: ListChanges };
};

/**
 * A file body: `text` holds the file's last `min(size, want)` bytes decoded, and `size` is the size
 * the file had when it was read — how a caller tells an oversized file from a truncated window.
 */
type FileText =
  | { kind: "missing" }
  | { kind: "unreadable" }
  | { kind: "text"; text: string; size: number };

export function createRunStore(deps: StoreDeps): RunStore {
  const env = deps.env ?? process.env;
  const now = deps.now ?? (() => Date.now());
  const tailers = new Map<string, Tailer>();
  const passes = new Map<string, Promise<Counted>>();
  const bodies = new Map<string, BodyEntry>();
  let bodyWeight = 0;
  const eventTails = new Map<string, EventTailState>();
  const eventTailPasses = new Map<string, Promise<EventTailState | null>>();
  const answerTails = new Map<string, AnswerTailState>();
  const answerTailPasses = new Map<string, Promise<AnswerTailState | null>>();
  const finalized = new Map<string, FinalizedEntry>();
  let rootKey: string | null = null;
  let generation = 0;
  let unavailableSince: number | null = null;
  const storeId = randomUUID();
  let revision = 0;
  let latestList: ListSnapshot | undefined;
  let listPass: Promise<ListSnapshot> | undefined;

  /**
   * Every cache is keyed under the resolved root, so a root change or a dispose retires all of them
   * at once. A pass already in flight keeps working on the objects it started with; the next scan
   * drops whatever it stored for a directory that is no longer there.
   */
  function clearCaches(): void {
    tailers.clear();
    passes.clear();
    bodies.clear();
    bodyWeight = 0;
    eventTails.clear();
    eventTailPasses.clear();
    answerTails.clear();
    answerTailPasses.clear();
    finalized.clear();
  }

  function reset(): void {
    clearCaches();
    generation += 1;
    unavailableSince = null;
    listPass = undefined;
    latestList = undefined;
  }

  function resolution(): RunRootResolution {
    const { runRoot } = deps.config();
    const next = resolveRunRoot(runRoot, env);
    const nextKey = `${next.root}|${next.source}`;
    if (nextKey !== rootKey) {
      if (rootKey !== null) deps.log?.(`run root changed to ${next.root} (${next.source}); clearing caches`);
      reset();
      rootKey = nextKey;
    }
    return next;
  }

  function countersFor(dir: string): Promise<Counted> {
    // One pass per run at a time: an overlapping scan joins it rather than folding the same bytes twice.
    return singleFlight(passes, dir, () => countAppended(dir));
  }

  async function inspectFinalizedEvents(dir: string): Promise<Counted> {
    let info: Stats;
    try {
      info = await stat(join(dir, RUN_FILES.events));
    } catch {
      return { counters: null, unreadable: false, events: { exists: false, bytes: 0 } };
    }
    // A follow may be mutating the counters before it records the new revision.
    const tailer = passes.has(dir) ? undefined : tailers.get(dir);
    const counters = tailer && tailer.offset === info.size && tailer.revision === revisionOf(info) &&
      tailer.counters.lines > 0 ? snapshotCounters(tailer.counters) : null;
    return { counters, unreadable: false, events: { exists: true, bytes: info.size } };
  }

  /**
   * Fold `events.ndjson` into the run's counters, reading only what was appended since the last
   * pass. The launcher splices the log at its bound by replacing it with
   * `head + truncated marker + tail`, so five cheap signals restart the count from byte 0 — a
   * replaced file, a shrunken file, a same-size rewrite, a lost line boundary before the consumed
   * prefix, or a splice marker in the newly read bytes — and the numbers stay a description of one
   * revision of the log rather than a mix of two.
   */
  async function countAppended(dir: string): Promise<Counted> {
    let tailer = tailers.get(dir);
    if (!tailer) {
      tailer = {
        offset: 0,
        pending: Buffer.alloc(0),
        counters: createCounters(),
        unreadable: false,
        identity: "",
        revision: "",
        revisionSize: -1,
      };
      tailers.set(dir, tailer);
    }
    const current = tailer;
    const path = join(dir, RUN_FILES.events);
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      return {
        counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
        unreadable: false,
        events: { exists: false, bytes: 0 },
      };
    }
    const events = { exists: true, bytes: info.size };
    const revision = revisionOf(info);
    if (current.revision === revision && current.offset === info.size) {
      // This revision is already folded to its last byte, so there is nothing to read and no
      // line-boundary probe to make: size and timestamps still say this is the log that was
      // counted, down to the resolution those timestamps have.
      return {
        counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
        unreadable: false,
        events,
      };
    }
    const identity = identityOf(info);
    const consumed = current.offset - current.pending.length;
    if (current.identity !== "" && current.identity !== identity) {
      resetTailer(current, dir, "log replaced");
    } else if (info.size < consumed) {
      resetTailer(current, dir, "log shrank");
    } else if (current.revision !== "" && info.size === current.revisionSize) {
      // Same size, different revision: bytes under the counters were rewritten in place, so the
      // numbers would describe a log that no longer exists.
      resetTailer(current, dir, "log rewritten in place");
    } else if (consumed > 0 && !(await endsWithNewline(path, consumed))) {
      resetTailer(current, dir, "line boundary lost");
    }

    if ((await readAppended(path, current, info.size)) === "spliced") {
      resetTailer(current, dir, "launcher spliced the log");
      await readAppended(path, current, info.size);
    }
    current.identity = identity;
    if (current.offset === info.size) {
      // Record the revision this pass read to its end, never a later one the file reached while the
      // pass was reading: a later stat then still differs, so the new bytes are consumed next time.
      current.revision = revision;
      current.revisionSize = info.size;
    }
    return {
      counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
      unreadable: current.unreadable,
      events,
    };
  }

  function resetTailer(tailer: Tailer, dir: string, reason: string): void {
    deps.log?.(`recount ${dir} from byte 0: ${reason}`);
    tailer.offset = 0;
    tailer.pending = Buffer.alloc(0);
    tailer.counters = createCounters();
    tailer.unreadable = false;
    // The tail window's events were parsed from the same prefix these counters just gave up on, so
    // a later follow rebuilds it from the current log instead of extending rewritten bytes.
    eventTails.delete(dir);
  }

  async function readAppended(
    path: string,
    tailer: Tailer,
    size: number,
  ): Promise<"appended" | "spliced"> {
    if (size <= tailer.offset) return "appended";
    const startOffset = tailer.offset;
    const splicesBefore = tailer.counters.splices;
    try {
      const handle = await open(path, "r");
      try {
        let offset = tailer.offset;
        while (offset < size) {
          const length = Math.min(COUNTER_CHUNK, size - offset);
          const buffer = Buffer.allocUnsafe(length);
          const { bytesRead } = await handle.read(buffer, 0, length, offset);
          if (bytesRead <= 0) break;
          const chunk = buffer.subarray(0, bytesRead);
          const combined =
            tailer.pending.length > 0 ? Buffer.concat([tailer.pending, chunk]) : chunk;
          const lastNewline = combined.lastIndexOf(0x0a);
          if (lastNewline === -1) {
            tailer.pending = Buffer.from(combined);
            offset += bytesRead;
            continue;
          }
          const complete = combined.subarray(0, lastNewline).toString("utf8");
          tailer.pending = Buffer.from(combined.subarray(lastNewline + 1));
          offset += bytesRead;
          for (const line of complete.split("\n")) {
            applyEventLine(tailer.counters, line);
          }
        }
        tailer.offset = offset;
        tailer.unreadable = false;
      } finally {
        await handle.close();
      }
    } catch (error) {
      deps.log?.(`event log unreadable at ${path}: ${messageOf(error)}`);
      tailer.unreadable = true;
      return "appended";
    }
    // The fold owns what a splice marker means; this pass only asks whether it met one after
    // bytes the counters already covered.
    return startOffset > 0 && tailer.counters.splices > splicesBefore ? "spliced" : "appended";
  }

  /**
   * Read the last `want` bytes of a file, answering an unchanged file from the body cache instead
   * of the disk. An unreadable file is reported rather than thrown so one bad file cannot hide a
   * run. A file past the cache ceiling is read each pass rather than held.
   */
  async function readBody(path: string, want: number): Promise<FileText> {
    const started = generation;
    const cached = bodies.get(path);
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      if (started === generation) dropBody(path);
      return { kind: "missing" };
    }
    const revision = revisionOf(info);
    if (cached && cached.revision === revision && cached.want === want) {
      if (bodies.get(path) === cached) touch(bodies, path, cached);
      return { kind: "text", text: cached.text, size: info.size };
    }
    const start = Math.max(0, info.size - want);
    const bytes = info.size === 0 ? NO_BYTES : await readRange(path, start, info.size);
    if (bytes === null) {
      if (started === generation) dropBody(path);
      return { kind: "unreadable" };
    }
    const text = bytes.toString("utf8");
    if (started === generation) {
      dropBody(path);
      if (bytes.length <= BODY_CACHE_BYTES) {
        // Charge both UTF-16 text and keys, with a floor for map/entry overhead.
        const weight = 256 + 2 * (text.length + path.length + revision.length);
        bodies.set(path, { dir: dirname(path), revision, want, text, weight });
        bodyWeight += weight;
        while (bodyWeight > BODY_CACHE_BUDGET) dropBody(bodies.keys().next().value!);
      }
    }
    return { kind: "text", text, size: info.size };
  }

  function dropBody(path: string): void {
    const body = bodies.get(path);
    if (body && bodies.delete(path)) bodyWeight -= body.weight;
  }

  /**
   * Read exactly `[from, to)` through one handle. A short read means the file changed while it was
   * being read, so it is not content this caller can describe: it is reported like a failed read
   * and tried again on the next pass.
   */
  async function readRange(path: string, from: number, to: number): Promise<Buffer | null> {
    if (to <= from) return NO_BYTES;
    let handle: FileHandle;
    try {
      handle = await open(path, "r");
    } catch (error) {
      deps.log?.(`${path} unreadable: ${messageOf(error)}`);
      return null;
    }
    try {
      const buffer = Buffer.allocUnsafe(to - from);
      let filled = 0;
      while (filled < buffer.length) {
        const { bytesRead } = await handle.read(buffer, filled, buffer.length - filled, from + filled);
        if (bytesRead <= 0) break;
        filled += bytesRead;
      }
      if (filled < buffer.length) return null;
      return buffer;
    } catch (error) {
      deps.log?.(`${path} unreadable: ${messageOf(error)}`);
      return null;
    } finally {
      await handle.close();
    }
  }

  async function readJson(path: string): Promise<{ present: boolean; readable: boolean; value: unknown }> {
    const read = await readBody(path, JSON_READ_BYTES);
    if (read.kind === "missing") return { present: false, readable: false, value: null };
    if (read.kind === "unreadable") return { present: true, readable: false, value: null };
    try {
      return { present: true, readable: true, value: JSON.parse(read.text) };
    } catch {
      return { present: true, readable: false, value: null };
    }
  }

  /**
   * Validate one run's optional lineage sidecar. Every way the sidecar can
   * disappoint — absent, unreadable, larger than the cap, malformed JSON or a value the schema
   * rejects — answers the same way: no lineage. The file annotates the run, so it may never change
   * the run's own state, processes or tails; and a file past the cap is refused rather than parsed,
   * so a document whose head was cut off cannot pass as the run's lineage.
   */
  async function readLineage(dir: string): Promise<FollowRunOutput["lineage"]> {
    const read = await readBody(join(dir, LINEAGE_FILE), LINEAGE_READ_BYTES);
    if (read.kind !== "text" || read.size > LINEAGE_READ_BYTES) return undefined;
    let value: unknown;
    try {
      value = JSON.parse(read.text);
    } catch {
      return undefined;
    }
    const parsed = runLineageSchema.safeParse(value);
    return parsed.success ? parsed.data : undefined;
  }

  async function fileBytes(path: string): Promise<{ exists: boolean; bytes: number | null }> {
    try {
      return { exists: true, bytes: (await stat(path)).size };
    } catch {
      return { exists: false, bytes: null };
    }
  }

  async function readFiles(dir: string, date: string, slug: string, dirStat: Stats): Promise<RunFiles> {
    const [state, lockJson, finalizedText, statsJson, answerFile, sessionIdRead, previousEvents, lineage] =
      await Promise.all([
        readJson(join(dir, RUN_FILES.state)),
        readJson(join(dir, RUN_FILES.lock)),
        readJson(join(dir, RUN_FILES.finalized)),
        readJson(join(dir, RUN_FILES.stats)),
        fileBytes(join(dir, RUN_FILES.answer)),
        readBody(join(dir, SESSION_FILE), SESSION_READ_BYTES),
        fileBytes(join(dir, RUN_FILES.previousEvents)),
        readLineage(dir),
      ]);
    const values = asRecord(state.value) ?? {};
    const stateFile: RunStateFile = { present: state.present, readable: state.readable, values };

    const lockValue = asRecord(lockJson.value);
    const lock: RunLock | null = lockValue
      ? { pid: numberOrNull(lockValue.pid), agentPid: numberOrNull(lockValue.agent_pid) }
      : null;

    const finalized: RunFinalized = finalizedText.present
      ? { present: true, exitCode: parseExitCode(finalizedText.value) }
      : { present: false, exitCode: null };

    const statsValue = asRecord(statsJson.value);
    const stats: EventStats = statsValue
      ? {
          totalBytes: numberOrNull(statsValue.total_bytes),
          retainedBytes: numberOrNull(statsValue.retained_bytes),
          droppedBytes: numberOrNull(statsValue.dropped_bytes),
          truncated: typeof statsValue.truncated === "boolean" ? statsValue.truncated : null,
        }
      : null;

    const answer: RunAnswer = { exists: answerFile.exists, bytes: answerFile.bytes };
    const sessionId = sessionIdRead.kind === "text" ? sessionIdRead.text.trim() : "";

    return {
      dir,
      date,
      slug,
      state: stateFile,
      lock,
      finalized,
      stats,
      answer,
      events: { exists: false, bytes: 0, rotated: previousEvents.exists },
      lineage,
      sessionIdFromFile: sessionId ? sessionId.split(/\r?\n/)[0] : null,
      dirModifiedAt: dirStat.mtime.toISOString(),
    };
  }

  function summarize(files: RunFiles, derived: Counted): RunSummary {
    const pids = pidsOf(files.state.values, files.lock);
    const needsLiveness = !files.finalized.present && pids.length > 0;
    const verdicts: Map<number, PidVerdict> = needsLiveness
      ? deps.probe.verdicts(pids)
      : new Map();
    if (needsLiveness) {
      // Only the pids the inline probe could not decide need confirming, and confirmation
      // continues off the scan path: the next scan sees the verdict.
      const unproven = pids.filter((pid) => verdicts.get(pid) === "unknown");
      void deps.probe.refresh(unproven).catch((error: unknown) => {
        deps.log?.(`liveness refresh failed: ${messageOf(error)}`);
      });
    }
    return mapRun(
      { files: { ...files, events: { ...files.events, ...derived.events } }, counters: derived.counters, logReadable: !derived.unreadable, verdicts },
      now(),
    );
  }

  async function findRun(id: string): Promise<{ dir: string; date: string; slug: string; info: Stats } | null> {
    const parts = id.split("/");
    if (parts.length !== 2 || !DATE_DIR.test(parts[0]) || parts[1].startsWith(".") || parts[1].startsWith("~gc-")) {
      return null;
    }
    const dir = join(resolution().root, parts[0], parts[1]);
    const dirStat = await stat(dir).catch(() => null);
    if (!dirStat?.isDirectory()) return null;
    return { dir, date: parts[0], slug: parts[1], info: dirStat };
  }

  /**
   * Bring the event log's tail up to the file's revision. Growth is read as an append — the
   * launcher appends to the log between observations — so only the new bytes are read; a
   * replacement, a shrink or a rewrite that keeps the size starts over from the bounded window, and
   * a read that fails reports no tail for this poll while the cache is kept for the next one.
   * Whenever the counting pass detects that the prefix it folded is gone — a splice, a rewrite, a
   * replacement or a lost boundary — it drops this cache, so a rewritten prefix is never extended.
   */
  async function materializeEventTail(dir: string): Promise<EventTailState | null> {
    const path = join(dir, RUN_FILES.events);
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      eventTails.delete(dir);
      return null;
    }
    const revision = revisionOf(info);
    const previous = eventTails.get(dir);
    if (previous && previous.revision === revision) {
      touch(eventTails, dir, previous);
      return previous;
    }
    const identity = identityOf(info);
    const windowStart = Math.max(0, info.size - TAIL_BYTES);
    if (previous && previous.identity === identity && previous.size < info.size && previous.size > windowStart) {
      const unfinishedInsideWindow =
        previous.pending.length === 0 || windowStart === 0 || previous.pendingStart > windowStart;
      if (unfinishedInsideWindow) {
        const added = await readRange(path, previous.size, info.size);
        if (added === null) return null;
        const lines = previous.lines.slice();
        let parseBytes = added;
        let parseStart = previous.size;
        if (previous.pendingLost) {
          // The front of the held line is out of reach, so the only thing its end can do is not be
          // mistaken for a line of its own: parsing resumes after the newline that ends it.
          const end = added.indexOf(0x0a);
          if (end === -1) {
            return cacheEventTail(dir, previous, identity, revision, info.size, lines, NO_BYTES, info.size, true);
          }
          parseBytes = added.subarray(end + 1);
          parseStart = previous.size + end + 1;
        } else if (previous.pending.length > 0) {
          parseBytes = Buffer.concat([previous.pending, added]);
          parseStart = previous.pendingStart;
        }
        const rest = parseTailLines(parseBytes, parseStart, lines);
        return cacheEventTail(dir, previous, identity, revision, info.size, lines, rest.pending, rest.pendingStart, false);
      }
    }
    const bytes = info.size === 0 ? NO_BYTES : await readRange(path, windowStart, info.size);
    if (bytes === null) {
      eventTails.delete(dir);
      return null;
    }
    const lines: TailLine[] = [];
    let parseBytes = bytes;
    let parseStart = windowStart;
    let lost = false;
    if (windowStart > 0) {
      const firstNewline = bytes.indexOf(0x0a);
      if (firstNewline === -1) {
        // The window holds no line boundary, so it is inside a line longer than the whole window.
        parseBytes = NO_BYTES;
        parseStart = info.size;
        lost = true;
      } else {
        // The window may begin inside a line; that fragment is not an event, so the tail starts at
        // the first line boundary in it.
        parseBytes = bytes.subarray(firstNewline + 1);
        parseStart = windowStart + firstNewline + 1;
      }
    }
    const rest = parseTailLines(parseBytes, parseStart, lines);
    return cacheEventTail(dir, previous, identity, revision, info.size, lines, rest.pending, rest.pendingStart, lost);
  }

  /**
   * Store a materialized event tail, pruned to what a follow window can still show: a line that
   * begins at or before the window start is unreachable by the same rule the window read used, and
   * the list is capped at the longest tail a caller may ask for.
   */
  function cacheEventTail(
    dir: string,
    previous: EventTailState | undefined,
    identity: string,
    revision: string,
    size: number,
    lines: TailLine[],
    pending: Buffer,
    pendingStart: number,
    pendingLost: boolean,
  ): EventTailState | Promise<EventTailState | null> {
    // A counter recount can invalidate the prefix while a tail read is suspended. Nothing below
    // awaits, so this identity check and publication are one synchronous step; a lost prefix rebuilds.
    if (eventTails.get(dir) !== previous) return materializeEventTail(dir);
    const windowStart = Math.max(0, size - TAIL_BYTES);
    if (windowStart > 0) {
      let dropped = 0;
      while (dropped < lines.length && lines[dropped].start <= windowStart) dropped += 1;
      if (dropped > 0) lines.splice(0, dropped);
    }
    if (lines.length > MAX_TAIL_LINES) lines.splice(0, lines.length - MAX_TAIL_LINES);
    let held = pending;
    let start = pendingStart;
    let lost = pendingLost;
    if (held.length > 0 && windowStart > 0 && start <= windowStart) {
      // The unfinished line began before the window, so it can never be shown, and its bytes are
      // only a fragment that may grow without bound. What matters is that it exists: the bytes that
      // end it must not be read as a line of their own.
      held = NO_BYTES;
      start = size;
      lost = true;
    }
    // Charge for the decoded window and parsed rows, not just the unfinished byte buffer.
    const state: EventTailState = {
      weight: 256 + 2 * Math.min(size, TAIL_BYTES) + 128 * lines.length,
      identity,
      revision,
      size,
      windowStart,
      lines,
      pending: Buffer.from(held),
      pendingStart: start,
      pendingEvent: undefined,
      pendingLost: lost,
    };
    touch(eventTails, dir, state);
    return state;
  }

  /**
   * Bring the answer file's bounded tail up to the file's revision, extending it when the file only
   * grew — the same append-between-observations assumption the event log relies on — while a
   * shrink, a same-size rewrite or a replacement reads its window again. A growing rewrite that is
   * not an append is outside that assumption, which leaves the held prefix describing bytes the
   * file no longer has until a revision that does not merely grow arrives.
   */
  async function materializeAnswerTail(dir: string): Promise<AnswerTailState | null> {
    const path = join(dir, RUN_FILES.answer);
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      answerTails.delete(dir);
      return null;
    }
    const revision = revisionOf(info);
    const previous = answerTails.get(dir);
    if (previous && previous.revision === revision) {
      touch(answerTails, dir, previous);
      return previous;
    }
    const identity = identityOf(info);
    if (previous && previous.identity === identity && previous.size < info.size && info.size - previous.size < ANSWER_TAIL_BYTES) {
      const added = await readRange(path, previous.size, info.size);
      if (added === null) return null;
      let bytes = Buffer.concat([previous.bytes, added]);
      if (bytes.length > ANSWER_TAIL_BYTES) {
        const cut = bytes.length - ANSWER_TAIL_BYTES;
        bytes = bytes.subarray(cut);
      }
      return cacheAnswerTail(dir, identity, revision, info.size, bytes);
    }
    const start = Math.max(0, info.size - ANSWER_TAIL_BYTES);
    const bytes = info.size === 0 ? NO_BYTES : await readRange(path, start, info.size);
    if (bytes === null) {
      answerTails.delete(dir);
      return null;
    }
    return cacheAnswerTail(dir, identity, revision, info.size, bytes);
  }

  function cacheAnswerTail(
    dir: string,
    identity: string,
    revision: string,
    size: number,
    bytes: Buffer,
  ): AnswerTailState {
    const state: AnswerTailState = {
      // Include a conservative allowance for the line split and decoded UTF-16 text.
      weight: 256 + 4 * bytes.length,
      identity,
      revision,
      size,
      bytes: Buffer.from(bytes),
      lines: null,
    };
    touch(answerTails, dir, state);
    return state;
  }

  /**
   * Drop cache entries for run directories a scan did not find, so a deleted run takes its caches
   * with it. An entry with a pass in flight is left alone; the next scan retires it.
   */
  function pruneCaches(live: Set<string>, unavailableDates: Set<string>): void {
    const deleted = (dir: string) => !live.has(dir) && !unavailableDates.has(dirname(dir));
    for (const [path, body] of bodies) {
      if (deleted(body.dir)) dropBody(path);
    }
    for (const [dir] of eventTails) {
      if (deleted(dir) && !eventTailPasses.has(dir)) eventTails.delete(dir);
    }
    for (const [dir] of answerTails) {
      if (deleted(dir) && !answerTailPasses.has(dir)) answerTails.delete(dir);
    }
    for (const [dir] of tailers) {
      if (deleted(dir) && !passes.has(dir)) tailers.delete(dir);
    }
    for (const dir of finalized.keys()) if (deleted(dir)) finalized.delete(dir);
  }

  /**
   * The last `limit` events a follow window would show: the complete lines of the held tail that
   * begin after the window start, plus the unfinished line when it is valid JSON already.
   */
  function tailEventsOf(state: EventTailState | null, limit: number): RunEvent[] {
    if (!state) return [];
    const { windowStart } = state;
    const visible =
      windowStart === 0 ? state.lines : state.lines.filter((line) => line.start > windowStart);
    const chosen = visible.length > limit ? visible.slice(visible.length - limit) : visible;
    const events = chosen.map((line) => line.event);
    if (state.pending.length > 0 && (windowStart === 0 || state.pendingStart > windowStart)) {
      const pending = pendingEventOf(state);
      if (pending !== null) {
        if (events.length >= limit) events.shift();
        events.push(pending);
      }
    }
    return events;
  }

  /** The same bounded suffix the window read produced: the last `lines` lines of the answer tail. */
  function answerTextOf(state: AnswerTailState, lines: number): string {
    let parts = state.lines;
    if (parts === null) {
      const split = state.bytes.toString("utf8").split(/\r?\n/);
      if (split.length > 0 && split[split.length - 1] === "") split.pop();
      parts = split;
      state.lines = split;
    }
    return parts.slice(Math.max(0, parts.length - lines)).join("\n");
  }

  function pendingEventOf(state: EventTailState): RunEvent | null {
    if (state.pendingEvent === undefined) {
      state.pendingEvent = applyEventLine(createCounters(), state.pending.toString("utf8"));
    }
    return state.pendingEvent ?? null;
  }

  async function buildFollow(id: string, tailLines: number): Promise<FollowRunOutput> {
    const started = generation;
    const found = await findRun(id);
    if (!found) {
      return { found: false, summary: null, events: [], answerTail: null };
    }
    const [files, counted] = await Promise.all([
      readFiles(found.dir, found.date, found.slug, found.info),
      countersFor(found.dir),
    ]);
    const summary = summarize(files, counted);
    // A detail read observes in-place edits immediately. Make them visible to the next list
    // scan too instead of keeping a snapshot we now know is out of date.
    const cachedSummary = finalized.get(found.dir);
    if (started === generation && cachedSummary && !isDeepStrictEqual(summary, cachedSummary.run)) {
      finalized.delete(found.dir);
    }
    // Both tails come from a revision-checked cache: a warmed poll of an unchanged run reads no log
    // bytes, and an append costs only the bytes it added. Each is materialized once per run at a
    // time, so overlapping polls share the pass and neither can extend a state the other replaces.
    const eventTail = await singleFlight(eventTailPasses, found.dir, () =>
      materializeEventTail(found.dir),
    );
    const answerTail = await singleFlight(answerTailPasses, found.dir, () =>
      materializeAnswerTail(found.dir),
    );
    trimTailCache(eventTails, eventTailPasses, EVENT_CACHE_BUDGET);
    trimTailCache(answerTails, answerTailPasses, ANSWER_CACHE_BUDGET);
    return {
      found: true,
      summary,
      lineage: files.lineage,
      events: tailEventsOf(eventTail, tailLines),
      answerTail: answerTail === null ? null : answerTextOf(answerTail, tailLines),
    };
  }

  async function scanArchive(resolved: RunRootResolution, started: number): Promise<ListRunsOutput> {
    const scanTime = now();
    const warnings: string[] = [];
    const runs: RunSummary[] = [];
    let rootExists = resolved.exists;
    let dates: string[] = [];
    if (rootExists) {
      try {
        dates = (await readdir(resolved.root, { withFileTypes: true }))
          .filter((entry) => entry.isDirectory() && DATE_DIR.test(entry.name))
          .map((entry) => entry.name)
          .sort()
          .reverse();
      } catch (error) {
        warnings.push(`${resolved.root}: ${messageOf(error)}`);
        rootExists = false;
      }
    }
    if (started === generation && !rootExists) {
      // An unavailable mount and a removed root can both look like ENOENT. A short grace
      // preserves warm state and labels the last known rows until the grace expires.
      unavailableSince ??= scanTime;
      if (scanTime - unavailableSince >= ROOT_GRACE_MS) {
        clearCaches();
      } else if (latestList?.scan.runs.length) {
        for (const run of latestList.scan.runs) runs.push(run);
        if (warnings.length === 0) warnings.push(`${resolved.root}: temporarily unavailable; showing last scan`);
      }
    }
    if (started === generation && rootExists) {
      unavailableSince = null;
      const live = new Set<string>();
      const unavailableDates = new Set<string>();
      const groups = await mapBounded(dates, async (date) => {
        const dateDir = join(resolved.root, date);
        try {
          const slugs = (await readdir(dateDir, { withFileTypes: true }))
            .filter((entry) => entry.isDirectory() && !entry.name.startsWith(".") && !entry.name.startsWith("~gc-"));
          return slugs.map(({ name: slug }) => ({ dir: join(dateDir, slug), date, slug }));
        } catch (error) {
          unavailableDates.add(dateDir);
          warnings.push(`${dateDir}: ${messageOf(error)}`);
          return [];
        }
      });
      const summaries = await mapBounded(groups.flat(), async ({ dir, date, slug }) => {
        if (started !== generation) return null;
        live.add(dir);
        try {
          const info = await stat(dir);
          if (!info.isDirectory() || started !== generation) return null;
          const directoryRevision = revisionOf(info);
          const cached = finalized.get(dir);
          if (cached?.directoryRevision === directoryRevision && scanTime - cached.checkedAt < FINALIZED_RECHECK_MS) {
            return cached.run;
          }
          const files = await readFiles(dir, date, slug, info);
          if (started !== generation) return null;
          const counted = files.finalized.present && stateCountersTakePrecedence(files)
            ? await inspectFinalizedEvents(dir)
            : await countersFor(dir);
          const run = summarize(files, counted);
          if (started === generation) {
            if (run.finalized && files.state.readable && !counted.unreadable) {
              finalized.set(dir, { run, directoryRevision, checkedAt: scanTime });
            } else {
              finalized.delete(dir);
            }
          }
          return run;
        } catch (error) {
          warnings.push(`${dir}: ${messageOf(error)}`);
          return null;
        }
      });
      for (const run of summaries) if (run !== null) runs.push(run);
      // An unreadable date is not a deletion. Its last observed rows remain until a successful
      // enumeration can establish membership (or the date disappears from the parent listing).
      if (unavailableDates.size > 0) {
        for (const run of latestList?.scan.runs ?? []) {
          if (unavailableDates.has(dirname(run.runDir))) runs.push(run);
        }
      }
      runs.sort((left, right) => sortKey(right).localeCompare(sortKey(left)));
      if (started === generation) pruneCaches(live, unavailableDates);
    }
    warnings.sort();
    return {
      runRoot: resolved.root,
      rootSource: resolved.source,
      rootExists,
      candidates: resolved.candidates,
      probe: deps.probe.kind,
      scannedAt: new Date(scanTime).toISOString(),
      runs,
      stats: summarizeRuns(runs),
      warnings,
    };
  }

  async function refreshList(): Promise<ListSnapshot> {
    const resolved = resolution();
    if (listPass) return listPass;
    const started = generation;
    const pass = scanArchive(resolved, started).then((scan) => {
      if (started !== generation) return refreshList();
      const base = latestList;
      const changes = base ? compareLists(base.scan.runs, scan.runs) : undefined;
      if (base && changes && !changes.order && changes.changes.length === 0) {
        latestList = { ...base, scan: { ...scan, runs: base.scan.runs } };
      } else {
        latestList = {
          scan,
          revision: `${storeId}:${++revision}`,
          previous: base && changes ? { revision: base.revision, changes } : undefined,
        };
      }
      return latestList;
    }).finally(() => {
      if (listPass === pass) listPass = undefined;
    });
    listPass = pass;
    return pass;
  }

  return {
    async listRuns() {
      return (await refreshList()).scan;
    },

    async listUpdate(knownRevision) {
      const { scan, revision, previous } = await refreshList();
      const delta = knownRevision === revision
        ? { changes: [], removed: [] }
        : previous && previous.revision === knownRevision ? previous.changes : undefined;
      if (!delta) return { ...scan, revision };
      const { runs: _runs, ...facts } = scan;
      return { ...facts, revision, ...delta };
    },

    async paths(id: string): Promise<RunPathsOutput> {
      const scannedAt = new Date(now()).toISOString();
      const found = await findRun(id);
      if (!found) return { found: false, paths: [], scannedAt };
      const paths = await Promise.all(
        Object.values(RUN_FILES).map(async (name) => {
          const path = join(found.dir, name);
          const { exists, bytes } = await fileBytes(path);
          return { label: name, path, exists, bytes };
        }),
      );
      return { found: true, paths, scannedAt };
    },

    async follow(id: string, tailLines?: number): Promise<FollowRunOutput> {
      return buildFollow(id, clampTail(tailLines ?? deps.config().tailLines));
    },

    dispose(): void {
      reset();
      rootKey = null;
    },
  };
}

async function mapBounded<T, U>(values: readonly T[], map: (value: T) => Promise<U>): Promise<U[]> {
  const results: U[] = new Array(values.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(SCAN_CONCURRENCY, values.length) }, async () => {
    while (next < values.length) {
      const index = next++;
      results[index] = await map(values[index]);
    }
  }));
  return results;
}

function compareLists(before: RunSummary[], after: RunSummary[]): ListChanges {
  const byId = new Map(before.map((run) => [run.id, run]));
  const changes: RunSummary[] = [];
  let orderChanged = before.length !== after.length;
  for (let i = 0; i < after.length; i++) {
    const run = after[i];
    const old = byId.get(run.id);
    orderChanged ||= before[i]?.id !== run.id;
    byId.delete(run.id);
    if (old === run) continue;
    if (old && isDeepStrictEqual(old, run)) after[i] = old;
    else changes.push(run);
  }
  return {
    changes,
    removed: [...byId.keys()],
    ...(orderChanged ? { order: after.map(({ id }) => id) } : {}),
  };
}

async function endsWithNewline(path: string, offset: number): Promise<boolean> {
  try {
    const handle = await open(path, "r");
    try {
      const buffer = Buffer.allocUnsafe(1);
      const { bytesRead } = await handle.read(buffer, 0, 1, offset - 1);
      return bytesRead === 1 && buffer[0] === 0x0a;
    } finally {
      await handle.close();
    }
  } catch {
    return false;
  }
}

/**
 * Parse the newline-terminated segments of `bytes`, which begin at absolute offset `start`, and
 * append the events they carry together with the byte each line began at. The bytes after the last
 * newline come back unparsed: they may still become a line, and a later append continues them.
 */
function parseTailLines(
  bytes: Buffer,
  start: number,
  into: TailLine[],
): { pending: Buffer; pendingStart: number } {
  let cursor = start;
  let rest = bytes;
  // One scratch fold serves the whole batch: an event handed back describes its own line only, and
  // this parser never reads the fold's bookkeeping, so a counters object per line is not needed.
  const scratch = createCounters();
  for (;;) {
    const newline = rest.indexOf(0x0a);
    if (newline === -1) break;
    const event = applyEventLine(scratch, rest.subarray(0, newline).toString("utf8"));
    if (event) into.push({ event, start: cursor });
    // Unmatched tool starts are the only part of the scratch that grows with the batch.
    if (scratch.open.size > SCRATCH_OPEN_TOOLS) scratch.open.clear();
    cursor += newline + 1;
    rest = rest.subarray(newline + 1);
  }
  return { pending: rest, pendingStart: cursor };
}

/** Identity of a file: a replaced file is a different file, whatever its size or times say. */
function identityOf(info: Stats): string {
  return `${info.ino}:${info.birthtimeMs}`;
}

/**
 * Revision of a file's content: its identity, size, and modification and change times. Reuse is
 * allowed only when all of them match, so a log that was appended to, rewritten in place, replaced
 * or shrunk is read again. These are the signals a filesystem offers, not a proof of content
 * equality: where timestamps are coarse (some removable and network filesystems), a same-size
 * rewrite inside one timestamp tick can pass as unchanged, and that revision's cached bytes stand.
 */
function revisionOf(info: Stats): string {
  return `${identityOf(info)}:${info.size}:${info.mtimeMs}:${info.ctimeMs}`;
}

function touch<K, V>(cache: Map<K, V>, key: K, value: V): void {
  cache.delete(key);
  cache.set(key, value);
}

function trimTailCache<T extends { weight: number }>(
  cache: Map<string, T>, inflight: ReadonlyMap<string, unknown>, budget: number,
): void {
  let weight = 0;
  for (const value of cache.values()) weight += value.weight;
  for (const key of cache.keys()) {
    if (weight <= budget) break;
    if (inflight.has(key)) continue;
    weight -= cache.get(key)!.weight;
    cache.delete(key);
  }
}

/** Run one pass per key at a time: an overlapping caller awaits the pass already in flight. */
function singleFlight<T>(
  inflight: Map<string, Promise<T>>,
  key: string,
  start: () => Promise<T>,
): Promise<T> {
  const running = inflight.get(key);
  if (running) return running;
  const pass = start().finally(() => {
    if (inflight.get(key) === pass) inflight.delete(key);
  });
  inflight.set(key, pass);
  return pass;
}

function clampTail(lines: number): number {
  return Math.min(Math.max(Math.trunc(lines), 1), MAX_TAIL_LINES);
}

function sortKey(run: RunSummary): string {
  return run.endedAt ?? run.startedAt ?? run.dirModifiedAt ?? run.id;
}

function parseExitCode(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseInt(value.trim(), 10);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
