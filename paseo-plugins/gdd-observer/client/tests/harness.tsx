import type { ReactElement, ReactNode } from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import {
  QueryClient,
  QueryClientProvider,
  type QueryClientConfig,
} from "@tanstack/react-query";
import { PluginRpcProvider, PluginTranslationProvider, PluginTranslationRuntime } from "@getpaseo/plugin/client/host";
import type { PluginHostProps } from "@getpaseo/plugin/client";
import type {
  FollowRunOutput,
  ListRunsOutput,
  RunEvent,
  RunPathsOutput,
  RunSummary,
} from "../../shared/runs";
import { afterEach, vi, type Mock } from "vitest";
import { StateBadge } from "../status-strip";

export { TestFlatList, mountedRowRange, testListViewport } from "./setup";
export type { TestFlatListProps, TestListBounds, TestListWindowSpec } from "./setup";

export const hostProps: PluginHostProps = {
  host: { id: "fixture-host", label: "Fixture host" },
  layout: { compact: false, platform: "web" },
  theme: {
    colors: {
      surface0: "#101010", surface1: "#202020", surface2: "#303030", border: "#404040",
      foreground: "#ffffff", foregroundMuted: "#aaaaaa", accent: "#0088ff", accentForeground: "#000000",
      statusSuccess: "#00cc00", statusWarning: "#ffcc00", statusDanger: "#ff0000",
    },
  },
};

export function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "2026-11-14/stage-implement", date: "2026-11-14", slug: "stage-implement",
    name: "stage-implement", runDir: "/fixture/runs/2026-11-14/stage-implement",
    state: "running", liveness: "running", finalized: false, exitCode: null,
    startedAt: null, endedAt: null, durationS: null, elapsedS: 60,
    model: { requested: null, requestedProvider: null, requestedModel: null, thinking: null, observed: [] },
    maxTime: null, sessionId: null, turns: null, toolCalls: null, costUsd: null,
    countersFrom: "none", countersPartial: false, currentTool: null, currentToolIntent: null,
    lastError: null, errorCount: 0, answerChars: null, hasAnswer: false,
    eventsBytes: 0, eventsDroppedBytes: 0, eventsTruncated: false, eventLines: 0,
    pids: { pid: null, agentPid: null }, livePids: [], lastEventAt: null, dirModifiedAt: null,
    warnings: [], ...overrides,
  };
}

export function makeScan(overrides: Partial<ListRunsOutput> = {}): ListRunsOutput {
  return {
    runRoot: "/fixture/runs", rootSource: "setting", rootExists: true,
    candidates: [{ path: "/fixture/runs", source: "setting", exists: true }],
    probe: "unavailable", scannedAt: "2026-11-14T12:34:56Z", runs: [], warnings: [],
    stats: {
      total: 0, byState: { running: 0, done: 0, failed: 0, killed: 0, unknown: 0 },
      byLiveness: { running: 0, settled: 0, stale: 0, unknown: 0 },
      turns: 0, toolCalls: 0, costUsd: 0, countedRuns: 0, partialRuns: 0, flagged: 0,
    },
    ...overrides,
  };
}

/** The scan facts without the runs: the base a delta answer replaces. */
export function makeScanFacts(
  overrides: Partial<Omit<ListRunsOutput, "runs">> = {},
): Omit<ListRunsOutput, "runs"> {
  const { runs: _runs, ...facts } = makeScan(overrides);
  return facts;
}

/** Revision the default `runs.list` mock reports; delta-driven tests supply their own `invoke`. */
export const LIST_SCAN_REVISION = "scan-revision-1";

export function makeEvent(overrides: Partial<RunEvent> = {}): RunEvent {
  return { type: "turn_end", at: null, tool: null, intent: null, detail: null, role: null, ...overrides };
}

export function textOf(node: ReactTestInstance | string | number): string {
  if (typeof node !== "object") return String(node);
  return node.children.map((child) => textOf(child)).join("");
}

