import type { Stats } from "node:fs";
import { open, readdir, stat, type FileHandle } from "node:fs/promises";
import { dirname, join } from "node:path";
import type {
  EventStats,
  FollowRunOutput,
  ListRunsOutput,
  RunEvent,
  RunPathsOutput,
  RunSummary,
} from "../shared/runs";
import { MAX_TAIL_LINES } from "../shared/runs";
import {
  applyEventLine,
  asRecord,
  createCounters,
  snapshotCounters,
} from "./events";
import type { CounterSnapshot, RunCounters } from "./events";
import type { LivenessProbe, PidVerdict } from "./liveness";
import { resolveRunRoot, type RunRootResolution } from "./run-root";
import { summarizeRuns } from "./stats";
import {
  mapRun,
  pidsOf,
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
  stats: "events.stats.json",
  answer: "answer.md",
  lock: "lock",
  finalized: "finalized",
  prompt: "prompt.md",
  runnerOut: "runner.out",
  stderr: "stderr.log",
} as const;
const SESSION_FILE = "session.id";

const DATE_DIR = /^\d{4}-\d{2}-\d{2}$/;
const TAIL_BYTES = 256 * 1024;
const ANSWER_TAIL_BYTES = 64 * 1024;
const COUNTER_CHUNK = 256 * 1024;
const JSON_READ_BYTES = 1024 * 1024;
const SESSION_READ_BYTES = 4096;
/** A body past this size is re-read each pass rather than held; the run files that matter are small. */
const BODY_CACHE_BYTES = 16 * 1024;
const BODY_CACHE_ENTRIES = 2048;
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
  bytes: Buffer;
  text: string | null;
};

/** One parsed event and the byte its line began at, which is how a window boundary is applied. */
type TailLine = { event: RunEvent; start: number };

/**
 * The event log's bounded tail, kept so an append costs only the bytes it added: `lines` holds the
 * events of terminated lines, `pending` the trailing bytes that are not a line yet, and a new event
 * is parsed when its last byte arrives rather than the whole window being read again.
 */
type EventTailState = {
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
  identity: string;
  revision: string;
  size: number;
  bytes: Buffer;
  lines: string[] | null;
};

type Counted = { counters: CounterSnapshot | null; unreadable: boolean };

/** One run's outcome inside the scan: its summary, or the failure that kept it out. */
type ScannedRun = { run: RunSummary | null; failure: string | null };

type FileText =
  | { kind: "missing" }
  | { kind: "unreadable" }
  | { kind: "text"; text: string };

