import {
  Fragment,
  cloneElement,
  createElement,
  useImperativeHandle,
  useState,
  useSyncExternalStore,
  type ReactElement,
} from "react";
import { environmentManager, notifyManager } from "@tanstack/react-query";
import type { SettingsInputProps } from "@getpaseo/plugin/client/ui";
import type { SettingsState } from "@getpaseo/plugin/client";
import type { observerSettingsSchema } from "../../shared/settings";
import { OBSERVER_DEFAULTS } from "../../shared/settings";
import { beforeEach, vi } from "vitest";

// ---------------------------------------------------------------------------------------------
// Host list adapter
//
// The host's FlatList is replaced with a renderer-level stand-in that keeps the real component
// tree: it renders only the rows a bounded list would mount, keys them with the production
// `keyExtractor`, and renders the production header and empty slots. `testListViewport` sets the
// simulated viewport height (in rows) and the simulated scroll position; both are global because
// they stand in for the host device, not for the plugin.
// ---------------------------------------------------------------------------------------------

export interface TestListWindowSpec {
  /** Rows the simulated viewport shows at once. */
  rows: number;
  /** Index of the first visible row (the simulated scroll offset). */
  scrollIndex: number;
}

/** Bounds the production list passes to the real FlatList; defaults mirror React Native. */
export interface TestListBounds {
  initialNumToRender?: number;
  windowSize?: number;
  maxToRenderPerBatch?: number;
}

export interface TestListRowInfo<Item> {
  item: Item;
  index: number;
  separators: {
    highlight(): void;
    unhighlight(): void;
    updateProps(select: "leading" | "trailing", nextProps: unknown): void;
  };
}

export interface TestFlatListProps<Item> {
  data?: ArrayLike<Item> | null;
  renderItem?: ((info: TestListRowInfo<Item>) => ReactElement | null) | null;
  keyExtractor?: (item: Item, index: number) => string;
  ListHeaderComponent?: ReactElement | ((props: Record<string, never>) => ReactElement | null) | null;
  ListEmptyComponent?: ReactElement | ((props: Record<string, never>) => ReactElement | null) | null;
  initialNumToRender?: number;
  windowSize?: number;
  maxToRenderPerBatch?: number;
}

const DEFAULT_VIEWPORT_ROWS = 10;

let viewport: TestListWindowSpec = { rows: DEFAULT_VIEWPORT_ROWS, scrollIndex: 0 };
let viewportSnapshot: TestListWindowSpec = { ...viewport };
const viewportListeners = new Set<() => void>();

function publishViewport(next: TestListWindowSpec): void {
  const rows = Math.max(1, Math.trunc(next.rows));
  const scrollIndex = Math.max(0, Math.trunc(next.scrollIndex));
  if (rows === viewport.rows && scrollIndex === viewport.scrollIndex) return;
  viewport = { rows, scrollIndex };
  viewportSnapshot = { ...viewport };
  for (const listener of viewportListeners) listener();
}

/**
 * Test-side viewport for the list adapter. `setRows` models the device height in rows, `scrollTo`
 * models scrolling so the given row index is visible first, and `reset` restores both defaults
 * (also run before every test). Changes re-render mounted lists, so drive them inside `act`:
 * `await view.change(() => testListViewport.scrollTo(1990))`.
 */
export const testListViewport = {
  subscribe(listener: () => void): () => void {
    viewportListeners.add(listener);
    return () => {
      viewportListeners.delete(listener);
    };
  },
  getSnapshot: (): TestListWindowSpec => viewportSnapshot,
  setRows(rows: number): void {
    publishViewport({ rows, scrollIndex: viewport.scrollIndex });
  },
  scrollTo(scrollIndex: number): void {
    publishViewport({ rows: viewport.rows, scrollIndex });
  },
  reset(): void {
    publishViewport({ rows: DEFAULT_VIEWPORT_ROWS, scrollIndex: 0 });
  },
};

/**
 * Rows the adapter mounts for `count` items: the visible viewport plus at most one mount batch on
 * either side, clipped to the host window (`windowSize` viewport lengths) and to the data. A
 * simplified model of bounded list mounting, not a native-host proof.
 */
export function mountedRowRange(
  count: number,
  bounds: TestListBounds = {},
  view: TestListWindowSpec = viewportSnapshot,
): { start: number; end: number } {
  if (count <= 0) return { start: 0, end: 0 };
  const rows = Math.max(1, Math.trunc(view.rows));
  const initialNumToRender = Math.max(1, Math.trunc(bounds.initialNumToRender ?? 10));
  const windowSize = Math.max(1, Math.trunc(bounds.windowSize ?? 21));
  const batch = Math.max(1, Math.trunc(bounds.maxToRenderPerBatch ?? 10));
  const scrollIndex = Math.min(Math.max(0, Math.trunc(view.scrollIndex)), count - 1);
  const windowLength = Math.max(rows, windowSize * rows);
  const windowStart = Math.min(
    Math.max(scrollIndex - Math.floor((windowLength - rows) / 2), 0),
    Math.max(0, count - windowLength),
  );
  const start = Math.max(windowStart, scrollIndex - batch, 0);
  let end = Math.min(windowStart + windowLength, scrollIndex + rows + batch, count);
  if (scrollIndex === 0) end = Math.max(end, Math.min(count, initialNumToRender));
  return { start, end };
}

