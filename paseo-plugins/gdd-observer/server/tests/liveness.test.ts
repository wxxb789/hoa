import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setImmediate as tick } from "node:timers/promises";

const execFileMock = vi.hoisted(() => vi.fn());

// `liveness.ts` captures `promisify(execFile)` when it loads, so the OS listing boundary is mocked
// before importing it. Each invocation stays pending until the test settles it.
vi.mock("node:child_process", () => ({ execFile: execFileMock }));

import { createLivenessProbe, MAX_TRACKED_PIDS } from "../liveness";
import { mapRun, type RunFiles } from "../state";

type ExecCallback = (error: Error | null, result?: { stdout: string; stderr: string }) => void;

/** One mocked `tasklist` invocation with the fake clock's time at the call. */
type ListingCall = { at: number; command: string; args: string[] };

let now: number;
let calls: ListingCall[];
let pending: ExecCallback[];

beforeEach(() => {
  now = 0;
  calls = [];
  pending = [];
  vi.spyOn(Date, "now").mockImplementation(() => now);
  vi.spyOn(process, "kill").mockImplementation(() => true);
  execFileMock.mockReset();
  execFileMock.mockImplementation(
    (command: string, args: string[], _options: unknown, callback: ExecCallback) => {
      calls.push({ at: Date.now(), command, args });
      pending.push(callback);
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

function advanceTo(ms: number): void {
  now = ms;
}

/** Only `alivePids` answer signal 0; every other pid fails with `code`. */
function killCheck(alivePids: number[], code = "ESRCH"): void {
  const alive = new Set(alivePids);
  vi.mocked(process.kill).mockImplementation((pid): true => {
    if (alive.has(pid)) return true;
    throw Object.assign(new Error(`${code}: kill ${pid}`), { code });
  });
}

/** Answer the pending `tasklist` invocation with exactly `pids`, then let the probe apply it. */
function resolveListing(pids: number[]): Promise<void> {
  const settle = pending.shift();
  if (settle === undefined) throw new Error("no OS listing is pending");
  const stdout = pids.map((pid) => `"image.exe","${pid}","Console","1","1,024 K"`).join("\r\n");
  settle(null, { stdout, stderr: "" });
  // Let the microtasks queued behind the settled listing run before the next assertion.
  return tick();
}

/** Fail the pending `tasklist` invocation, then let the probe keep its verdicts. */
function failListing(code = "ETIMEDOUT"): Promise<void> {
  const settle = pending.shift();
  if (settle === undefined) throw new Error("no OS listing is pending");
  settle(Object.assign(new Error(`tasklist ${code}`), { code }), undefined);
  return tick();
}

describe("liveness probe", () => {
  it("answers posix verdicts from the process check and never lists", async () => {
    const probe = createLivenessProbe("linux");
    killCheck([100]);
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(probe.verdicts([200]).get(200)).toBe("dead");
    await probe.refresh([100, 200]);
    expect(calls).toHaveLength(0);
    expect(probe.verdicts([100, 200]).get(100)).toBe("alive");
    expect(probe.verdicts([100, 200]).get(200)).toBe("dead");
  });

  it("never lists on posix even for an inconclusive check", () => {
    const probe = createLivenessProbe("linux");
    killCheck([], "EIO");
    expect(probe.verdicts([400]).get(400)).toBe("unknown");
    expect(calls).toHaveLength(0);
  });

  it("keeps no posix verdict history: an ambiguous check reads unknown, never a remembered verdict", () => {
    const probe = createLivenessProbe("linux");
    killCheck([100]);
    expect(probe.verdicts([100]).get(100)).toBe("alive");

    killCheck([], "EIO");
    expect(probe.verdicts([100]).get(100)).toBe("unknown"); // fresh ambiguity, not the earlier proof of life

    killCheck([], "ESRCH");
    expect(probe.verdicts([100]).get(100)).toBe("dead"); // absence is authoritative on posix

    killCheck([], "EIO");
    expect(probe.verdicts([100]).get(100)).toBe("unknown"); // and no dead verdict is remembered either
    expect(calls).toHaveLength(0);
  });

  it("treats access denial on Windows as proof of life", () => {
    const probe = createLivenessProbe("win32");
    killCheck([], "EPERM");
    expect(probe.verdicts([300]).get(300)).toBe("alive");
    expect(calls).toHaveLength(0);
  });

  it("keeps an inconclusive process check unknown, then confirms it from a listing", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([], "EIO");
    expect(probe.verdicts([300]).get(300)).toBe("unknown");
    expect(calls).toHaveLength(1);
    await resolveListing([300]);
    expect(probe.verdicts([300]).get(300)).toBe("alive");
    expect(calls).toHaveLength(1);
  });

  it("does not list for values that cannot be run pids", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    const verdicts = probe.verdicts([0, -1, 1.5]);
    expect([...verdicts.values()]).toEqual(["unknown", "unknown", "unknown"]);
    await probe.refresh([0, -1, 1.5]);
    expect(calls).toHaveLength(0);
  });

  it("reuses a settled listing for 30 seconds and lists again at the boundary", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    expect(probe.verdicts([100]).get(100)).toBe("unknown");
    expect(calls).toHaveLength(1);
    const confirming = probe.refresh([100]);
    expect(calls).toHaveLength(1); // the explicit call shares the listing already in flight
    await resolveListing([100]);
    await confirming;

    advanceTo(29_999);
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);

    advanceTo(30_000);
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(2);
    await resolveListing([]);
    expect(probe.verdicts([100]).get(100)).toBe("dead");
    expect(calls).toHaveLength(2);
  });

  it("spends at most two listings across a warmed 60-second interval of two-second scans", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    const listedAt: number[] = [];

    for (let t = 0; t < 60_000; t += 2_000) {
      advanceTo(t);
      expect(probe.verdicts([100]).get(100)).not.toBe("dead");
      if (pending.length > 0) {
        listedAt.push(calls[calls.length - 1].at);
        await resolveListing([100]);
      }
    }

    expect(listedAt).toEqual([0, 30_000]);
    expect(listedAt.length).toBeLessThanOrEqual(2);
    expect(probe.verdicts([100]).get(100)).toBe("alive");

    advanceTo(60_000);
    probe.verdicts([100]);
    expect(calls).toHaveLength(3); // the interval is half-open: the next window opens at 60 s
  });

  it("revalidates an inconclusive pid off the scan path while a confirmed alive verdict is displayed", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([100]);
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(0); // a direct proof of life needs no listing

    advanceTo(2_000);
    killCheck([]);
    const displayed = probe.verdicts([100]);
    expect(displayed.get(100)).toBe("alive"); // the last confirmed verdict, not a fresh proof
    expect(displayed.get(100)).not.toBe("unknown"); // so the store would ask for no refresh
    expect(calls).toHaveLength(1); // the probe still confirms the exit off the scan path
    await resolveListing([]);
    expect(probe.verdicts([100]).get(100)).toBe("dead");
    expect(calls).toHaveLength(1);

    advanceTo(31_999);
    expect(probe.verdicts([100]).get(100)).toBe("dead");
    expect(calls).toHaveLength(1);
  });

  it("keeps verdicts through a failed listing and backs the next attempt off like a success", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([100]);
    expect(probe.verdicts([100]).get(100)).toBe("alive");

    advanceTo(2_000);
    killCheck([]);
    const scan = probe.verdicts([100, 200]);
    expect(scan.get(100)).toBe("alive");
    expect(scan.get(200)).toBe("unknown");
    expect(calls).toHaveLength(1);
    await failListing();
    expect(probe.verdicts([100, 200]).get(100)).toBe("alive");
    expect(probe.verdicts([100, 200]).get(200)).toBe("unknown");
    expect(calls).toHaveLength(1);

    advanceTo(31_999);
    probe.verdicts([100, 200]);
    expect(calls).toHaveLength(1);

    advanceTo(32_000);
    probe.verdicts([100, 200]);
    expect(calls).toHaveLength(2);
    await resolveListing([]);
    expect(probe.verdicts([100, 200]).get(100)).toBe("dead");
    expect(probe.verdicts([100, 200]).get(200)).toBe("dead");
  });

  it("does not apply a listing invoked before a newer proof of life", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    probe.verdicts([100]); // unknown, so a listing starts at t = 0
    expect(calls).toHaveLength(1);

    advanceTo(1_000);
    killCheck([100]); // pid 100 now belongs to a live process
    expect(probe.verdicts([100]).get(100)).toBe("alive");

    advanceTo(2_000);
    await resolveListing([]); // the listing was invoked before that proof of life
    await probe.refresh([100]); // a reuse of that same negative listing
    expect(calls).toHaveLength(1);

    killCheck([]); // no direct proof now, so only the confirmed verdict answers
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);
  });

  it("lets a newer proof of life override a confirmed absence from a reused listing", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    probe.verdicts([100]);
    await resolveListing([]);
    expect(probe.verdicts([100]).get(100)).toBe("dead");

    advanceTo(2_000);
    killCheck([100]); // the pid was reused by a live process
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    await probe.refresh([100]); // the cached negative listing is still fresh
    expect(calls).toHaveLength(1);

    killCheck([]); // no direct proof now, so only the confirmed verdict answers
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);
  });

  it("keeps a proof of life taken while a listing was in flight when both share one clock reading", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    probe.verdicts([100]); // a listing is invoked first, at now = 0
    expect(calls).toHaveLength(1);

    killCheck([100]); // the pid is reused by a live process, still at now = 0
    expect(probe.verdicts([100]).get(100)).toBe("alive");

    await resolveListing([]); // the negative listing settles without the clock moving
    killCheck([]); // no direct proof now, so only the confirmed verdict answers
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);
  });

  it("keeps a proof of life taken after a listing settled when both share one clock reading", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    probe.verdicts([100]); // a listing is invoked first, at now = 0
    await resolveListing([]); // confirmed absent, still at now = 0
    expect(probe.verdicts([100]).get(100)).toBe("dead");

    killCheck([100]); // the pid is reused by a live process, still at now = 0
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    await probe.refresh([100]); // the cached negative listing is still fresh
    expect(calls).toHaveLength(1);

    killCheck([]); // no direct proof now, so only the confirmed verdict answers
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);
  });

  it("answers every in-flight caller's subset from one shared listing", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    const first = probe.verdicts([100]);
    const second = probe.verdicts([200]);
    expect(first.get(100)).toBe("unknown");
    expect(second.get(200)).toBe("unknown");
    expect(calls).toHaveLength(1);

    const refreshA = probe.refresh([100]);
    const refreshB = probe.refresh([200]);
    expect(calls).toHaveLength(1); // no per-subset listing

    await resolveListing([100]);
    await Promise.all([refreshA, refreshB]);
    expect(probe.verdicts([100]).get(100)).toBe("alive"); // asked about before that listing was invoked
    expect(probe.verdicts([200]).get(200)).toBe("unknown"); // asked about after it: its omission proves nothing
    expect(calls).toHaveLength(1);

    // At the reuse boundary one listing eligible for both pids settles and still answers each subset.
    advanceTo(30_000);
    const nextA = probe.refresh([100]);
    const nextB = probe.refresh([200]);
    expect(calls).toHaveLength(2); // still one listing for both callers
    await resolveListing([100]);
    await Promise.all([nextA, nextB]);
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(probe.verdicts([200]).get(200)).toBe("dead"); // now the omission is causally newer
    expect(calls).toHaveLength(2);
  });

  it("keeps a pid unknown until a listing invoked after its first observation proves absence", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    expect(probe.verdicts([100]).get(100)).toBe("unknown"); // t = 0: an inconclusive pid starts a listing
    expect(calls).toHaveLength(1);
    await resolveListing([100]); // it settles at t = 0 without pid 777, which does not exist yet
    expect(probe.verdicts([100]).get(100)).toBe("alive");
    expect(calls).toHaveLength(1);

    // t = 20 s: pid 777 is first observed while that settled listing is still inside its reuse window.
    advanceTo(20_000);
    expect(probe.verdicts([777]).get(777)).toBe("unknown");
    expect(calls).toHaveLength(1);
    await tick();

    // The listing was invoked before pid 777 was ever asked about, so its omission proves nothing about
    // it: reporting `dead` here is the verdict the store surfaces as `stale`.
    advanceTo(22_000);
    expect(probe.verdicts([777]).get(777)).toBe("unknown");
    expect(calls).toHaveLength(1);

    advanceTo(28_000);
    expect(probe.verdicts([777]).get(777)).toBe("unknown");
    expect(calls).toHaveLength(1); // the reuse window holds: no listing is started for the skipped pid

    // t = 30 s: the reuse window closes, so a listing invoked after the first observation starts.
    advanceTo(30_000);
    expect(probe.verdicts([777]).get(777)).toBe("unknown"); // displayed until that listing settles
    expect(calls).toHaveLength(2);
    await resolveListing([]);
    expect(probe.verdicts([777]).get(777)).toBe("dead"); // only now is the omission causally newer
    expect(calls).toHaveLength(2);
  });

  it("keeps a pid unknown when its first mention is a refresh reusing an older listing", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    expect(probe.verdicts([100]).get(100)).toBe("unknown"); // t = 0: pid 100 starts the listing
    expect(calls).toHaveLength(1);
    await resolveListing([100]); // it settles at t = 0 without pid 777

    // t = 20 s: the probe first hears about pid 777 through the explicit confirmation entry point, which
    // records that observation before it applies the settled listing.
    advanceTo(20_000);
    await probe.refresh([777]);
    expect(calls).toHaveLength(1); // the settled listing is reused instead of replaced
    expect(probe.verdicts([777]).get(777)).toBe("unknown"); // its omission predates the pid

    advanceTo(30_000);
    expect(probe.verdicts([777]).get(777)).toBe("unknown"); // still no listing newer than the pid
    expect(calls).toHaveLength(2);
    await resolveListing([]);
    expect(probe.verdicts([777]).get(777)).toBe("dead");
    expect(calls).toHaveLength(2);
  });

  it("caps retained Windows history and re-observes an evicted pid without inventing death", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    // t = 0: one listing omits both pids, marking them dead within its reuse window.
    expect(probe.verdicts([100, 101]).get(100)).toBe("unknown");
    expect(calls).toHaveLength(1);
    await resolveListing([]);
    const confirmed = probe.verdicts([100, 101]);
    expect(confirmed.get(100)).toBe("dead");
    expect(confirmed.get(101)).toBe("dead");

    // Overflow the cap with fresh pids. Every scan is answered from the settled listing's reuse
    // window, so no extra tasklist subprocess is spawned per poll.
    for (let pid = 200; pid < 200 + MAX_TRACKED_PIDS; pid++) {
      expect(probe.verdicts([pid]).get(pid)).toBe("unknown");
    }
    expect(calls).toHaveLength(1);

    // The oldest history was evicted: pid 100 is re-observed and reads unknown — never the `dead`
    // the cap can no longer justify, and the listing older than the re-observation cannot re-prove it.
    expect(probe.verdicts([100]).get(100)).toBe("unknown");
    expect(calls).toHaveLength(1);

    // A listing invoked at 30 s starts for pid 999; pid 101 is re-observed while it is in flight.
    advanceTo(30_000);
    expect(probe.verdicts([999]).get(999)).toBe("unknown");
    expect(calls).toHaveLength(2);
    advanceTo(31_000);
    expect(probe.verdicts([101]).get(101)).toBe("unknown");
    expect(calls).toHaveLength(2);

    // The listing predates pid 101's re-observation, so its omission proves nothing about it, while
    // pid 999, observed before the listing was invoked, is confirmed absent.
    await resolveListing([]);
    expect(probe.verdicts([999]).get(999)).toBe("dead");
    expect(probe.verdicts([101]).get(101)).toBe("unknown");
    expect(calls).toHaveLength(2);

    // Once a listing is invoked after the re-observation, absence is proven normally.
    await probe.refresh([100]);
    expect(probe.verdicts([100]).get(100)).toBe("dead");
    expect(calls).toHaveLength(2);
  });

  it("never lets a listing kill a pending pid whose history was evicted mid-flight", async () => {
    const probe = createLivenessProbe("win32");
    killCheck([]);
    expect(probe.verdicts([5]).get(5)).toBe("unknown"); // t = 0: pid 5 starts and waits on the listing
    expect(calls).toHaveLength(1);

    // Fresh unknown pids evict pid 5's record while the listing is still in flight; their own scans
    // share that listing instead of spawning new subprocesses.
    for (let pid = 200; pid < 200 + MAX_TRACKED_PIDS; pid++) {
      expect(probe.verdicts([pid]).get(pid)).toBe("unknown");
    }
    expect(calls).toHaveLength(1);

    // The listing an evicted pid was waiting on predates anything still known about it; re-observing
    // it must read unknown rather than let that omission mark it dead.
    await resolveListing([]);
    expect(probe.verdicts([5]).get(5)).toBe("unknown");
    expect(calls).toHaveLength(1);
  });

  it("first displays stale at the 46-second scan after a skipped in-flight listing", async () => {
    const probe = createLivenessProbe("win32");
    const files: RunFiles = {
      dir: "/runs/2026-11-14/timeline",
      date: "2026-11-14",
      slug: "timeline",
      state: { present: true, readable: true, values: { state: "running", pid: 777 } },
      lock: null,
      finalized: { present: false, exitCode: null },
      stats: null,
      answer: { exists: false, bytes: null },
      events: { exists: false, bytes: 0 },
      sessionIdFromFile: null,
      dirModifiedAt: null,
    };
    const scans: Array<{ at: number; liveness: string }> = [];
    function scan(): string {
      const { liveness } = mapRun(
        { files, counters: null, logReadable: true, verdicts: probe.verdicts([777]) },
        Date.now(),
      );
      scans.push({ at: Date.now(), liveness });
      return liveness;
    }
    killCheck([]);
    // t = 0: the pid is not visible yet, so an inconclusive scan starts the only listing that predates the
    // proof of life below. Scans are what invoke listings, so its invocation is one interval before it.
    expect(scan()).toBe("unknown");
    expect(calls).toHaveLength(1);

    // t = 2 s: the pid is alive, proving life after that listing was invoked, and no listing is started.
    advanceTo(2_000);
    killCheck([777]);
    expect(scan()).toBe("running");
    expect(calls).toHaveLength(1);

    // t = 4 s: the process exits, so the check is inconclusive again and asks for confirmation.
    killCheck([]);
    for (const t of [4_000, 6_000]) {
      advanceTo(t);
      expect(scan()).toBe("running"); // the last confirmed verdict, never stale
      expect(calls).toHaveLength(1); // the in-flight listing is joined, not replaced
    }

    // The in-flight listing settles 1 ms inside its 8 s budget and omits the pid. Its invocation predates
    // that proof of life, so it is skipped. Its completion anchors the reuse window.
    advanceTo(7_999);
    await resolveListing([]);
    advanceTo(8_000);
    expect(scan()).toBe("running");
    expect(calls).toHaveLength(1);

    // While that window is open every scan keeps the last proof of life and starts no listing.
    for (let t = 10_000; t <= 36_000; t += 2_000) {
      advanceTo(t);
      expect(scan()).toBe("running");
      expect(calls).toHaveLength(1);
    }

    // The first listing invoked after the proof of life starts at the 38 s tick — that is what the skipped
    // listing's own completion bought it.
    advanceTo(38_000);
    expect(scan()).toBe("running");
    expect(calls).toHaveLength(2);
    expect(calls[1].at).toBe(38_000);

    // That listing can prove absence, but until it settles the displayed verdict stays `alive`.
    for (let t = 40_000; t <= 44_000; t += 2_000) {
      advanceTo(t);
      expect(scan()).toBe("running");
      expect(calls).toHaveLength(2);
    }
    advanceTo(45_999);
    await resolveListing([]); // 43,999 ms after the proof of life the omission turns the pid `dead`

    advanceTo(46_000);
    expect(scan()).toBe("stale");
    expect(scans.find((entry) => entry.liveness === "stale")?.at).toBe(46_000);
    expect(calls.map((call) => call.at)).toEqual([0, 38_000]);
    expect(calls).toHaveLength(2);

    // The dead verdict gets the same reuse treatment: 30 s without a listing, then the next one, so this
    // timeline keeps at most two listings per warmed minute.
    for (const t of [48_000, 60_000]) {
      advanceTo(t);
      expect(scan()).toBe("stale");
      expect(calls).toHaveLength(2);
    }
    advanceTo(76_000);
    expect(scan()).toBe("stale");
    expect(calls).toHaveLength(3);
    await resolveListing([]);
    expect(scan()).toBe("stale");
  });
});