export function createRunStore(deps: StoreDeps): RunStore {
  const env = deps.env ?? process.env;
  const now = deps.now ?? (() => Date.now());
  const tailers = new Map<string, Tailer>();
  const passes = new Map<string, Promise<Counted>>();
  const bodies = new Map<string, BodyEntry>();
  const eventTails = new Map<string, EventTailState>();
  const eventTailPasses = new Map<string, Promise<EventTailState | null>>();
  const answerTails = new Map<string, AnswerTailState>();
  const answerTailPasses = new Map<string, Promise<AnswerTailState | null>>();
  let rootKey: string | null = null;

  /**
   * Every cache is keyed under the resolved root, so a root change or a dispose retires all of them
   * at once. A pass already in flight keeps working on the objects it started with; the next scan
   * drops whatever it stored for a directory that is no longer there.
   */
  function clearCaches(): void {
    tailers.clear();
    passes.clear();
    bodies.clear();
    eventTails.clear();
    eventTailPasses.clear();
    answerTails.clear();
    answerTailPasses.clear();
  }

  function resolution(): RunRootResolution {
    const { runRoot } = deps.config();
    const next = resolveRunRoot(runRoot, env);
    const nextKey = `${next.root}|${next.source}`;
    if (nextKey !== rootKey) {
      if (rootKey !== null) {
        deps.log?.(`run root changed to ${next.root} (${next.source}); clearing caches`);
        clearCaches();
      }
      rootKey = nextKey;
    }
    return next;
  }

  function countersFor(dir: string): Promise<Counted> {
    // One pass per run at a time: an overlapping scan joins it rather than folding the same bytes twice.
    return singleFlight(passes, dir, () => countAppended(dir));
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
      };
    }
    const revision = revisionOf(info);
    if (current.revision === revision && current.offset === info.size) {
      // This revision is already folded to its last byte, so there is nothing to read and no
      // line-boundary probe to make: size and timestamps still say this is the log that was
      // counted, down to the resolution those timestamps have.
      return {
        counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
        unreadable: false,
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
    const cached = bodies.get(path);
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      bodies.delete(path);
      return { kind: "missing" };
    }
    const revision = revisionOf(info);
    if (cached && cached.revision === revision && cached.want === want) {
      return { kind: "text", text: textOf(cached) };
    }
    const start = Math.max(0, info.size - want);
    const bytes = info.size === 0 ? NO_BYTES : await readRange(path, start, info.size);
    if (bytes === null) {
      bodies.delete(path);
      return { kind: "unreadable" };
    }
    const entry: BodyEntry = { dir: dirname(path), revision, want, bytes, text: null };
    if (bytes.length <= BODY_CACHE_BYTES) {
      bodies.delete(path);
      bodies.set(path, entry);
      while (bodies.size > BODY_CACHE_ENTRIES) {
        const oldest = bodies.keys().next();
        if (oldest.done) break;
        bodies.delete(oldest.value);
      }
    } else {
      // Too large to hold: drop whatever an older revision left behind, which no longer describes a
      // file that exists.
      bodies.delete(path);
    }
    return { kind: "text", text: textOf(entry) };
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

  async function fileBytes(path: string): Promise<{ exists: boolean; bytes: number | null }> {
    try {
      return { exists: true, bytes: (await stat(path)).size };
    } catch {
      return { exists: false, bytes: null };
    }
  }

  async function readFiles(dir: string, date: string, slug: string): Promise<RunFiles> {
    // The eight reads are independent, so they run as one wave instead of one await after another.
    const [state, lockJson, finalizedText, statsJson, answerFile, eventsFile, sessionIdRead, dirStat] =
      await Promise.all([
        readJson(join(dir, RUN_FILES.state)),
        readJson(join(dir, RUN_FILES.lock)),
        readJson(join(dir, RUN_FILES.finalized)),
        readJson(join(dir, RUN_FILES.stats)),
        fileBytes(join(dir, RUN_FILES.answer)),
        fileBytes(join(dir, RUN_FILES.events)),
        readBody(join(dir, SESSION_FILE), SESSION_READ_BYTES),
        stat(dir).catch(() => null),
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
    const events: RunEventLog = { exists: eventsFile.exists, bytes: eventsFile.bytes ?? 0 };
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
      events,
      sessionIdFromFile: sessionId ? sessionId.split(/\r?\n/)[0] : null,
      dirModifiedAt: dirStat ? dirStat.mtime.toISOString() : null,
    };
  }

  async function summarize(files: RunFiles): Promise<RunSummary> {
    const derived = await countersFor(files.dir);
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
      { files, counters: derived.counters, logReadable: !derived.unreadable, verdicts },
      now(),
    );
  }

  async function findRun(id: string): Promise<{ dir: string; date: string; slug: string } | null> {
    const parts = id.split("/");
    if (parts.length !== 2 || !DATE_DIR.test(parts[0])) return null;
    const dir = join(resolution().root, parts[0], parts[1]);
    const dirStat = await stat(dir).catch(() => null);
    if (!dirStat?.isDirectory()) return null;
    return { dir, date: parts[0], slug: parts[1] };
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
    if (previous && previous.revision === revision) return previous;
    const identity = identityOf(info);
    const windowStart = Math.max(0, info.size - TAIL_BYTES);
    if (previous && previous.identity === identity && previous.size < info.size) {
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
    const state: EventTailState = {
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
    eventTails.set(dir, state);
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
    if (previous && previous.revision === revision) return previous;
    const identity = identityOf(info);
    if (previous && previous.identity === identity && previous.size < info.size) {
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
      identity,
      revision,
      size,
      bytes: Buffer.from(bytes),
      lines: null,
    };
    answerTails.set(dir, state);
    return state;
  }

  /**
   * Drop cache entries for run directories a scan did not find, so a deleted run takes its caches
   * with it. An entry with a pass in flight is left alone; the next scan retires it.
   */
  function pruneCaches(live: Set<string>): void {
    for (const [path, body] of bodies) {
      if (!live.has(body.dir)) bodies.delete(path);
    }
    for (const [dir] of eventTails) {
      if (!live.has(dir) && !eventTailPasses.has(dir)) eventTails.delete(dir);
    }
    for (const [dir] of answerTails) {
      if (!live.has(dir) && !answerTailPasses.has(dir)) answerTails.delete(dir);
    }
    for (const [dir] of tailers) {
      if (!live.has(dir) && !passes.has(dir)) tailers.delete(dir);
    }
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
    const found = await findRun(id);
    if (!found) {
      return { found: false, summary: null, events: [], answerTail: null };
    }
    const files = await readFiles(found.dir, found.date, found.slug);
    const summary = await summarize(files);
    // Both tails come from a revision-checked cache: a warmed poll of an unchanged run reads no log
    // bytes, and an append costs only the bytes it added. Each is materialized once per run at a
    // time, so overlapping polls share the pass and neither can extend a state the other replaces.
    const eventTail = await singleFlight(eventTailPasses, found.dir, () =>
      materializeEventTail(found.dir),
    );
    const answerTail = await singleFlight(answerTailPasses, found.dir, () =>
      materializeAnswerTail(found.dir),
    );
    return {
      found: true,
      summary,
      events: tailEventsOf(eventTail, tailLines),
      answerTail: answerTail === null ? null : answerTextOf(answerTail, tailLines),
    };
  }

  return {
    async listRuns(): Promise<ListRunsOutput> {
      const resolved = resolution();
      const scannedAt = new Date(now()).toISOString();
      const warnings: string[] = [];
      const runs: RunSummary[] = [];
      // The directories this scan found, which is everything a cache entry may still describe.
      const live = new Set<string>();
      if (!resolved.exists) {
        pruneCaches(live);
        return {
          runRoot: resolved.root,
          rootSource: resolved.source,
          rootExists: false,
          candidates: resolved.candidates,
          probe: deps.probe.kind,
          scannedAt,
          runs,
          stats: summarizeRuns(runs),
          warnings,
        };
      }
      const dates = (await readdir(resolved.root, { withFileTypes: true }))
        .filter((entry) => entry.isDirectory() && DATE_DIR.test(entry.name))
        .map((entry) => entry.name)
        .sort()
        .reverse();
      // Every run's reads are independent, so the scan is one wave of work whose wall time is the
      // slowest run rather than the sum of all of them. `Promise.all` keeps the results in input
      // order, and `runs.sort` below stays the only ordering authority.
      const scanned = await Promise.all(
        dates.map(async (date) => {
          const dateDir = join(resolved.root, date);
          let slugs: string[];
          try {
            slugs = (await readdir(dateDir, { withFileTypes: true }))
              .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
              .map((entry) => entry.name);
          } catch (error) {
            return { summaries: [], failure: `${dateDir}: ${messageOf(error)}` };
          }
          const summaries = await Promise.all(
            slugs.map(async (slug): Promise<ScannedRun> => {
              const dir = join(dateDir, slug);
              live.add(dir);
              try {
                return { run: await summarize(await readFiles(dir, date, slug)), failure: null };
              } catch (error) {
                return { run: null, failure: `${dir}: ${messageOf(error)}` };
              }
            }),
          );
          return { summaries, failure: null };
        }),
      );
      for (const scan of scanned) {
        if (scan.failure !== null) warnings.push(scan.failure);
        for (const entry of scan.summaries) {
          if (entry.failure !== null) warnings.push(entry.failure);
          else if (entry.run !== null) runs.push(entry.run);
        }
      }
      runs.sort((left, right) => sortKey(right).localeCompare(sortKey(left)));
      pruneCaches(live);
      return {
        runRoot: resolved.root,
        rootSource: resolved.source,
        rootExists: true,
        candidates: resolved.candidates,
        probe: deps.probe.kind,
        scannedAt,
        runs,
        stats: summarizeRuns(runs),
        warnings,
      };
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
      clearCaches();
      rootKey = null;
    },
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

function textOf(entry: BodyEntry): string {
  if (entry.text === null) entry.text = entry.bytes.toString("utf8");
  return entry.text;
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
