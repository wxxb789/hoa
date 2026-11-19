import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { LIVENESS_PROBES } from "../shared/runs";

const run = promisify(execFile);

export type PidVerdict = "alive" | "dead" | "unknown";
export type ProbeKind = (typeof LIVENESS_PROBES)[number];

export type LivenessProbe = {
  kind: ProbeKind;
  /**
   * Verdicts for this scan without blocking: an inline process check answers what it can, and
   * unproven pids keep their last confirmed verdict (`unknown` until one exists). An inconclusive
   * check also schedules confirmation against the OS listing off this call, so a verdict confirmed
   * earlier is revisited after that process exits.
   */
  verdicts(pids: number[]): Map<number, PidVerdict>;
  /**
   * Confirm pids the inline check could not decide against the OS listing. The caller passes only
   * those, so the probe never repeats a `process.kill` the caller just made. Resolves when the
   * listing settles; callers that arrive while one is in flight share it.
   */
  refresh(pids: number[]): Promise<void>;
};

const TASKLIST_TIMEOUT_MS = 8000;
/** Reuse of a settled listing attempt, measured from its completion; failures back off the same. */
const TASKLIST_REUSE_MS = 30_000;
/**
 * Cap on the per-pid evidence a Windows probe retains. Past it the least recently scanned pid is
 * evicted: an evicted pid reads `unknown` and is re-observed on its next scan, so retention can
 * neither grow without bound nor turn forgotten evidence into a verdict.
 */
export const MAX_TRACKED_PIDS = 4096;

/** A fresh signal check: `alive` on proof of existence, `gone` only where `ESRCH` is authoritative. */
type SignalVerdict = "alive" | "gone" | "unknown";

function signalCheck(pid: number): SignalVerdict {
  try {
    process.kill(pid, 0);
    return "alive";
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    // Access denial proves the process exists; it is not evidence of death.
    if (code === "EPERM") return "alive";
    if (code === "ESRCH") return "gone";
    return "unknown";
  }
}

function isPid(pid: number): boolean {
  return Number.isInteger(pid) && pid > 0;
}

/** Confirmed evidence for one pid, with the sequences that order it against OS listings. */
type TrackedPid = {
  verdict: "alive" | "dead" | null;
  /** This pid's first observation; a listing's omission proves absence only for pids observed before it was invoked. */
  firstSeq: number;
  /** Newest proof of life; a proof taken after a listing was invoked outranks that listing's omission. */
  aliveSeq: number;
  /** Waiting on the listing in flight, from `refresh(pids)` until that listing settles. */
  pending: boolean;
};

/**
 * One settled `tasklist` attempt: the evidence sequence taken at its invocation, the completion
 * time that opens its reuse window, and the listed pids (`null` when it failed, which proves nothing).
 */
type ListingRecord = { seq: number; at: number; pids: Set<number> | null };

/**
 * POSIX: every scan reads the process directly and `ESRCH` is authoritative, so there is nothing to
 * confirm and nothing to remember; an inconclusive check reads `unknown` instead of a stale verdict.
 */
function createPosixProbe(): LivenessProbe {
  return {
    kind: "posix",
    verdicts(pids: number[]): Map<number, PidVerdict> {
      const verdicts = new Map<number, PidVerdict>();
      for (const pid of pids) {
        const signal = isPid(pid) ? signalCheck(pid) : "unknown";
        verdicts.set(pid, signal === "gone" ? "dead" : signal);
      }
      return verdicts;
    },
    async refresh(): Promise<void> {
      // Signal checks are authoritative on POSIX, so nothing is confirmed in the background.
    },
  };
}

function parseListing(stdout: string): Set<number> {
  const pids = new Set<number>();
  for (const line of stdout.split(/\r?\n/)) {
    const match = /^"[^"]*","(\d+)",/.exec(line.trim());
    if (match) pids.add(Number(match[1]));
  }
  return pids;
}

