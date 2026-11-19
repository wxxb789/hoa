import { act } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OBSERVER_DEFAULTS, type ObserverSettings } from "../../shared/settings";
import type { ListRunsOutput, ListRunsUpdate } from "../../shared/runs";
import { RunsScreen } from "../runs-browser";
import { ObserverSettingsScreen } from "../settings-screen";
import {
  hostProps,
  LIST_SCAN_REVISION,
  makeRun,
  makeScan,
  makeScanFacts,
  mountedListRows,
  mountedRowCount,
  nodes,
  renderClient,
  testListViewport,
  type RenderedClient,
} from "./harness";
import { testHost } from "./setup";

// Scale coverage for the windowed run list and the shared list-scan polling election. The
// rendering tests drive the simulated host viewport from `testListViewport`; the polling tests
// drive the real React Query timers with fake time and count the RPCs the surfaces actually send.

const compactProps = { ...hostProps, layout: { ...hostProps.layout, compact: true } };

/** Run browser and settings over one test QueryClient, so the polling election is shared. */
function Surfaces({ list, settings }: { list: boolean; settings: boolean }) {
  return (
    <>
      {list ? <RunsScreen {...compactProps} params={{}} /> : null}
      {settings ? <ObserverSettingsScreen {...hostProps} /> : null}
    </>
  );
}

function populationScan(count: number): ListRunsOutput {
  const runs = Array.from({ length: count }, (_, index) =>
    makeRun({ id: `2026-11-14/run-${index}`, slug: `run-${index}`, name: `run-${index}` }),
  );
  return makeScan({
    runs,
    stats: {
      total: count,
      byState: { running: count, done: 0, failed: 0, killed: 0, unknown: 0 },
      byLiveness: { running: count, settled: 0, stale: 0, unknown: 0 },
      turns: 0,
      toolCalls: 0,
      costUsd: 0,
      countedRuns: 0,
      partialRuns: 0,
      flagged: 0,
    },
  });
}

function listCalls(view: RenderedClient): number {
  return view.invoke.mock.calls.filter(([method]) => method === "runs.list").length;
}