export function nodes(root: ReactTestInstance, type: string): ReactTestInstance[] {
  return root.findAll((node) => node.type === type);
}

export function visibleTexts(root: ReactTestInstance): string[] {
  return nodes(root, "Text").map(textOf);
}

/**
 * The run rows the host list currently mounts. Every run row is a Pressable that carries a state
 * badge. Cross-revision measurements use accessible labels instead of module-instance identity.
 */
export function mountedListRows(view: RenderedClient): ReactTestInstance[] {
  return nodes(view.root, "Pressable")
    .filter((row) => row.findAll((node) => node.type === StateBadge).length > 0);
}

/** Number of run rows the list currently mounts. */
export function mountedRowCount(view: RenderedClient): number {
  return mountedListRows(view).length;
}

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const cleanup of cleanups.splice(0).reverse()) await cleanup();
});

type Options = {
  locale?: "en" | "zh-CN";
  scan?: ListRunsOutput;
  follow?: FollowRunOutput;
  paths?: RunPathsOutput;
  pending?: boolean;
  invoke?: (method: string, input: unknown) => Promise<unknown>;
  /** Overrides for the test QueryClient's query defaults; scale tests use `staleTime: 0`. */
  queryDefaults?: NonNullable<NonNullable<QueryClientConfig["defaultOptions"]>["queries"]>;
};

export interface RenderedClient {
  tree: ReactTestRenderer;
  query: QueryClient;
  invoke: Mock<(method: string, input: unknown) => Promise<unknown>>;
  translations: PluginTranslationRuntime;
  readonly root: ReactTestInstance;
  texts(): string[];
  update(next: ReactElement): Promise<void>;
  change(action: () => void | Promise<void>): Promise<void>;
}

export async function renderClient(element: ReactElement, options: Options = {}): Promise<RenderedClient> {
  const locale = options.locale ?? "en";
  const translations = new PluginTranslationRuntime({ getLocale: () => locale, subscribe: () => () => {} });
  const query = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity, ...options.queryDefaults },
    },
  });
  const scan = options.scan ?? makeScan();
  const follow = options.follow ?? { found: false, summary: null, events: [], answerTail: null };
  const paths = options.paths ?? { found: false, paths: [], scannedAt: scan.scannedAt };
  if (!options.pending) {
    query.setQueryData(["gddRuns", "list"], scan);
    if (follow.summary) {
      query.setQueryData(["gddRuns", "follow", follow.summary.id, 80], follow);
      query.setQueryData(["gddRuns", "paths", follow.summary.id], paths);
    }
  }
  const invoke = vi.fn(options.invoke ?? (async (method: string) => {
    if (options.pending) return new Promise<never>(() => {});
    if (method === "runs.list") return { revision: LIST_SCAN_REVISION, ...scan };
    if (method === "runs.follow") return follow;
    if (method === "runs.paths") return paths;
    throw new Error(`Unexpected RPC: ${method}`);
  }));
  function wrap(children: ReactNode) {
    return (
      <PluginTranslationProvider runtime={translations}>
        <PluginRpcProvider invoke={invoke}>
          <QueryClientProvider client={query}>{children}</QueryClientProvider>
        </PluginRpcProvider>
      </PluginTranslationProvider>
    );
  }
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(wrap(element)); });
  cleanups.push(async () => {
    await act(async () => { tree.unmount(); });
    query.clear();
    translations.dispose();
    // Unmount while a test's fake clock is still installed so pending polling timers are cleared
    // against the timers that created them, then hand the real clock back to the runner.
    if (vi.isFakeTimers()) vi.useRealTimers();
  });
  return {
    tree, query, invoke, translations,
    get root() { return tree.root; },
    texts: () => visibleTexts(tree.root),
    async update(next: ReactElement) { await act(async () => { tree.update(wrap(next)); }); },
    async change(action: () => void | Promise<void>) { await act(async () => { await action(); }); },
  };
}
