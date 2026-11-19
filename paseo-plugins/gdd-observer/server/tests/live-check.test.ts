import { describe, expect, it } from "vitest";
import { followRun, listRuns, runPaths } from "../../shared/runs";
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
    console.log(
      `[live] root=${first.runRoot} source=${first.rootSource} exists=${first.rootExists} ` +
        `probe=${first.probe} stats=${JSON.stringify(first.stats)}`,
    );
    expect(first.rootExists).toBe(true);
    expect(listRuns.output.safeParse(first).success).toBe(true);

    const pids = first.runs
      .flatMap((run) => [run.pids.pid, run.pids.agentPid])
      .filter((pid): pid is number => pid !== null);
    await probe.refresh(pids);
    const scan = await store.listRuns();
    for (const run of scan.runs) {
      console.log(
        `[live] ${run.id} state=${run.state} liveness=${run.liveness} turns=${run.turns} tools=${run.toolCalls} ` +
          `cost=${run.costUsd} tool=${run.currentTool ?? "-"} bytes=${run.eventsBytes} countersFrom=${run.countersFrom} ` +
          `requested=${run.model.requested ?? "(tool default)"} thinking=${run.model.thinking ?? "-"} ` +
          `observed=${run.model.observed.map((usage) => `${usage.provider}/${usage.model}x${usage.messages}`).join(",") || "-"}`,
      );
    }
    const live = scan.runs.filter((run) => run.liveness === "running");
    console.log(`[live] runs=${scan.runs.length} live=${live.length}`);
    expect(scan.runs.length).toBeGreaterThan(0);
    expect(listRuns.output.safeParse(scan).success).toBe(true);
    const paths = runPaths.output.safeParse(await store.paths(scan.runs[0].id));
    expect(paths.success ? "" : JSON.stringify(paths.error.issues)).toBe("");
    const follow = followRun.output.safeParse(await store.follow(scan.runs[0].id, 8));
    expect(follow.success ? "" : JSON.stringify(follow.error.issues)).toBe("");
    for (const run of scan.runs) {
      if (run.liveness === "running") {
        expect(run.state).toBe("running");
        for (const [name, count] of Object.entries({
          turns: run.turns,
          toolCalls: run.toolCalls,
          eventLines: run.eventLines,
        })) {
          expect(
            count === null || (Number.isInteger(count) && count >= 0),
            `${run.id}: ${name} must be null or a non-negative integer`,
          ).toBe(true);
        }
      }
      if (run.countersFrom === "events") {
        expect(run.eventLines, `${run.id}: event-sourced counters need log lines`).toBeGreaterThan(0);
        expect(run.eventsBytes, `${run.id}: event-sourced counters need log bytes`).toBeGreaterThan(0);
      }
      if (run.eventLines > 0) {
        expect(run.eventsBytes, `${run.id}: counted log lines need log bytes`).toBeGreaterThan(0);
      }
    }
  }, 60_000);
});