function readySettings(values: Partial<ObserverSettings> = {}) {
  const save = vi
    .fn<(next: ObserverSettings, revision: string) => Promise<boolean>>()
    .mockResolvedValue(true);
  testHost.settings = {
    status: "ready",
    values: { ...OBSERVER_DEFAULTS, ...values },
    revision: "revision-1",
    saving: false,
    saveError: null,
    save,
    reset: vi.fn().mockResolvedValue(true),
    reload: vi.fn().mockResolvedValue(undefined),
  };
  return { save };
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("windowed run list", () => {
  it("mounts a bounded window of rows while the header keeps the whole-scan facts", async () => {
    // The 4-row viewport is the case that discriminates the production FlatList props from the
    // adapter defaults: windowSize 3 clips the mount window to 3 × 4 = 12 rows, while the
    // adapter's own windowSize 21 would leave the viewport plus one 10-row batch — 14 rows —
    // unclipped.
    testListViewport.setRows(4);
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: populationScan(2000),
      queryDefaults: { staleTime: 0 },
    });

    // The aggregate facts come from the whole scan even though only a window of rows mounts.
    expect(view.texts()).toContain("2000 runs");

    const mounted = mountedListRows(view);
    expect(mounted).toHaveLength(12);
    expect(mounted[0].props.accessibilityLabel).toContain("run-0");
    expect(mounted[11].props.accessibilityLabel).toContain("run-11");
    expect(
      mounted.some((row) => String(row.props.accessibilityLabel).includes("run-12")),
    ).toBe(false);

    // A resized viewport re-windows the mounted list: 10 visible rows plus the next 10-row batch.
    await view.change(() => testListViewport.setRows(10));
    const resized = mountedListRows(view);
    expect(resized).toHaveLength(20);
    expect(resized[19].props.accessibilityLabel).toContain("run-19");
    expect(
      resized.some((row) => String(row.props.accessibilityLabel).includes("run-20")),
    ).toBe(false);
  });

  it("keys mounted rows by run id so a new head run does not remount the visible window", async () => {
    testListViewport.setRows(10);
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: populationScan(30),
      queryDefaults: { staleTime: 0 },
    });
    const before = mountedListRows(view);
    expect(before).toHaveLength(20);

    const head = makeRun({ id: "2026-11-15/fresh-head", slug: "fresh-head", name: "fresh-head" });
    await view.change(() => {
      view.query.setQueryData(["gddRuns", "list"], makeScan({ runs: [head, ...populationScan(30).runs] }));
    });

    const after = mountedListRows(view);
    expect(after).toHaveLength(20);
    expect(after[0]).not.toBe(before[0]);
    expect(after[0].props.accessibilityLabel).toContain("fresh-head");
    expect(after[1]).toBe(before[0]);
    expect(after[2]).toBe(before[1]);
  });

  it("reaches offscreen runs by scroll and selects one without mounting the population", async () => {
    testListViewport.setRows(4);
    const population = populationScan(2000);
    const target = population.runs[1003];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: population,
      follow: { found: true, summary: target, events: [], answerTail: null },
      queryDefaults: { staleTime: 0 },
    });
    expect(mountedRowCount(view)).toBe(12);

    // Scrolling mid-scan mounts one viewport of rows on either side of the visible four, clipped
    // by windowSize and by neither data edge: rows 996-1007.
    await view.change(() => testListViewport.scrollTo(1000));
    const scrolled = mountedListRows(view);
    expect(scrolled).toHaveLength(12);
    expect(scrolled[0].props.accessibilityLabel).toContain("run-996");
    expect(scrolled[11].props.accessibilityLabel).toContain("run-1007");

    const targetRow = scrolled.find((row) =>
      String(row.props.accessibilityLabel).includes(target.name),
    );
    expect(targetRow).toBeDefined();
    await view.change(() => targetRow!.props.onPress());
    expect(view.texts()).toContain(target.id);
    expect(mountedRowCount(view)).toBe(12);
  });

  it("returns from a selected run to the compact windowed list", async () => {
    testListViewport.setRows(10);
    const population = populationScan(2000);
    const target = population.runs[1999];
    const view = await renderClient(
      <RunsScreen {...compactProps} params={{}} />,
      {
        scan: population,
        follow: { found: true, summary: target, events: [], answerTail: null },
        queryDefaults: { staleTime: 0 },
      },
    );

    await view.change(() => testListViewport.scrollTo(1990));
    const targetRow = mountedListRows(view).find((row) =>
      String(row.props.accessibilityLabel).includes(target.name),
    );
    expect(targetRow).toBeDefined();
    await view.change(() => targetRow!.props.onPress());
    // Compact: the selected run replaces the list pane with the detail view.
    expect(mountedRowCount(view)).toBe(0);
    expect(view.texts()).toContain(target.id);

    const back = nodes(view.root, "Pressable").find((node) => node.props.accessibilityLabel === "All runs");
    expect(back).toBeDefined();
    await view.change(() => back!.props.onPress());
    // The simulated host keeps its scroll offset, so the remounted list is still bounded.
    expect(mountedRowCount(view)).toBeGreaterThanOrEqual(10);
    expect(mountedRowCount(view)).toBeLessThanOrEqual(30);
  });
});

