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
   * unproven pids keep their last confirmed verdict (`unknown` until one exists).
   */
  verdicts(pids: number[]): Map<number, PidVerdict>;
  /** Confirm unproven pids against the OS listing. Resolves when the listing settles. */
  refresh(pids: number[]): Promise<void>;
};

const TASKLIST_TIMEOUT_MS = 8000;
const TASKLIST_TTL_MS = 5000;

/**
 * Process liveness for run pids.
 *
 * Node's signal-0 probe is libuv's `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` plus
 * `GetExitCodeProcess`, so a clean result and `EPERM` both prove the process exists. On Windows an
 * `ESRCH` verdict is unproven, so it is confirmed against a batched `tasklist` listing: a run is
 * only ever reported `stale` after the OS stops listing its pid. Confirmation runs off the scan
 * path, so a host where process listing is slow cannot stall the panel, and `unknown` is never
 * treated as dead.
 */
export function createLivenessProbe(platform: NodeJS.Platform = process.platform): LivenessProbe {
  const kind: ProbeKind = platform === "win32" ? "win32" : "posix";
  /** Last confirmed verdict per pid. Refreshes only ever overwrite it, so nothing decays to death. */
  const verdictCache = new Map<number, PidVerdict>();
  let listing: { at: number; pids: Set<number> | null } | null = null;
  let inFlight: Promise<void> | null = null;

  function inline(pid: number): PidVerdict {
    if (!Number.isInteger(pid) || pid <= 0) return "unknown";
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

  async function listPids(): Promise<Set<number> | null> {
    const now = Date.now();
    if (listing && now - listing.at < TASKLIST_TTL_MS) return listing.pids;
    try {
      const { stdout } = await run("tasklist", ["/NH", "/FO", "CSV"], {
        timeout: TASKLIST_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 8 * 1024 * 1024,
      });
      const pids = new Set<number>();
      for (const line of stdout.split(/\r?\n/)) {
        const match = /^"[^"]*","(\d+)",/.exec(line.trim());
        if (match) pids.add(Number(match[1]));
      }
      listing = { at: Date.now(), pids };
      return pids;
    } catch {
      listing = { at: Date.now(), pids: null };
      return null;
    }
  }

  return {
    kind,
    verdicts(pids: number[]): Map<number, PidVerdict> {
      const verdicts = new Map<number, PidVerdict>();
      for (const pid of pids) {
        const direct = inline(pid);
        if (direct !== "unknown") {
          verdictCache.set(pid, direct);
          verdicts.set(pid, direct);
          continue;
        }
        verdicts.set(pid, verdictCache.get(pid) ?? "unknown");
      }
      return verdicts;
    },
    async refresh(pids: number[]): Promise<void> {
      if (kind !== "win32") return;
      const unproven = pids.filter((pid) => inline(pid) === "unknown");
      if (unproven.length === 0) return;
      if (inFlight) {
        await inFlight;
        return;
      }
      inFlight = (async () => {
        const listed = await listPids();
        for (const pid of unproven) {
          // A failed listing leaves the previous verdict in place rather than inventing death.
          if (listed !== null) verdictCache.set(pid, listed.has(pid) ? "alive" : "dead");
        }
      })();
      try {
        await inFlight;
      } finally {
        inFlight = null;
      }
    },
  };
}