function createWindowsProbe(): LivenessProbe {
  /**
   * Last confirmed evidence per pid, in LRU order (Map iteration order), capped at
   * `MAX_TRACKED_PIDS`. Eviction only drops a pid to `unknown`: a missing record is never judged by
   * any listing, so forgotten evidence can never invent death.
   */
  const tracked = new Map<number, TrackedPid>();
  /** Most recent listing attempt; reused for 30 s, including failed attempts. */
  let listing: ListingRecord | null = null;
  /** The single listing in flight; refreshes that arrive while it runs share it. */
  let task: Promise<void> | null = null;
  /** Monotonic evidence order: a listing is ordered by its invocation, a proof by its own check. */
  let evidenceSeq = 0;

  /** Move a known pid to the MRU end; eviction takes the oldest entry. */
  function touch(pid: number): TrackedPid | undefined {
    const record = tracked.get(pid);
    if (record !== undefined) {
      tracked.delete(pid);
      tracked.set(pid, record);
    }
    return record;
  }

  /** Touch a record or create it, evicting the least recently used pid once past the cap. */
  function observe(pid: number): TrackedPid {
    const record = touch(pid);
    if (record !== undefined) return record;
    const observed: TrackedPid = {
      verdict: null,
      firstSeq: ++evidenceSeq,
      aliveSeq: 0,
      pending: false,
    };
    tracked.set(pid, observed);
    if (tracked.size > MAX_TRACKED_PIDS) {
      const oldest = tracked.keys().next().value;
      if (oldest !== undefined) tracked.delete(oldest);
    }
    return observed;
  }

  function markAlive(record: TrackedPid, seq: number): void {
    record.verdict = "alive";
    if (seq > record.aliveSeq) record.aliveSeq = seq;
  }

  function inline(pid: number): PidVerdict {
    if (!isPid(pid)) return "unknown";
    const record = observe(pid);
    if (signalCheck(pid) === "alive") {
      markAlive(record, ++evidenceSeq);
      return "alive";
    }
    // `ESRCH` is unproven on Windows: only the OS listing may mark a pid dead.
    return "unknown";
  }

  /**
   * Apply a settled listing. A successful listing that omits a pid is the only thing that ever
   * marks one dead, and only for a pid whose retained evidence brackets the listing: observed
   * before it was invoked, with no newer proof of life, and not evicted since.
   */
  function applyListing(record: ListingRecord, pids: Iterable<number>): void {
    if (record.pids === null) return;
    for (const pid of pids) {
      const trackedPid = touch(pid);
      // A missing record means the evidence order against this listing is unknowable: an omission
      // must not decide for a pid the cap has already forgotten.
      if (trackedPid === undefined) continue;
      if (record.pids.has(pid)) {
        markAlive(trackedPid, record.seq);
        continue;
      }
      if (trackedPid.firstSeq > record.seq) continue;
      if (trackedPid.aliveSeq > record.seq) continue;
      trackedPid.verdict = "dead";
    }
  }

  async function runListing(): Promise<void> {
    // Taken at invocation: a proof of life that lands while this listing runs is causally newer
    // even when both read the same millisecond from `Date.now()`.
    const seq = ++evidenceSeq;
    let pids: Set<number> | null = null;
    try {
      const { stdout } = await run("tasklist", ["/NH", "/FO", "CSV"], {
        timeout: TASKLIST_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 8 * 1024 * 1024,
      });
      pids = parseListing(stdout);
    } catch {
      // A failed listing proves nothing; keep the confirmed verdicts and back off like a success.
    }
    const settled: ListingRecord = { seq, at: Date.now(), pids };
    listing = settled;
    // The pending flags are the whole waiting set, bounded with the retained history: one settled
    // attempt answers every caller that shared it.
    const pending: number[] = [];
    for (const [pid, trackedPid] of tracked) {
      if (trackedPid.pending) pending.push(pid);
    }
    applyListing(settled, pending);
    for (const pid of pending) {
      const trackedPid = tracked.get(pid);
      if (trackedPid !== undefined) trackedPid.pending = false;
    }
    task = null;
  }

  async function refresh(pids: number[]): Promise<void> {
    const valid: number[] = [];
    for (const pid of pids) {
      if (isPid(pid)) valid.push(pid);
    }
    if (valid.length === 0) return;
    const records = valid.map((pid) => observe(pid));
    const cached = listing !== null && Date.now() - listing.at < TASKLIST_REUSE_MS ? listing : null;
    if (cached !== null) {
      applyListing(cached, valid);
      return;
    }
    for (const record of records) record.pending = true;
    if (task === null) task = runListing();
    await task;
  }

  return {
    kind: "win32",
    verdicts(pids: number[]): Map<number, PidVerdict> {
      const verdicts = new Map<number, PidVerdict>();
      const revalidate: number[] = [];
      for (const pid of pids) {
        const direct = inline(pid);
        if (direct !== "unknown") {
          verdicts.set(pid, direct);
          continue;
        }
        verdicts.set(pid, tracked.get(pid)?.verdict ?? "unknown");
        // Confirmation happens off this call even with a verdict on display: callers only ask to
        // refresh `unknown` ones, so a stale `alive` would otherwise never be revisited.
        if (isPid(pid)) revalidate.push(pid);
      }
      if (revalidate.length > 0) {
        // Best effort: failed listings preserve verdicts and back off without reaching callers.
        void refresh(revalidate).catch(() => {});
      }
      return verdicts;
    },
    refresh,
  };
}

/**
 * Process liveness for run pids.
 *
 * Node's signal-0 probe is libuv's `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` plus
 * `GetExitCodeProcess`, so a clean result and `EPERM` both prove the process exists. On Windows an
 * `ESRCH` verdict is unproven, so it is confirmed against a batched `tasklist` listing: a run is
 * only ever reported `stale` after the OS stops listing its pid. Confirmation runs off the scan
 * path, so a host where process listing is slow cannot stall the panel, and `unknown` is never
 * treated as dead. A settled listing is reused for 30 s, and an inconclusive check schedules its own
 * confirmation, so a run confirmed earlier is revisited once the reuse window closes. Evidence is
 * ordered by a per-probe sequence rather than the clock, so a listing can never mark a pid stale with
 * an omission that predates that pid's latest proof of life: pid reuse is not death. Retained
 * evidence is capped (`MAX_TRACKED_PIDS`, LRU), and an evicted pid reads `unknown` until a fresh
 * listing proves it, so a long-lived server never accumulates pid history it no longer scans.
 * POSIX keeps no history at all: each scan re-reads the process, and an ambiguous check reads
 * `unknown` instead of repeating a verdict the OS no longer backs.
 */
export function createLivenessProbe(platform: NodeJS.Platform = process.platform): LivenessProbe {
  return platform === "win32" ? createWindowsProbe() : createPosixProbe();
}
