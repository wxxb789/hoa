import { randomUUID } from "node:crypto";
import type { Stats } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { isDeepStrictEqual } from "node:util";
import type {
  FollowRunOutput,
  ListRunsDelta,
  ListRunsOutput,
  ListRunsUpdate,
  RunPathsOutput,
  RunSummary,
} from "../shared/runs";
import { MAX_TAIL_LINES } from "../shared/runs";
import { summarizeRuns } from "../shared/stats";
import type { LivenessProbe, PidVerdict } from "./liveness";
import { createRunFileReader, messageOf, revisionOf, type Counted } from "./run-store-reader";
import { resolveRunRoot, type RunRootResolution } from "./run-root";
import { mapRun, pidsOf, stateCountersTakePrecedence, type RunFiles } from "./state";

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

const DATE_DIR = /^\d{4}-\d{2}-\d{2}$/;
const SCAN_CONCURRENCY = 12;
const FINALIZED_RECHECK_MS = 30_000;
const ROOT_GRACE_MS = 30_000;

type FinalizedEntry = { run: RunSummary; directoryRevision: string; checkedAt: number };
type ListChanges = Pick<ListRunsDelta, "changes" | "removed" | "order">;
type ListSnapshot = {
  scan: ListRunsOutput;
  revision: string;
  previous?: { revision: string; changes: ListChanges };
};

export function createRunStore(deps: StoreDeps): RunStore {
  const env = deps.env ?? process.env;
  const now = deps.now ?? (() => Date.now());
  const finalized = new Map<string, FinalizedEntry>();
  let rootKey: string | null = null;
  let generation = 0;
  const reader = createRunFileReader(deps.log?.bind(deps), () => generation);
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
    reader.clear();
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

  async function buildFollow(id: string, tailLines: number): Promise<FollowRunOutput> {
    const started = generation;
    const found = await findRun(id);
    if (!found) {
      return { found: false, summary: null, events: [], answerTail: null };
    }
    const [files, counted] = await Promise.all([
      reader.readFiles(found.dir, found.date, found.slug, found.info),
      reader.countersFor(found.dir),
    ]);
    const summary = summarize(files, counted);
    // A detail read observes in-place edits immediately. Make them visible to the next list
    // scan too instead of keeping a snapshot we now know is out of date.
    const cachedSummary = finalized.get(found.dir);
    if (started === generation && cachedSummary && !isDeepStrictEqual(summary, cachedSummary.run)) {
      finalized.delete(found.dir);
    }
    return {
      found: true,
      summary,
      lineage: files.lineage,
      ...await reader.readTails(found.dir, tailLines),
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
          const files = await reader.readFiles(dir, date, slug, info);
          if (started !== generation) return null;
          const counted = await reader.countersFor(dir, files.finalized.present && stateCountersTakePrecedence(files));
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
      if (started === generation) {
        const deleted = (dir: string) => !live.has(dir) && !unavailableDates.has(dirname(dir));
        reader.prune(deleted);
        for (const dir of finalized.keys()) if (deleted(dir)) finalized.delete(dir);
      }
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
      return { found: true, paths: await reader.readPaths(found.dir), scannedAt };
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

function clampTail(lines: number): number {
  return Math.min(Math.max(Math.trunc(lines), 1), MAX_TAIL_LINES);
}

function sortKey(run: RunSummary): string {
  return run.endedAt ?? run.startedAt ?? run.dirModifiedAt ?? run.id;
}