describe("shared list polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  });

  it("elects the fastest cadence across staggered mounts, transfers it, and stops after unmount", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const view = await renderClient(<Surfaces list settings={false} />, {
      scan: makeScan({ runs: populationScan(16).runs }),
      queryDefaults: { staleTime: 0 },
    });
    // Alone, the surface mounts with a stale cached scan: the baseline immediate refetch, charged
    // separately from the polling cadence.
    expect(listCalls(view)).toBe(1);

    await advance(30_000);
    expect(listCalls(view)).toBe(2);

    // The settings screen joins an already active observer: same cache entry, no scan of its own.
    await view.update(<Surfaces list settings />);
    expect(listCalls(view)).toBe(2);
    await advance(9_999);
    expect(listCalls(view)).toBe(2);
    await advance(1);
    expect(listCalls(view)).toBe(3);
    await advance(10_000);
    expect(listCalls(view)).toBe(4);

    // The fastest surface unmounts: polling transfers to the remaining browser cadence.
    await view.update(<Surfaces list settings={false} />);
    await advance(29_999);
    expect(listCalls(view)).toBe(4);
    await advance(1);
    expect(listCalls(view)).toBe(5);

    // The last surface unmounts: polling stops.
    await view.update(<Surfaces list={false} settings={false} />);
    await advance(300_000);
    expect(listCalls(view)).toBe(5);
  });

  it("requests exactly 10 s when the settings screen is the only surface", async () => {
    readySettings();
    const view = await renderClient(<ObserverSettingsScreen {...hostProps} />, {
      scan: makeScan(),
      queryDefaults: { staleTime: 0 },
    });
    // The only observer mounts with a stale cached scan and refreshes it once.
    expect(listCalls(view)).toBe(1);
    await advance(9_999);
    expect(listCalls(view)).toBe(1);
    await advance(1);
    expect(listCalls(view)).toBe(2);
    await advance(10_000);
    expect(listCalls(view)).toBe(3);
  });

  it("keeps the run browser on its configured cadence and re-elects when that setting changes", async () => {
    readySettings({ pollIntervalMs: 5000 });
    const view = await renderClient(<Surfaces list settings={false} />, {
      scan: makeScan(),
      queryDefaults: { staleTime: 0 },
    });
    expect(listCalls(view)).toBe(1);
    await advance(4_999);
    expect(listCalls(view)).toBe(1);
    await advance(1);
    expect(listCalls(view)).toBe(2);

    readySettings({ pollIntervalMs: 1000 });
    await view.update(<Surfaces list settings={false} />);
    await advance(999);
    expect(listCalls(view)).toBe(2);
    await advance(1);
    expect(listCalls(view)).toBe(3);
  });

  it("reloads the shared scan immediately when a root save succeeds", async () => {
    readySettings({ runRoot: "" });
    const refreshed = makeScan({ runRoot: "/fixture/runs/new", scannedAt: "2026-11-14T13:00:00Z" });
    const view = await renderClient(<Surfaces list settings />, {
      scan: makeScan(),
      invoke: async (method) => {
        if (method === "runs.list") return { revision: "scan-revision-2", ...refreshed };
        throw new Error(`Unexpected RPC: ${method}`);
      },
    });
    // Fresh shared scan (the harness default staleTime is Infinity): both surfaces mount by
    // reusing it, so the save's invalidation is the only possible source of the reload below.
    expect(listCalls(view)).toBe(0);
    expect(view.texts()).toContain("Run root: /fixture/runs");

    await view.change(() => {
      nodes(view.root, "SettingsInput")[0].props.onChangeText("/fixture/runs/new");
    });
    await view.change(async () => {
      nodes(view.root, "SettingsAction")[0].props.onPress();
      for (let tick = 0; tick < 16; tick += 1) await Promise.resolve();
    });

    // No timer advanced: the save itself invalidated the shared scan for both surfaces.
    expect(listCalls(view)).toBe(1);
    expect(view.texts()).toContain("Run root: /fixture/runs/new");
    expect(view.texts()).toContain("/fixture/runs/new");
  });

  it("shares one in-flight scan across simultaneous mounts and one error afterwards", async () => {
    const view = await renderClient(<Surfaces list settings />, { pending: true });
    expect(listCalls(view)).toBe(1);

    await view.change(() => {
      view.query
        .getQueryCache()
        .find({ queryKey: ["gddRuns", "list"] })!
        .setState({ status: "error", error: new Error("fixture denied") });
    });
    expect(view.texts().filter((text) => text === "Could not read runs: fixture denied")).toHaveLength(2);
  });

  it("retries a failed scan during a one-commit browser remount", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const view = await renderClient(<RunsScreen key="before" {...compactProps} params={{}} />, {
      scan: makeScan(),
      queryDefaults: { staleTime: 0 },
    });
    expect(listCalls(view)).toBe(1);
    await view.change(() => {
      view.query.getQueryCache().find({ queryKey: ["gddRuns", "list"] })!.setState({
        status: "error",
        error: new Error("fixture denied"),
        data: undefined,
      });
    });
    expect(view.texts()).toContain("Could not read runs: fixture denied");

    await view.update(<RunsScreen key="after" {...compactProps} params={{}} />);

    // No timer tick or empty intermediate commit: the replacement is now the sole observer.
    expect(listCalls(view)).toBe(2);
    expect(view.texts()).not.toContain("Could not read runs: fixture denied");
  });

  it("reopens alone with an immediate stale refetch and a failed-scan retry", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const view = await renderClient(<Surfaces list settings={false} />, {
      scan: makeScan(),
      queryDefaults: { staleTime: 0 },
    });
    expect(listCalls(view)).toBe(1);

    // Every observer unmounts, then one surface opens alone: it refetches at once, not on cadence.
    await view.update(<Surfaces list={false} settings={false} />);
    await view.update(<Surfaces list settings={false} />);
    expect(listCalls(view)).toBe(2);

    // A failed scan with no data retries on the reopening mount, not on the next polling tick.
    await view.change(() => {
      view.query.getQueryCache().find({ queryKey: ["gddRuns", "list"] })!.setState({
        status: "error",
        error: new Error("fixture denied"),
        data: undefined,
      });
    });
    await view.update(<Surfaces list={false} settings={false} />);
    await view.update(<Surfaces list settings={false} />);
    expect(listCalls(view)).toBe(3);
  });
});

