import type { Stats } from "node:fs";
import { open, readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import type {
  EventStats,
  FollowRunOutput,
  ListRunsOutput,
  RunDetailOutput,
  RunSummary,
} from "../shared/runs";
import { applyEventLine, createCounters, parseEventWindow, snapshotCounters } from "./events";
import type { CounterSnapshot, RunCounters } from "./events";
import type { LivenessProbe, PidVerdict } from "./liveness";
import { resolveRunRoot, type RunRootResolution } from "./run-root";
import {
  mapRun,
  type RunAnswer,
  type RunEventLog,
  type RunFiles,
  type RunFinalized,
  type RunLock,
  type RunStateFile,
} from "./state";

export type StoreConfig = { runRoot: string; pollIntervalMs: number; tailLines: number };

export type StoreDeps = {
  probe: LivenessProbe;
  config(): StoreConfig;
  env?: NodeJS.ProcessEnv;
  now?(): number;
  log?(message: string): void;
};

export type RunStore = {
  listRuns(): Promise<ListRunsOutput>;
  runDetail(id: string, tailLines?: number): Promise<RunDetailOutput>;
  follow(id: string, tailLines?: number): Promise<FollowRunOutput>;
  dispose(): void;
};

/** Files the launcher writes into a run directory. */
const RUN_FILES = [
  { label: "state.json", file: "state.json" },
  { label: "events.ndjson", file: "events.ndjson" },
  { label: "events.stats.json", file: "events.stats.json" },
  { label: "answer.md", file: "answer.md" },
  { label: "lock", file: "lock" },
  { label: "finalized", file: "finalized" },
  { label: "prompt.md", file: "prompt.md" },
  { label: "runner.out", file: "runner.out" },
  { label: "stderr.log", file: "stderr.log" },
] as const;

const DATE_DIR = /^\d{4}-\d{2}-\d{2}$/;
const TAIL_BYTES = 256 * 1024;
const ANSWER_TAIL_BYTES = 64 * 1024;
const COUNTER_CHUNK = 256 * 1024;

type Tailer = {
  offset: number;
  pending: Buffer;
  counters: RunCounters;
  resets: number;
  unreadable: boolean;
  fileId: string;
  updating: Promise<{ counters: CounterSnapshot | null; unreadable: boolean }> | null;
};

export function createRunStore(deps: StoreDeps): RunStore {
  const env = deps.env ?? process.env;
  const now = deps.now ?? (() => Date.now());
  const tailers = new Map<string, Tailer>();
  let rootCache: RunRootResolution | null = null;
  let rootKey = "";

  function resolution(): RunRootResolution {
    const { runRoot } = deps.config();
    const next = resolveRunRoot(runRoot, env);
    const nextKey = `${next.root}|${next.source}`;
    if (rootCache === null || nextKey !== rootKey) {
      if (rootCache !== null) {
        deps.log?.(`run root changed to ${next.root} (${next.source}); clearing caches`);
        tailers.clear();
      }
      rootCache = next;
      rootKey = nextKey;
    }
    return next;
  }

  /**
   * Counters are derived by tailing `events.ndjson` from the last byte we read, so a
   * scan costs only the appended window. The launcher splices the log at its bound by replacing it
   * with `head + truncated marker + tail`, so any of three cheap signals restarts the count from
   * byte 0 (a replaced file, a shrunken file, or a lost line boundary) and the numbers stay a
   * description of the retained log rather than a mix of two revisions.
   */
  async function countersFor(
    dir: string,
  ): Promise<{ counters: CounterSnapshot | null; unreadable: boolean }> {
    let tailer = tailers.get(dir);
    if (!tailer) {
      tailer = {
        offset: 0,
        pending: Buffer.alloc(0),
        counters: createCounters(),
        resets: 0,
        unreadable: false,
        fileId: "",
        updating: null,
      };
      tailers.set(dir, tailer);
    }
    if (tailer.updating) return tailer.updating;
    const current = tailer;
    current.updating = updateCounters(dir, current).finally(() => {
      current.updating = null;
    });
    return current.updating;
  }

  async function updateCounters(
    dir: string,
    current: Tailer,
  ): Promise<{ counters: CounterSnapshot | null; unreadable: boolean }> {
    const path = join(dir, "events.ndjson");
    let info: Stats;
    try {
      info = await stat(path);
    } catch {
      // No log yet (a run that just started) is normal, not a read failure.
      return {
        counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
        unreadable: false,
      };
    }
    const fileId = `${info.ino}:${info.birthtimeMs}`;
    const replaced = current.fileId !== "" && current.fileId !== fileId;

    // Two passes at most: a rewritten log restarts the count from byte 0, then a recount settles.
    for (let pass = 0; pass < 2; pass += 1) {
      const completeOffset = current.offset - current.pending.length;
      const shifted =
        replaced ||
        info.size < current.offset ||
        (completeOffset > 0 && !(await endsWithNewline(path, completeOffset)));
      current.fileId = fileId;
      const restart = shifted || (await readAppended(path, current, info.size)) === "spliced";
      if (!restart) break;
      current.offset = 0;
      current.pending = Buffer.alloc(0);
      current.counters = createCounters();
      current.resets += 1;
      current.unreadable = false;
    }
    return {
      counters: current.counters.lines > 0 ? snapshotCounters(current.counters) : null,
      unreadable: current.unreadable,
    };
  }

  /**
   * Fold the appended window into the tailer's counters. `offset` advances past every byte read;
   * `pending` retains an incomplete suffix exactly once until a later read completes the line.
   * Returns `"spliced"` when a `truncated` marker appeared after bytes already counted.
   */
  async function readAppended(
    path: string,
    tailer: Tailer,
    size: number,
  ): Promise<"appended" | "spliced"> {
    if (size <= tailer.offset) return "appended";
    const startOffset = tailer.offset;
    let spliced = false;
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
          offset += bytesRead;
          const combined =
            tailer.pending.length > 0 ? Buffer.concat([tailer.pending, chunk]) : chunk;
          const lastNewline = combined.lastIndexOf(0x0a);
          if (lastNewline === -1) {
            tailer.pending = Buffer.from(combined);
            continue;
          }
          const complete = combined.subarray(0, lastNewline).toString("utf8");
          tailer.pending = Buffer.from(combined.subarray(lastNewline + 1));
          for (const line of complete.split("\n")) {
            const event = applyEventLine(tailer.counters, line);
            if (event?.type === "truncated" && startOffset > 0) spliced = true;
          }
        }
        tailer.offset = offset;
      } finally {
        await handle.close();
      }
    } catch (error) {
      deps.log?.(`event log unreadable at ${path}: ${messageOf(error)}`);
      tailer.unreadable = true;
      return "appended";
    }
    return spliced ? "spliced" : "appended";
  }

  /** Read the last `bytes` of a file as text, without ever loading the whole file. */
  async function readTailText(path: string, bytes: number, dropFragment = false): Promise<string | null> {
    let size: number;
    try {
      size = (await stat(path)).size;
    } catch {
      return null;
    }
    if (size === 0) return "";
    const start = Math.max(0, size - bytes);
    const length = size - start;
    const handle = await open(path, "r");
    try {
      const buffer = Buffer.allocUnsafe(length);
      const { bytesRead } = await handle.read(buffer, 0, length, start);
      const text = buffer.subarray(0, bytesRead).toString("utf8");
      return dropFragment ? dropLeadingFragment(text, start) : text;
    } finally {
      await handle.close();
    }
  }

  async function readJson(path: string): Promise<{ present: boolean; readable: boolean; value: unknown }> {
    const text = await readTailText(path, 1024 * 1024);
    if (text === null) return { present: false, readable: false, value: null };
    try {
      return { present: true, readable: true, value: JSON.parse(text) };
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
    const state = await readJson(join(dir, "state.json"));
    const values =
      typeof state.value === "object" && state.value !== null && !Array.isArray(state.value)
        ? (state.value as Record<string, unknown>)
        : {};
    const stateFile: RunStateFile = { present: state.present, readable: state.readable, values };

    const lockJson = await readJson(join(dir, "lock"));
    const lockValue =
      typeof lockJson.value === "object" && lockJson.value !== null
        ? (lockJson.value as Record<string, unknown>)
        : null;
    const lock: RunLock | null = lockValue
      ? {
          pid: numberOrNull(lockValue.pid),
          agentPid: numberOrNull(lockValue.agent_pid),
          backend: typeof lockValue.backend === "string" ? lockValue.backend : null,
          startedAt: typeof lockValue.started_at === "string" ? lockValue.started_at : null,
        }
      : null;

    const finalizedText = await readJson(join(dir, "finalized"));
    const finalized: RunFinalized = finalizedText.present
      ? { present: true, exitCode: parseExitCode(finalizedText.value) }
      : { present: false, exitCode: null };

    const statsJson = await readJson(join(dir, "events.stats.json"));
    const statsValue =
      typeof statsJson.value === "object" && statsJson.value !== null
        ? (statsJson.value as Record<string, unknown>)
        : null;
    const stats: EventStats = statsValue
      ? {
          totalBytes: numberOrNull(statsValue.total_bytes),
          retainedBytes: numberOrNull(statsValue.retained_bytes),
          droppedBytes: numberOrNull(statsValue.dropped_bytes),
          truncated: typeof statsValue.truncated === "boolean" ? statsValue.truncated : null,
        }
      : null;

    const answerFile = await fileBytes(join(dir, "answer.md"));
    const answer: RunAnswer = { exists: answerFile.exists, bytes: answerFile.bytes };
    const eventsFile = await fileBytes(join(dir, "events.ndjson"));
    const events: RunEventLog = {
      exists: eventsFile.exists,
      bytes: eventsFile.bytes ?? 0,
      readable: true,
    };
    const sessionIdText = await readTailText(join(dir, "session.id"), 4096);
    const dirStat = await stat(dir).catch(() => null);

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
      sessionIdFromFile: sessionIdText?.trim() ? sessionIdText.trim().split(/\r?\n/)[0] : null,
      dirModifiedAt: dirStat ? dirStat.mtime.toISOString() : null,
    };
  }

  async function summarize(files: RunFiles): Promise<RunSummary> {
    const derived = await countersFor(files.dir);
    files.events.readable = !derived.unreadable;
    const pids = [
      numberOrNull(files.state.values.pid),
      numberOrNull(files.state.values.agent_pid),
      files.lock?.pid ?? null,
      files.lock?.agentPid ?? null,
    ].filter((pid): pid is number => pid !== null && pid > 0);
    const needsLiveness = !files.finalized.present && pids.length > 0;
    const verdicts: Map<number, PidVerdict> = needsLiveness
      ? deps.probe.verdicts(pids)
      : new Map();
    if (needsLiveness) {
      // Confirmation of an unproven pid continues off the scan path; the next scan sees it.
      void deps.probe.refresh(pids).catch((error: unknown) => {
        deps.log?.(`liveness refresh failed: ${messageOf(error)}`);
      });
    }
    return mapRun({ files, counters: derived.counters, verdicts }, now());
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
   * One bounded read of a run: metadata folded from `stat`/`state.json`, the last `tailLines`
   * events from a fixed window at the end of the log, and the answer tail. `includePaths` adds the
   * per-file listing used by the detail view.
   */
  async function buildDetail(
    id: string,
    tailLines: number,
    includePaths: boolean,
  ): Promise<RunDetailOutput> {
    const scannedAt = new Date(now()).toISOString();
    const found = await findRun(id);
    if (!found) {
      return { found: false, summary: null, events: [], answerTail: null, stats: null, paths: [], scannedAt };
    }
    const files = await readFiles(found.dir, found.date, found.slug);
    const summary = await summarize(files);
    const eventsText = await readTailText(join(found.dir, "events.ndjson"), TAIL_BYTES, true);
    const answerTail = await readTailText(join(found.dir, "answer.md"), ANSWER_TAIL_BYTES);
    const paths = includePaths
      ? await Promise.all(
          RUN_FILES.map(async (entry) => {
            const path = join(found.dir, entry.file);
            const { exists, bytes } = await fileBytes(path);
            return { label: entry.label, path, exists, bytes };
          }),
        )
      : [];
    return {
      found: true,
      summary,
      events: parseEventWindow(eventsText ?? "", tailLines),
      answerTail: answerTail === null ? null : tailText(answerTail, tailLines),
      stats: files.stats,
      paths,
      scannedAt,
    };
  }

  return {
    async listRuns(): Promise<ListRunsOutput> {
      const resolved = resolution();
      const scannedAt = new Date(now()).toISOString();
      const warnings: string[] = [];
      const runs: RunSummary[] = [];
      if (!resolved.exists) {
        return {
          runRoot: resolved.root,
          rootSource: resolved.source,
          rootExists: false,
          candidates: resolved.candidates,
          probe: deps.probe.kind,
          scannedAt,
          runs,
          warnings,
        };
      }
      const dates = (await readdir(resolved.root, { withFileTypes: true }))
        .filter((entry) => entry.isDirectory() && DATE_DIR.test(entry.name))
        .map((entry) => entry.name)
        .sort()
        .reverse();
      for (const date of dates) {
        const dateDir = join(resolved.root, date);
        let slugs: string[];
        try {
          slugs = (await readdir(dateDir, { withFileTypes: true }))
            .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
            .map((entry) => entry.name);
        } catch (error) {
          warnings.push(`${dateDir}: ${messageOf(error)}`);
          continue;
        }
        for (const slug of slugs) {
          try {
            const files = await readFiles(join(dateDir, slug), date, slug);
            runs.push(await summarize(files));
          } catch (error) {
            warnings.push(`${join(dateDir, slug)}: ${messageOf(error)}`);
          }
        }
      }
      runs.sort((left, right) => sortKey(right).localeCompare(sortKey(left)));
      return {
        runRoot: resolved.root,
        rootSource: resolved.source,
        rootExists: true,
        candidates: resolved.candidates,
        probe: deps.probe.kind,
        scannedAt,
        runs,
        warnings,
      };
    },

    runDetail(id: string, tailLines?: number): Promise<RunDetailOutput> {
      return buildDetail(id, clampTail(tailLines ?? deps.config().tailLines), true);
    },

    async follow(id: string, tailLines?: number): Promise<FollowRunOutput> {
      const result = await buildDetail(id, clampTail(tailLines ?? deps.config().tailLines), false);
      return {
        found: result.found,
        summary: result.summary,
        events: result.events,
        answerTail: result.answerTail,
        scannedAt: result.scannedAt,
      };
    },

    dispose(): void {
      tailers.clear();
      rootCache = null;
      rootKey = "";
    },
  };
}

function dropLeadingFragment(text: string, startOffset: number): string {
  if (startOffset === 0) return text;
  const index = text.indexOf("\n");
  return index === -1 ? "" : text.slice(index + 1);
}

/** True when the byte before `offset` is a newline, i.e. the log was not rewritten underneath us. */
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

function tailText(text: string, lines: number): string {
  const split = text.split(/\r?\n/);
  if (split.length > 0 && split[split.length - 1] === "") split.pop();
  return split.slice(-lines).join("\n");
}

function clampTail(lines: number): number {
  return Math.min(Math.max(Math.trunc(lines), 1), 2000);
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