const listSeparators = {
  highlight() {},
  unhighlight() {},
  updateProps() {},
};

function renderListSlot(
  slot: ReactElement | ((props: Record<string, never>) => ReactElement | null) | null | undefined,
): ReactElement | null {
  if (slot === null || slot === undefined) return null;
  return typeof slot === "function" ? slot({}) : slot;
}

/**
 * Stand-in for the host FlatList. Only the rows `mountedRowRange` selects render, so mounted-row
 * counts reflect bounded mounting instead of the whole scan.
 */
export function TestFlatList<Item>(props: TestFlatListProps<Item>): ReactElement {
  const view = useSyncExternalStore(testListViewport.subscribe, testListViewport.getSnapshot);
  const data = props.data;
  const count = data === null || data === undefined ? 0 : data.length;
  const range = mountedRowRange(
    count,
    {
      initialNumToRender: props.initialNumToRender,
      windowSize: props.windowSize,
      maxToRenderPerBatch: props.maxToRenderPerBatch,
    },
    view,
  );
  const rows: ReactElement[] = [];
  const renderItem = props.renderItem;
  if (data !== null && data !== undefined && renderItem !== null && renderItem !== undefined) {
    for (let index = range.start; index < range.end; index += 1) {
      const item = data[index] as Item;
      const rendered = renderItem({ item, index, separators: listSeparators });
      if (rendered === null) continue;
      const key = props.keyExtractor ? props.keyExtractor(item, index) : String(index);
      rows.push(cloneElement(rendered as ReactElement<{ key?: string }>, { key }));
    }
  }
  return createElement(
    Fragment,
    null,
    renderListSlot(props.ListHeaderComponent),
    count === 0 ? renderListSlot(props.ListEmptyComponent) : null,
    ...rows,
  );
}

// Only services and primitives supplied by the Paseo host are replaced. Translation,
// RPC validation, tab state, React Query and all plugin components remain real.
const testHost = vi.hoisted(() => ({
  settings: null as unknown as SettingsState<typeof observerSettingsSchema>,
  copyText: vi.fn<(text: string) => Promise<void>>(),
  toast: { show: vi.fn(), error: vi.fn() },
}));

export { testHost };

vi.mock("react-native", () => ({ Text: "Text", View: "View", Pressable: "Pressable" }));

vi.mock("@getpaseo/plugin/client", async (original) => ({
  ...(await original<object>()),
  useSettings: () => testHost.settings,
}));

vi.mock("@getpaseo/plugin/client/ui", () => ({
  Icon: "Icon",
  Loading: "Loading",
  Markdown: "Markdown",
  ScrollView: "ScrollView",
  FlatList: TestFlatList,
  SidebarRow: "SidebarRow",
  SettingsSection: "SettingsSection",
  SettingsCard: "SettingsCard",
  SettingsRow: "SettingsRow",
  SettingsAction: "SettingsAction",
  SettingsSelect: "SettingsSelect",
  SettingsInput: function SettingsInput({ ref, initialValue = "", onChangeText, ...props }: SettingsInputProps) {
    const [text, setText] = useState(initialValue);
    useImperativeHandle(ref, () => ({
      getText: () => text,
      replaceText: setText,
      focus() {},
      blur() {},
    }), [text]);
    return createElement("SettingsInput", {
      ...props,
      value: text,
      onChangeText(value: string) {
        setText(value);
        onChangeText(value);
      },
    });
  },
  copyText: testHost.copyText,
  useToast: () => testHost.toast,
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
// Let async act drain query notifications without wall-clock sleeps or timer races.
notifyManager.setScheduler(queueMicrotask);
// The host is a client runtime, but Node has no `window`, which TanStack Query's server detection
// would read as "do not schedule polling timers". Model the client so refetch intervals exist.
environmentManager.setIsServer(() => false);

beforeEach(() => {
  vi.clearAllMocks();
  testListViewport.reset();
  testHost.copyText.mockReset().mockResolvedValue(undefined);
  testHost.settings = {
    status: "ready",
    values: { ...OBSERVER_DEFAULTS },
    revision: "revision-1",
    saving: false,
    saveError: null,
    save: vi.fn().mockResolvedValue(true),
    reset: vi.fn().mockResolvedValue(true),
    reload: vi.fn().mockResolvedValue(undefined),
  };
});
