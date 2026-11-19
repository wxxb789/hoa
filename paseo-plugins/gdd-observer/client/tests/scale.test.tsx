import { act } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OBSERVER_DEFAULTS, type ObserverSettings } from "../../shared/settings";
import type { ListRunsOutput } from "../../shared/runs";
import { RunsScreen } from "../runs-browser";
import { ObserverSettingsScreen } from "../settings-screen";
import {
  hostProps,
  makeRun,
  makeScan,
  mountedListRows,
  mountedRowCount,
  mountedRowRange,
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

const listBounds = { initialNumToRender: 10, windowSize: 3, maxToRenderPerBatch: 10 };

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
    testListViewport.setRows(10);
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: populationScan(2000),
      queryDefaults: { staleTime: 0 },
    });

    // The aggregate facts come from the whole scan even though only a window of rows mounts.
    expect(view.texts()).toContain("2000 runs");

    const mounted = mountedListRows(view);
    const window = mountedRowRange(2000, listBounds);
    expect(window).toEqual({ start: 0, end: 20 });
    expect(mounted).toHaveLength(window.end - window.start);
    expect(mounted[0].props.accessibilityLabel).toContain("run-0");
    expect(mounted[19].props.accessibilityLabel).toContain("run-19");
    expect(
      mounted.some((row) => String(row.props.accessibilityLabel).includes("run-20")),
    ).toBe(false);

    // The mounted count follows the viewport, not the population.
    const small = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: populationScan(20),
      queryDefaults: { staleTime: 0 },
    });
    expect(mountedRowCount(small)).toBe(20);

    // A resized viewport re-windows the mounted list: 12 rows here is a literal from the renderer
    // adapter's arithmetic, never read back from `mountedRowRange`.
    await small.change(() => testListViewport.setRows(4));
    expect(mountedRowCount(small)).toBe(12);
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
    testListViewport.setRows(10);
    const population = populationScan(2000);
    const target = population.runs[1999];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      scan: population,
      follow: { found: true, summary: target, events: [], answerTail: null },
      queryDefaults: { staleTime: 0 },
    });
    expect(mountedRowCount(view)).toBe(20);

    await view.change(() => testListViewport.scrollTo(1990));
    const window = mountedRowRange(2000, listBounds);
    expect(window).toEqual({ start: 1980, end: 2000 });
    const scrolled = mountedListRows(view);
    expect(scrolled).toHaveLength(window.end - window.start);

    const targetRow = scrolled.find((row) =>
      String(row.props.accessibilityLabel).includes(target.name),
    );
    expect(targetRow).toBeDefined();
    await view.change(() => targetRow!.props.onPress());
    expect(view.texts()).toContain(target.id);
    expect(mountedRowCount(view)).toBe(20);
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
        if (method === "runs.list") return refreshed;
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