// The versioned scan: every poll names the revision of the snapshot the surface already holds and
// folds the answer (a full snapshot or a delta) into that snapshot instead of replacing it whole.

describe("versioned run scan", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  });

  it("asks from the cached scan's revision and adopts each full scan's revision", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const inputs: unknown[] = [];
    const scan = makeScan();
    const view = await renderClient(<Surfaces list settings={false} />, {
      scan,
      queryDefaults: { staleTime: 0 },
      invoke: async (method, input) => {
        if (method !== "runs.list") throw new Error(`Unexpected RPC: ${method}`);
        inputs.push(input);
        return { revision: `scan-revision-${inputs.length}`, ...scan };
      },
    });

    // No revision is held yet, so the first scan must ask for a full population.
    expect(inputs).toEqual([{}]);
    await advance(30_000);
    expect(inputs).toEqual([{}, { knownRevision: "scan-revision-1" }]);
    await advance(30_000);
    expect(inputs).toEqual([
      {},
      { knownRevision: "scan-revision-1" },
      { knownRevision: "scan-revision-2" },
    ]);
  });

  it("merges a delta's changes, removals and order onto the cached snapshot", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const [a, b, c] = populationScan(3).runs;
    const settled = makeRun({ id: a.id, slug: a.slug, name: a.name, state: "done", liveness: "settled" });
    const fresh = makeRun({ id: "2026-11-14/fresh", slug: "fresh", name: "fresh" });
    const inputs: unknown[] = [];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      queryDefaults: { staleTime: 0 },
      invoke: async (method, input) => {
        if (method !== "runs.list") throw new Error(`Unexpected RPC: ${method}`);
        inputs.push(input);
        if (inputs.length === 1) return { revision: "scan-r1", ...makeScan({ runs: [a, b, c] }) };
        const delta: ListRunsUpdate = {
          ...makeScanFacts(),
          revision: "scan-r2",
          changes: [settled, fresh],
          removed: [b.id],
          order: [fresh.id, a.id, c.id],
        };
        return delta;
      },
    });

    const before = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;

    await advance(30_000);
    expect(inputs).toEqual([{}, { knownRevision: "scan-r1" }]);
    const after = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;
    expect(before.runs.map((run) => run.id)).toEqual([a.id, b.id, c.id]);
    expect(after.runs.map((run) => run.id)).toEqual([fresh.id, a.id, c.id]);
    expect(after.runs[1].state).toBe("done");
    expect(after.runs[1].liveness).toBe("settled");
    // The untouched run keeps the summary the base snapshot already held.
    expect(after.runs[2]).toBe(before.runs[2]);
    expect(after.runs[1]).not.toBe(before.runs[0]);
  });

  it("keeps the run array when a delta restates no runs", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const population = populationScan(3);
    const inputs: unknown[] = [];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      queryDefaults: { staleTime: 0 },
      invoke: async (method, input) => {
        if (method !== "runs.list") throw new Error(`Unexpected RPC: ${method}`);
        inputs.push(input);
        if (inputs.length === 1) return { revision: "scan-r1", ...makeScan({ runs: population.runs }) };
        const delta: ListRunsUpdate = {
          ...makeScanFacts({ scannedAt: `2026-11-14T12:35:0${inputs.length}Z` }),
          revision: `scan-r${inputs.length}`,
          changes: [],
          removed: [],
        };
        return delta;
      },
    });

    const first = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;
    await advance(30_000);
    const second = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;
    await advance(30_000);
    const third = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;

    // Every empty delta restates the facts, and each time the run array (so every row identity in
    // it) is the same array the previous snapshot carried.
    expect(second.scannedAt).toBe("2026-11-14T12:35:02Z");
    expect(second).not.toBe(first);
    expect(second.runs).toBe(first.runs);
    expect(third.scannedAt).toBe("2026-11-14T12:35:03Z");
    expect(third.runs).toBe(first.runs);
    expect(third.runs[0]).toBe(first.runs[0]);
  });

  it("answers a delta whose base was replaced mid-flight with one full read", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const [a, b] = populationScan(2).runs;
    const inputs: unknown[] = [];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      queryDefaults: { staleTime: 0 },
      invoke: async (method, input) => {
        if (method !== "runs.list") throw new Error(`Unexpected RPC: ${method}`);
        inputs.push(input);
        if (inputs.length === 1) return { revision: "scan-r1", ...makeScan({ runs: [a, b] }) };
        if (inputs.length === 2) {
          // Replace the base while its delta is being produced.
          view.query.setQueryData(["gddRuns", "list"], makeScan({ runs: [b] }));
          const delta: ListRunsUpdate = {
            ...makeScanFacts(),
            revision: "scan-r2",
            changes: [],
            removed: [],
          };
          return delta;
        }
        return { revision: "scan-r9", ...makeScan({ runs: [b] }) };
      },
    });
    expect(inputs).toEqual([{}]);

    // The poll asks from scan-r1, but by the time its delta lands the cached base is gone.
    await advance(30_000);

    // The delta had no base to fold into, so the client read the full population once instead.
    expect(inputs).toEqual([{}, { knownRevision: "scan-r1" }, {}]);
    const scan = view.query.getQueryData<ListRunsOutput>(["gddRuns", "list"])!;
    expect(scan.runs.map((run) => run.id)).toEqual([b.id]);
    // The recovery read adopted its revision: the next poll asks from it.
    await advance(30_000);
    expect(inputs[3]).toEqual({ knownRevision: "scan-r9" });
  });
});

