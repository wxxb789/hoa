import { describe, expect, it } from "vitest";
import { listRuns, runDetail } from "../../shared/runs";
import { createLivenessProbe } from "../liveness";
import { createRunStore } from "../run-store";

/**
 * Live check against a real launcher run root. Skipped unless `GDD_LIVE_ROOT` is set, so the
 * suite stays hermetic; run it with the daemon host's own root:
 *
 *   GDD_LIVE_ROOT=<run root> npx vitest run server/tests/live-check.test.ts
 */
const root = process.env.GDD_LIVE_ROOT?.trim() ?? "";

describe.skipIf(root === "")("live run root", () => {
  it("lists real runs with sane counters", async () => {
    const probe = createLivenessProbe();
    const store = createRunStore({
      probe,
      config: () => ({ runRoot: root, pollIntervalMs: 2000, tailLines: 10 }),
    });

    const first = await store.listRuns();
    console.log(`[live] root=${first.runRoot} source=${first.rootSource} exists=${first.rootExists} probe=${first.probe}`);
    expect(first.rootExists).toBe(true);
    expect(listRuns.output.safeParse(first).success).toBe(true);

    // Confirm unproven pids against the OS listing, then rescan: no guessed sleep, the promise
    // settles when the real process listing does.
    const pids = first.runs
      .flatMap((run) => [run.pids.pid, run.pids.agentPid])
      .filter((pid): pid is number => pid !== null);
    await probe.refresh(pids);
    const scan = await store.listRuns();
    for (const run of scan.runs) {
      console.log(
        `[live] ${run.id} state=${run.state} liveness=${run.liveness} turns=${run.turns} tools=${run.toolCalls} ` +
          `cost=${run.costUsd} tool=${run.currentTool ?? "-"} bytes=${run.eventsBytes} countersFrom=${run.countersFrom}`,
      );
    }
    const live = scan.runs.filter((run) => run.liveness === "running");
    console.log(`[live] runs=${scan.runs.length} live=${live.length}`);
    expect(scan.runs.length).toBeGreaterThan(0);
    expect(listRuns.output.safeParse(scan).success).toBe(true);
    const detail = runDetail.output.safeParse(await store.runDetail(scan.runs[0].id, 8));
    expect(detail.success ? "" : JSON.stringify(detail.error.issues)).toBe("");
    for (const run of live) {
      expect(run.state).toBe("running");
      expect(run.turns === null || run.turns > 0).toBe(true);
    }
  }, 60_000);
});
