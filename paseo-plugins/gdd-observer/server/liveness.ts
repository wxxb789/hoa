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

/** A confirmed verdict and the evidence sequence it was taken at, so reused pids can be ordered. */
type ConfirmedVerdict = { verdict: PidVerdict; seq: number };

/**
 * One settled `tasklist` attempt: the evidence sequence taken at its invocation, the completion
 * time that opens its reuse window, and the listed pids (`null` when it failed, which proves nothing).
 */
type ListingRecord = { seq: number; at: number; pids: Set<number> | null };

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
 * an omission that predates that pid's latest proof of life: pid reuse is not death.
 */
export function createLivenessProbe(platform: NodeJS.Platform = process.platform): LivenessProbe {
  const kind: ProbeKind = platform === "win32" ? "win32" : "posix";
  /** Last confirmed verdict per pid. Confirmation only ever overwrites it, so nothing decays to death. */
  const confirmed = new Map<number, ConfirmedVerdict>();
  /** An omission is only evidence for pids already known when the listing was invoked. */
  const firstObserved = new Map<number, number>();
  /** Most recent listing attempt; reused for 30 s, including failed attempts. */
  let listing: ListingRecord | null = null;
  /** Pids waiting on the listing in flight, unioned so one attempt answers every caller's subset. */
  const waiting = new Set<number>();
  let task: Promise<void> | null = null;
  /** Monotonic evidence order: a listing is ordered by its invocation, a proof by its own check. */
  let evidenceSeq = 0;

  function observe(pid: number): void {
    if (!firstObserved.has(pid)) firstObserved.set(pid, ++evidenceSeq);
  }

  function inline(pid: number): PidVerdict {
    if (!Number.isInteger(pid) || pid <= 0) return "unknown";
    observe(pid);
    try {
      process.kill(pid, 0);
      return "alive";
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      // Access denial proves the process exists; it is not evidence of death.
      if (code === "EPERM") return "alive";
      if (code === "ESRCH") return kind === "posix" ? "dead" : "unknown";
      return "unknown";
    }
  }

  function parseListing(stdout: string): Set<number> {
    const pids = new Set<number>();
    for (const line of stdout.split(/\r?\n/)) {
      const match = /^"[^"]*","(\d+)",/.exec(line.trim());
      if (match) pids.add(Number(match[1]));
    }
    return pids;
  }

  /**
   * Confirm pids from a settled listing. A successful listing that omits a pid is the only thing
   * that ever marks one dead; a failed attempt leaves every verdict as it was.
   */
  function applyListing(record: ListingRecord, pids: Iterable<number>): void {
    if (record.pids === null) return;
    for (const pid of pids) {
      const present = record.pids.has(pid);
      const observed = firstObserved.get(pid);
      if (!present && observed !== undefined && observed > record.seq) continue;
      const proven = confirmed.get(pid);
      // A proof of life taken after the listing was invoked outranks it: the pid may have been
      // reused while the listing ran, and an old omission must not report the new process as dead.
      if (proven !== undefined && proven.verdict === "alive" && proven.seq > record.seq) {
        continue;
      }
      confirmed.set(pid, { verdict: present ? "alive" : "dead", seq: record.seq });
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
    listing = { seq, at: Date.now(), pids };
    applyListing(listing, waiting);
    waiting.clear();
    task = null;
  }

  async function refresh(pids: number[]): Promise<void> {
    if (kind !== "win32" || pids.length === 0) return;
    for (const pid of pids) {
      if (Number.isInteger(pid) && pid > 0) observe(pid);
    }
    const cached = listing !== null && Date.now() - listing.at < TASKLIST_REUSE_MS ? listing : null;
    if (cached !== null) {
      applyListing(cached, pids);
      return;
    }
    for (const pid of pids) waiting.add(pid);
    if (task === null) task = runListing();
    await task;
  }

  return {
    kind,
    verdicts(pids: number[]): Map<number, PidVerdict> {
      const verdicts = new Map<number, PidVerdict>();
      const revalidate: number[] = [];
      for (const pid of pids) {
        const direct = inline(pid);
        if (direct !== "unknown") {
          confirmed.set(pid, { verdict: direct, seq: ++evidenceSeq });
          verdicts.set(pid, direct);
          continue;
        }
        verdicts.set(pid, confirmed.get(pid)?.verdict ?? "unknown");
        // Confirmation happens off this call even with a verdict on display: callers only ask to
        // refresh `unknown` ones, so a stale `alive` would otherwise never be revisited.
        if (kind === "win32" && Number.isInteger(pid) && pid > 0) revalidate.push(pid);
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