// A compact list a detail view covers must cost nothing: its pane unmounts the scan (observer,
// election registration, cadence) and the return re-runs the shared mount behaviour.

describe("hidden compact scan", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  });

  it("stops scanning while a detail covers the list and refreshes on re-entry", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const population = populationScan(3);
    const target = population.runs[0];
    const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, {
      scan: population,
      follow: { found: true, summary: target, events: [], answerTail: null },
      queryDefaults: { staleTime: 0 },
    });
    // Alone, the surface refreshes the stale cached scan once, then keeps its own cadence.
    expect(listCalls(view)).toBe(1);
    await advance(30_000);
    expect(listCalls(view)).toBe(2);
    // The default mock answers full scans with a revision, and the surface asks from it next.
    const inputs = view.invoke.mock.calls
      .filter(([method]) => method === "runs.list")
      .map(([, input]) => input);
    expect(inputs).toEqual([{}, { knownRevision: LIST_SCAN_REVISION }]);

    const row = mountedListRows(view).find((candidate) =>
      String(candidate.props.accessibilityLabel).includes(target.name),
    );
    expect(row).toBeDefined();
    await view.change(() => row!.props.onPress());
    expect(mountedRowCount(view)).toBe(0);

    // Hidden: no scan of its own and no cadence.
    await advance(300_000);
    expect(listCalls(view)).toBe(2);

    const back = nodes(view.root, "Pressable").find((node) => node.props.accessibilityLabel === "All runs");
    expect(back).toBeDefined();
    await view.change(() => back!.props.onPress());
    // Back alone: the return refresh is immediate, not the next cadence tick.
    expect(listCalls(view)).toBe(3);
    expect(mountedRowCount(view)).toBeGreaterThan(0);
  });

  it("keeps the settings cadence while hidden and joins the active scan on return", async () => {
    readySettings({ pollIntervalMs: 30_000 });
    const population = populationScan(3);
    const target = population.runs[0];
    const view = await renderClient(<Surfaces list settings />, {
      scan: population,
      follow: { found: true, summary: target, events: [], answerTail: null },
      queryDefaults: { staleTime: 0 },
    });
    // Both surfaces share one baseline refresh; the settings screen's fixed 10 s is the cadence.
    expect(listCalls(view)).toBe(1);

    const pressTarget = async (): Promise<void> => {
      const row = mountedListRows(view).find((candidate) =>
        String(candidate.props.accessibilityLabel).includes(target.name),
      );
      expect(row).toBeDefined();
      await view.change(() => row!.props.onPress());
    };
    const pressBack = async (): Promise<void> => {
      const back = nodes(view.root, "Pressable").find(
        (node) => node.props.accessibilityLabel === "All runs",
      );
      expect(back).toBeDefined();
      await view.change(() => back!.props.onPress());
    };

    await pressTarget();
    expect(mountedRowCount(view)).toBe(0);
    await advance(9_999);
    expect(listCalls(view)).toBe(1);
    await advance(1);
    expect(listCalls(view)).toBe(2);

    // The list returns while settings still watches the scan: it joins that scan instead of
    // adding a refresh, and the settings cadence keeps running.
    await pressBack();
    expect(listCalls(view)).toBe(2);
    await advance(10_000);
    expect(listCalls(view)).toBe(3);

    // Hide again, then drop settings: a hidden list registers nothing, so nothing polls the scan.
    await pressTarget();
    await view.update(<Surfaces list settings={false} />);
    await advance(60_000);
    expect(listCalls(view)).toBe(3);

    // Re-entered alone once more: the immediate refresh comes back.
    await pressBack();
    expect(listCalls(view)).toBe(4);
  });
});
