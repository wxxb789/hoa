import type { PluginButtonIconProps, PluginClientContext } from "@getpaseo/plugin/client";
import { createElement, type ComponentType } from "react";
import { act, type ReactTestInstance } from "react-test-renderer";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import contribute from "../../index.client";
import type { FollowRunOutput, ListRunsUpdate, RunEvent, RunSummary } from "../../shared/runs";
import {
  hostProps,
  makeEvent,
  makeRun,
  makeScan,
  makeScanFacts,
  nodes,
  renderClient,
  textOf,
  type RenderedClient,
} from "./harness";

type Contribution = Parameters<PluginClientContext["addComposerPill"]>[0];
type Agent = { id: string; workspaceId?: string };
type DirectoryUpdate = { kind: "upsert"; agent: Agent } | { kind: "remove"; agentId: string };

const parent = { id: "parent", workspaceId: "workspace" };
const sibling = { id: "sibling", workspaceId: "workspace" };
const lineage = { goal: "Observer rollout", stage: "Implement", parentAgentId: parent.id };
const live = makeRun({ id: "live", name: "Linked worker", lineage, elapsedS: 45 });
const liveB = makeRun({ id: "live-b", name: "Second worker", lineage: { ...lineage, stage: "Review" }, elapsedS: 120 });
const stale = makeRun({ id: "stale", name: "Stale worker", state: "running", liveness: "stale", lineage: { ...lineage, stage: "fix" }, elapsedS: 300 });
const done = makeRun({ ...live, finalized: true, state: "done", liveness: "settled", elapsedS: 260 });
const failed = makeRun({ id: "failed", name: "Failed worker", finalized: true, state: "failed", liveness: "settled", lineage, elapsedS: 200 });
const killed = makeRun({ id: "killed", name: "Killed worker", finalized: true, state: "killed", liveness: "settled", lineage, elapsedS: 200 });
const quietUnknown = makeRun({ id: "quiet-unknown", name: "Unknown worker", finalized: true, state: "unknown", liveness: "settled", lineage, elapsedS: 200 });
const unfinished = makeRun({ id: "unfinished", name: "Unfinished worker", state: "running", liveness: "unknown", finalized: false, lineage, elapsedS: 30 });
const untracked = makeRun({ id: "untracked", sessionId: parent.id, finalized: true, state: "done", liveness: "settled" });

interface TestInstallation {
  addSettingsScreen: Mock<PluginClientContext["addSettingsScreen"]>;
  cleanup: () => void;
  list: Mock<(options: { subscribe?: {}; page?: { cursor?: string }; signal: AbortSignal }) => Promise<unknown>>;
  removed: Mock;
  openScreen: Mock;
  registered: Map<string, Contribution>;
  response: Mock<() => Promise<ListRunsUpdate>>;
  rpc: Mock<(method: unknown, input: { knownRevision?: string }) => Promise<ListRunsUpdate>>;
  stopListening: Mock;
  update: (payload: DirectoryUpdate) => void;
  snapshot: (agents: Agent[], pageInfo?: { hasMore: boolean; nextCursor: string | null }) => void;
}

function installation(initial: ListRunsUpdate): TestInstallation {
  const registered = new Map<string, Contribution>();
  const removed = vi.fn();
  const openScreen = vi.fn();
  const addSettingsScreen = vi.fn<PluginClientContext["addSettingsScreen"]>(() => () => {});
  const stopListening = vi.fn();
  const response = vi.fn(async () => initial);
  const rpc = vi.fn((_method: unknown, _input: { knownRevision?: string }) => response());
  let directory!: {
    snapshot(value: { entries: { agent: Agent }[]; pageInfo?: { hasMore: boolean; nextCursor: string | null } }): void;
    update(value: unknown): void;
  };
  const list = vi.fn(async (options: { subscribe?: {}; page?: { cursor?: string }; signal: AbortSignal }): Promise<unknown> => ({
    subscription: {
      subscribe(observer: typeof directory) {
        directory = observer;
        if (!options.page?.cursor) {
          observer.snapshot({ entries: [parent, sibling, { id: "unassigned" }].map((agent) => ({ agent })) });
        }
        return stopListening;
      },
    },
  }));
  const cleanup = contribute({
    paseo: { agents: { list } }, rpc, openScreen,
    addSidebarFooterItem: () => () => {}, addScreen: () => () => {}, addSettingsScreen,
    addComposerPill(contribution: Contribution) {
      registered.set(contribution.agentId, contribution);
      return {
        update(patch: Partial<Contribution["button"]>) { Object.assign(contribution.button, patch); },
        remove() {
          registered.delete(contribution.agentId);
          removed(contribution);
        },
      };
    },
  } as unknown as PluginClientContext);
  return {
    addSettingsScreen, cleanup, list, removed, openScreen, registered, response, rpc, stopListening,
    update(payload: DirectoryUpdate) { directory.update({ type: "agent_update", payload }); },
    snapshot(agents: Agent[], pageInfo?: { hasMore: boolean; nextCursor: string | null }) {
      directory.snapshot({ entries: agents.map((agent) => ({ agent })), pageInfo });
    },
  };
}

const cleanups: (() => void)[] = [];
afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup();
  vi.useRealTimers();
});

async function install(scan: ListRunsUpdate): Promise<TestInstallation> {
  const host = installation(scan);
  cleanups.push(host.cleanup);
  await vi.advanceTimersByTimeAsync(0);
  return host;
}

function pillOf(host: TestInstallation, agentId = parent.id): Contribution {
  const pill = host.registered.get(agentId);
  if (pill === undefined) throw new Error(`No composer pill is registered for ${agentId}`);
  return pill;
}

function popoverContent(host: TestInstallation) {
  const behavior = pillOf(host).button.behavior;
  if (behavior.kind !== "popover") throw new Error("Expected the pill to open a popover");
  return behavior.Content;
}

function labelOf(view: RenderedClient, pill: Contribution, locale: "en" | "zh-CN"): string {
  const label = pill.button.label;
  if (label === undefined) throw new Error("The pill carries no label");
  return view.translations.resolve(label, locale);
}

function styleOf(node: ReactTestInstance): Record<string, unknown> {
  const style: unknown = node.props.style;
  const entries = Array.isArray(style) ? style : [style];
  return Object.assign({}, ...entries.filter((entry) => entry !== null && typeof entry === "object")) as Record<string, unknown>;
}

async function dotOf(pill: Contribution): Promise<{ frame: ReactTestInstance; dot: ReactTestInstance }> {
  const icon = pill.button.icon;
  expect(typeof icon).toBe("function");
  const view = await renderClient(
    createElement(icon as ComponentType<PluginButtonIconProps>, {
      ...hostProps,
      context: "agent",
      workspaceId: parent.workspaceId,
      agentId: parent.id,
      size: 16,
      color: "#ffffff",
    }),
  );
  const views = nodes(view.root, "View");
  expect(views.length).toBeGreaterThanOrEqual(2);
  return { frame: views[0], dot: views[1] };
}

async function installWith(runs: RunSummary[], revision: string) {
  const host = await install({ ...makeScan({ runs }), revision });
  const view = await renderClient(<></>);
  return { host, view, pill: pillOf(host) };
}

function followed(run: RunSummary, overrides: Partial<FollowRunOutput> = {}): FollowRunOutput {
  return { found: true, summary: run, events: [], answerTail: null, ...overrides };
}

function followHook(initial: Record<string, FollowRunOutput>) {
  const data = new Map(Object.entries(initial));
  const invoke = async (method: string, input: unknown): Promise<unknown> => {
    if (method !== "runs.follow") throw new Error(`Unexpected RPC: ${method}`);
    return data.get((input as { id: string }).id) ?? { found: false, summary: null, events: [], answerTail: null };
  };
  return { data, invoke };
}

function assistantEvents(prefix: string): RunEvent[] {
  return Array.from({ length: 8 }, (_, index) =>
    makeEvent({ type: "message_end", role: "assistant", detail: `event ${index + 1} ${prefix}` }),
  );
}

function nineLineAnswer(marker: string): string {
  return Array.from({ length: 9 }, (_, index) => index === 0
    ? `answer head ${marker}`
    : index === 8 ? `answer tail ${marker}` : `answer line ${index + 1} ${marker}`).join("\n");
}

function textContaining(view: RenderedClient, fragment: string): string | undefined {
  return nodes(view.root, "Text").map(textOf).find((text) => text.includes(fragment));
}

function pressableWithText(view: RenderedClient, text: string): ReactTestInstance {
  const node = nodes(view.root, "Pressable").find((candidate) => textOf(candidate) === text);
  if (node === undefined) throw new Error(`No Pressable reads exactly "${text}"`);
  return node;
}

function pressableContaining(view: RenderedClient, fragment: string): ReactTestInstance {
  const node = nodes(view.root, "Pressable").find((candidate) => textOf(candidate).includes(fragment));
  if (node === undefined) throw new Error(`No Pressable contains "${fragment}"`);
  return node;
}

describe("composer pill presentation", () => {
  it("hides the pill when no run is attributed to its agent", async () => {
    vi.useFakeTimers();
    const elsewhere = { ...live, lineage: { ...lineage, parentAgentId: sibling.id } };
    const host = await install({ ...makeScan({ runs: [untracked, elsewhere] }), revision: "z1" });
    const view = await renderClient(<></>);
    expect(pillOf(host).button.visible).toBe(false);
    expect(pillOf(host).button.label).toBeUndefined();
    expect(labelOf(view, pillOf(host, sibling.id), "en")).toBe("Implement · Observer rollout · 45s");
    const idle = await dotOf(pillOf(host));
    expect(styleOf(idle.dot).backgroundColor).toBe(hostProps.theme.colors.foregroundMuted);
  });

  it("labels a single active run with its stage, goal and compact elapsed", async () => {
    vi.useFakeTimers();
    const cases: Array<{ elapsedS: number | null; expected: string }> = [
      { elapsedS: 45, expected: "Implement · Observer rollout · 45s" },
      { elapsedS: 240, expected: "Implement · Observer rollout · 4m" },
      { elapsedS: 3600, expected: "Implement · Observer rollout · 1h" },
      { elapsedS: 3900, expected: "Implement · Observer rollout · 1h 5m" },
      { elapsedS: null, expected: "Implement · Observer rollout" },
    ];
    for (const { elapsedS, expected } of cases) {
      const run = makeRun({ id: "live", name: "Linked worker", lineage, elapsedS });
      const { view, pill } = await installWith([run], `single-${elapsedS}`);
      expect(labelOf(view, pill, "en"), `en label for elapsedS ${elapsedS}`).toBe(expected);
      expect(labelOf(view, pill, "zh-CN"), `zh label for elapsedS ${elapsedS}`).toBe(expected);
    }
  });

  it("aggregates multiple active runs and counts stale ones in both locales", async () => {
    vi.useFakeTimers();
    const running = await installWith([live, liveB], "multi-running");
    expect(labelOf(running.view, running.pill, "en")).toBe("GDD · 2 running");
    expect(labelOf(running.view, running.pill, "zh-CN")).toBe("GDD · 2 运行中");
    expect(styleOf((await dotOf(running.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusSuccess);

    const mixed = await installWith([live, liveB, stale], "multi-mixed");
    expect(labelOf(mixed.view, mixed.pill, "en")).toBe("GDD · 2 running · 1 stale");
    expect(labelOf(mixed.view, mixed.pill, "zh-CN")).toBe("GDD · 2 运行中 · 1 疑似失联");
    expect(styleOf((await dotOf(mixed.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusWarning);
  });

  it("names the latest stale, failed or killed run with its stage and goal", async () => {
    vi.useFakeTimers();
    const staleLatest = await installWith([stale, done], "latest-stale");
    expect(labelOf(staleLatest.view, staleLatest.pill, "en")).toBe("stale · Observer rollout");
    expect(labelOf(staleLatest.view, staleLatest.pill, "zh-CN")).toBe("疑似失联 · Observer rollout");
    expect(styleOf((await dotOf(staleLatest.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusWarning);

    const failedLatest = await installWith([failed, done], "latest-failed");
    expect(labelOf(failedLatest.view, failedLatest.pill, "en")).toBe("Implement failed · Observer rollout");
    expect(labelOf(failedLatest.view, failedLatest.pill, "zh-CN")).toBe("Implement 失败 · Observer rollout");
    expect(styleOf((await dotOf(failedLatest.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusDanger);

    const killedLatest = await installWith([killed, done], "latest-killed");
    expect(labelOf(killedLatest.view, killedLatest.pill, "en")).toBe("Implement killed · Observer rollout");
    expect(labelOf(killedLatest.view, killedLatest.pill, "zh-CN")).toBe("Implement 被终止 · Observer rollout");
    expect(styleOf((await dotOf(killedLatest.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusDanger);
  });

  it("keeps the latest settled goal quiet with a check, and an unknown quiet without one", async () => {
    vi.useFakeTimers();
    const latestDone = await installWith([done, failed], "quiet-done");
    expect(labelOf(latestDone.view, latestDone.pill, "en")).toBe("GDD · Observer rollout ✓");
    expect(labelOf(latestDone.view, latestDone.pill, "zh-CN")).toBe("GDD · Observer rollout ✓");
    expect(styleOf((await dotOf(latestDone.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.foregroundMuted);

    const latestUnknown = await installWith([quietUnknown], "quiet-unknown");
    expect(labelOf(latestUnknown.view, latestUnknown.pill, "en")).toBe("GDD · Observer rollout");
    expect(labelOf(latestUnknown.view, latestUnknown.pill, "zh-CN")).toBe("GDD · Observer rollout");
    expect(labelOf(latestUnknown.view, latestUnknown.pill, "en")).not.toContain("✓");
    expect(styleOf((await dotOf(latestUnknown.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.foregroundMuted);
  });

  it("treats an unfinalized running worker with unproven liveness as active with an attention dot", async () => {
    vi.useFakeTimers();
    const unknowns = await installWith([unfinished, { ...unfinished, id: "unfinished-2" }], "unknown-pair");
    expect(labelOf(unknowns.view, unknowns.pill, "en")).toBe("GDD · 2 running");
    expect(styleOf((await dotOf(unknowns.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusWarning);

    const withActive = await installWith([unfinished, live], "unknown-active");
    expect(labelOf(withActive.view, withActive.pill, "en")).toBe("GDD · 2 running");
    expect(styleOf((await dotOf(withActive.pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusWarning);
  });

  it("republishes a single active run when only its compact elapsed changes", async () => {
    vi.useFakeTimers();
    const ticking = (elapsedS: number) => makeRun({ id: "live", name: "Linked worker", lineage, elapsedS });
    const host = await install({ ...makeScan({ runs: [ticking(45)] }), revision: "elapsed-1" });
    const view = await renderClient(<></>);
    const pill = pillOf(host);
    expect(labelOf(view, pill, "en")).toBe("Implement · Observer rollout · 45s");
    expect(styleOf((await dotOf(pill)).dot).backgroundColor).toBe(hostProps.theme.colors.statusSuccess);

    host.response.mockResolvedValueOnce({ ...makeScan({ runs: [ticking(240)] }), revision: "elapsed-2" });
    await vi.advanceTimersByTimeAsync(5000);
    expect(host.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "elapsed-1" });
    expect(labelOf(view, pill, "en")).toBe("Implement · Observer rollout · 4m");
    expect(labelOf(view, pill, "zh-CN")).toBe("Implement · Observer rollout · 4m");
  });

  it("republishes quiet changes of goal name and of done to finalized unknown", async () => {
    vi.useFakeTimers();
    const worker = (goal: string, state: RunSummary["state"], id: string) =>
      makeRun({ id, name: `${goal} worker`, finalized: true, state, liveness: "settled", lineage: { ...lineage, goal } });
    const host = await install({ ...makeScan({ runs: [worker("Alpha", "done", "alpha")] }), revision: "quiet-1" });
    const view = await renderClient(<></>);
    const pill = pillOf(host);
    expect(labelOf(view, pill, "en")).toBe("GDD · Alpha ✓");

    host.response.mockResolvedValueOnce({ ...makeScan({ runs: [worker("Beta", "done", "beta")] }), revision: "quiet-2" });
    host.update({ kind: "upsert", agent: parent });
    await vi.advanceTimersByTimeAsync(5000);
    expect(host.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "quiet-1" });
    expect(labelOf(view, pill, "en")).toBe("GDD · Beta ✓");

    host.response.mockResolvedValueOnce({ ...makeScan({ runs: [worker("Beta", "unknown", "beta")] }), revision: "quiet-3" });
    host.update({ kind: "upsert", agent: parent });
    await vi.advanceTimersByTimeAsync(5000);
    expect(host.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "quiet-2" });
    expect(labelOf(view, pill, "en")).toBe("GDD · Beta");
    expect(styleOf((await dotOf(pill)).dot).backgroundColor).toBe(hostProps.theme.colors.foregroundMuted);
  });

  it("renders the pill icon as a centered 8px dot in the presentation tone color", async () => {
    vi.useFakeTimers();
    const cases: Array<{ name: string; runs: RunSummary[]; color: string }> = [
      { name: "active", runs: [live], color: hostProps.theme.colors.statusSuccess },
      { name: "stale", runs: [stale], color: hostProps.theme.colors.statusWarning },
      { name: "unknown unfinalized", runs: [unfinished], color: hostProps.theme.colors.statusWarning },
      { name: "failed", runs: [failed], color: hostProps.theme.colors.statusDanger },
      { name: "killed", runs: [killed], color: hostProps.theme.colors.statusDanger },
      { name: "done", runs: [done], color: hostProps.theme.colors.foregroundMuted },
      { name: "finalized unknown", runs: [quietUnknown], color: hostProps.theme.colors.foregroundMuted },
    ];
    for (const { name, runs, color } of cases) {
      const host = await install({ ...makeScan({ runs }), revision: `icon-${name}` });
      const { frame, dot } = await dotOf(pillOf(host));
      expect(styleOf(frame), `${name} icon frame`).toMatchObject({
        width: 16, height: 16, alignItems: "center", justifyContent: "center",
      });
      expect(styleOf(dot), `${name} icon dot`).toMatchObject({
        width: 8, height: 8, borderRadius: 4, backgroundColor: color,
      });
    }
  });
});

describe("host-scoped Composer Pills", () => {
  it("uses exact lineage, isolates identical agents by host, and only refreshes active or signaled hosts", async () => {
    vi.useFakeTimers();
    const a = installation({ ...makeScan({ runs: [live, stale] }), revision: "a1" });
    const b = installation({ ...makeScan({ runs: [untracked] }), revision: "b1" });
    cleanups.push(a.cleanup, b.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const aPill = a.registered.get(parent.id)!;
    expect(aPill).toMatchObject({ id: "gdd-workers", workspaceId: parent.workspaceId, button: { visible: true } });
    expect(typeof aPill.button.icon).toBe("function");
    expect(a.registered.get(sibling.id)?.button.visible).toBe(false);
    expect(a.registered.has("unassigned")).toBe(false);
    expect(b.registered.get(parent.id)?.button.visible).toBe(false);

    const view = await renderClient(<></>);
    expect(view.translations.resolve(aPill.button.title, "en")).toBe("GDD");
    expect(view.translations.resolve(aPill.button.label!, "en")).toBe("Implement · Observer rollout · 45s");
    expect(view.translations.resolve(aPill.button.label!, "zh-CN")).toBe("Implement · Observer rollout · 45s");
    const oneActive = await dotOf(aPill);
    expect(styleOf(oneActive.dot).backgroundColor).toBe(hostProps.theme.colors.statusWarning);

    a.response.mockResolvedValueOnce({ ...makeScanFacts(), revision: "a2", changes: [done], removed: [] });
    await vi.advanceTimersByTimeAsync(5000);
    expect(a.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "a1" });
    expect(view.translations.resolve(aPill.button.label!, "en")).toBe("GDD · Observer rollout ✓");
    const staleBehind = await dotOf(aPill);
    expect(styleOf(staleBehind.dot).backgroundColor).toBe(hostProps.theme.colors.foregroundMuted);
    await vi.advanceTimersByTimeAsync(24_000);
    expect(a.rpc).toHaveBeenCalledTimes(2);
    expect(b.rpc).toHaveBeenCalledTimes(1);

    b.response.mockResolvedValueOnce({ ...makeScanFacts(), revision: "b2", changes: [done], removed: [untracked.id], order: [done.id] });
    b.update({ kind: "upsert", agent: parent });
    b.update({ kind: "upsert", agent: sibling });
    await vi.advanceTimersByTimeAsync(1);
    expect(b.rpc).toHaveBeenCalledTimes(2);
    expect(b.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "b1" });
    expect(view.translations.resolve(b.registered.get(parent.id)!.button.label!, "en")).toBe("GDD · Observer rollout ✓");
    expect(b.registered.get(sibling.id)?.button.visible).toBe(false);
    expect(a.rpc).toHaveBeenCalledTimes(2);

    b.update({ kind: "upsert", agent: { ...parent, workspaceId: "moved" } });
    expect(b.removed).toHaveBeenCalledTimes(1);
    expect(b.registered.get(parent.id)?.workspaceId).toBe("moved");
    b.update({ kind: "remove", agentId: parent.id });
    expect(b.registered.has(parent.id)).toBe(false);
    b.snapshot([parent]);
    expect([...b.registered.keys()]).toEqual([parent.id]);
    b.cleanup();
    expect(b.list.mock.calls[0][0].signal.aborted).toBe(true);
    expect(b.stopListening).toHaveBeenCalledOnce();
    expect(b.registered.size).toBe(0);
    await vi.advanceTimersByTimeAsync(6000);
    expect(b.rpc).toHaveBeenCalledTimes(2);
  });

  it("refreshes the pill and shared list after a root save during an older scan", async () => {
    vi.useFakeTimers();
    const old = { ...makeScan({ runs: [done] }), revision: "old" };
    const host = installation(old);
    cleanups.push(host.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    let finishOldScan!: (value: ListRunsUpdate) => void;
    host.response.mockReturnValueOnce(new Promise((resolve) => { finishOldScan = resolve; }));
    const fresh = { ...makeScan({ runRoot: "/fixture/runs/new" }), revision: "new" };
    host.response.mockResolvedValueOnce(fresh);
    const Screen = host.addSettingsScreen.mock.calls[0][0].Component;
    const view = await renderClient(<Screen {...hostProps} />, { pending: true });
    expect(host.rpc).toHaveBeenCalledTimes(2);
    expect(host.registered.get(parent.id)?.button.visible).toBe(true);

    await view.change(() => nodes(view.root, "SettingsInput")[0].props.onChangeText(fresh.runRoot));
    await view.change(() => nodes(view.root, "SettingsAction")[0].props.onPress());
    expect(host.rpc).toHaveBeenCalledTimes(2);
    await view.change(() => finishOldScan(old));
    expect(host.rpc).toHaveBeenCalledTimes(3);
    expect(host.registered.get(parent.id)?.button.visible).toBe(false);
    expect(view.query.getQueryData(["gddRuns", "list"])).toMatchObject({ runRoot: fresh.runRoot, runs: [] });
  });

  it("paginates active agents beyond page 1 while preserving live remove/upsert deltas", async () => {
    vi.useFakeTimers();
    const tailParent = { id: "agent-201", workspaceId: "workspace" };
    const removedMidFlight = { id: "agent-202", workspaceId: "workspace" };
    const tailRun = makeRun({ id: "tail-run", lineage: { goal: "Observer rollout", stage: "Review", parentAgentId: tailParent.id } });
    const host = installation({ ...makeScan({ runs: [tailRun] }), revision: "p1" });
    cleanups.push(host.cleanup);
    await vi.advanceTimersByTimeAsync(0);

    let resolvePage2!: (value: unknown) => void;
    host.list.mockReturnValueOnce(new Promise((resolve) => { resolvePage2 = resolve; }));
    host.snapshot([parent], { hasMore: true, nextCursor: "cursor-2" });
    host.update({ kind: "remove", agentId: removedMidFlight.id });
    resolvePage2({
      entries: [{ agent: tailParent }, { agent: removedMidFlight }],
      pageInfo: { hasMore: false, nextCursor: null },
    });
    await vi.advanceTimersByTimeAsync(0);

    expect(host.registered.get(tailParent.id)?.button.visible).toBe(true);
    expect(host.registered.has(removedMidFlight.id)).toBe(false);
    expect(host.registered.has(sibling.id)).toBe(false);
  });
});

describe("composer pill popover", () => {
  it("groups goals, swaps them for an inline peek, and keeps the popover open behind Back", async () => {
    vi.useFakeTimers();
    const a = installation({ ...makeScan({ runs: [stale, done] }), revision: "p1" });
    const b = installation({ ...makeScan({ runs: [done] }), revision: "b1" });
    cleanups.push(a.cleanup, b.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const Content = popoverContent(a);
    const close = vi.fn();
    const { invoke } = followHook({
      [stale.id]: followed(stale, {
        events: [makeEvent({ type: "message_end", role: "assistant", detail: "已检查运行目录" })],
        answerTail: "首轮回答",
      }),
    });
    const view = await renderClient(
      <Content {...hostProps} host={{ id: "host-a", label: "Host A" }} layout={{ compact: true, platform: "ios" }}
        context="agent" workspaceId={parent.workspaceId} agentId={parent.id} close={close} />,
      { locale: "zh-CN", pending: true, invoke },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(view.texts()).toEqual(expect.arrayContaining(["Host A · 1 个目标", "查看全部", "最近目标", "Implement → fix ◌"]));
    expect(view.invoke).not.toHaveBeenCalledWith("runs.follow", expect.anything());
    expect(b.openScreen).not.toHaveBeenCalled();

    await view.change(() => pressableContaining(view, "→").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(close).not.toHaveBeenCalled();
    expect(view.texts()).toEqual(expect.arrayContaining([
      "返回", "完整视图", "最新活动", "回答预览", "该运行未正常收尾，疑似已失联。", "已检查运行目录", "首轮回答",
    ]));
    const staleMeta = textContaining(view, "5m");
    expect(staleMeta).toBeDefined();
    expect(staleMeta).toContain("疑似失联");
    expect(view.invoke).toHaveBeenCalledWith("runs.follow", { id: stale.id, tailLines: 12 });
    expect(view.query.getQueryData(["gddRuns", "follow", stale.id, 12, stale.runDir])).toMatchObject({ found: true });
    expect(close).not.toHaveBeenCalled();

    await view.change(() => pressableWithText(view, "返回").props.onPress());
    expect(view.texts()).toContain("最近目标");
    expect(view.texts()).not.toContain("回答预览");
    expect(close).not.toHaveBeenCalled();

    await view.change(() => pressableContaining(view, "→").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await view.change(() => pressableWithText(view, "完整视图").props.onPress());
    expect(close).toHaveBeenCalledOnce();
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id, runId: stale.id } });
    expect(close.mock.invocationCallOrder[0]).toBeLessThan(a.openScreen.mock.invocationCallOrder[0]);

    await view.change(() => pressableWithText(view, "返回").props.onPress());
    await view.change(() => pressableWithText(view, "查看全部").props.onPress());
    expect(close).toHaveBeenCalledTimes(2);
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id } });
    expect(close.mock.invocationCallOrder[1]).toBeLessThan(a.openScreen.mock.invocationCallOrder[1]);
    expect(b.openScreen).not.toHaveBeenCalled();

    const scansBeforeUnmount = a.rpc.mock.calls.length;
    await view.update(<></>);
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(a.rpc.mock.calls.length).toBe(scansBeforeUnmount);
    expect(b.rpc).toHaveBeenCalledTimes(1);
  });

  it("streams the peek's follow hook, switches siblings without history, and opens the exact host", async () => {
    vi.useFakeTimers();
    const a = installation({ ...makeScan({ runs: [stale, done] }), revision: "p1" });
    const b = installation({ ...makeScan({ runs: [stale, done] }), revision: "b1" });
    cleanups.push(a.cleanup, b.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const Content = popoverContent(a);
    const close = vi.fn();
    const longAnswer = "x".repeat(500) + "TAIL";
    const { data, invoke } = followHook({
      [stale.id]: followed(stale, { events: assistantEvents("stale"), answerTail: nineLineAnswer("stale") }),
      [done.id]: followed(done, {
        events: [makeEvent({ type: "message_end", role: "assistant", detail: "done event" })],
        answerTail: longAnswer,
      }),
    });
    const view = await renderClient(
      <Content {...hostProps} host={{ id: "host-a", label: "Host A" }} layout={{ compact: true, platform: "ios" }}
        context="agent" workspaceId={parent.workspaceId} agentId={parent.id} close={close} />,
      { pending: true, invoke },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(view.texts()).toEqual(expect.arrayContaining(["Host A · 1 goal", "All runs ↗", "Recent goals", "Implement → fix ◌"]));
    expect(view.query.getQueryData(["gddRuns", "list"])).toMatchObject({ revision: "p1" });

    await view.change(() => pressableContaining(view, "→").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(close).not.toHaveBeenCalled();
    expect(view.texts()).toEqual(expect.arrayContaining([
      "← Back", "Full view ↗", "Latest activity", "Answer preview",
      "Worker stopped reporting before finalizing.", "waiting for counters",
    ]));
    expect(view.texts()).toEqual(expect.arrayContaining(["event 3 stale", "event 8 stale"]));
    expect(view.texts()).not.toContain("event 2 stale");
    const answer = textContaining(view, "answer tail stale");
    expect(answer).toBeDefined();
    expect(answer).not.toContain("answer head stale");
    expect(view.invoke).toHaveBeenLastCalledWith("runs.follow", { id: stale.id, tailLines: 12 });
    expect(view.query.getQueryData(["gddRuns", "list"])).toMatchObject({ revision: "p1" });

    data.set(stale.id, followed(stale, {
      events: [
        makeEvent({ type: "message_end", role: "assistant", detail: "event fresh" }),
        makeEvent({ type: "tool_use", role: null, tool: "Bash", intent: "run tests" }),
      ],
      answerTail: "fresh answer",
    }));
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(view.texts()).toEqual(expect.arrayContaining(["event fresh", "Bash", "run tests", "fresh answer"]));
    expect(view.texts()).not.toContain("event 8 stale");
    expect(textContaining(view, "answer tail stale")).toBeUndefined();

    await view.change(() => pressableWithText(view, "Implement").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.invoke).toHaveBeenLastCalledWith("runs.follow", { id: done.id, tailLines: 12 });
    expect(view.texts()).toContain("done event");
    const clamped = nodes(view.root, "Text").map(textOf).find((text) => text.endsWith("TAIL"));
    expect(clamped).toBe("x".repeat(396) + "TAIL");
    expect(view.texts()).not.toContain("fresh answer");
    expect(close).not.toHaveBeenCalled();

    const active = makeRun({ id: "active", name: "Active worker", lineage: { ...lineage, stage: "Review" }, elapsedS: 120, currentTool: "Read", currentToolIntent: "checking notes" });
    data.set(active.id, followed(active, { events: [], answerTail: null }));
    a.response.mockResolvedValue({ ...makeScan({ runs: [active, stale, done] }), revision: "p2" });
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(view.texts()).toContain("Review");

    await view.change(() => pressableWithText(view, "← Back").props.onPress());
    expect(view.texts()).toEqual(expect.arrayContaining(["Host A · 1 running", "All runs ↗"]));
    expect(textContaining(view, "Read · checking notes")).toBeDefined();
    expect(view.texts()).toContain("Worker stopped reporting before finalizing.");
    expect(close).not.toHaveBeenCalled();

    await view.change(() => pressableContaining(view, "Read · checking notes").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.invoke).toHaveBeenLastCalledWith("runs.follow", { id: active.id, tailLines: 12 });
    expect(view.texts()).toEqual(expect.arrayContaining(["← Back", "Full view ↗"]));
    const activeMeta = textContaining(view, "2m");
    expect(activeMeta).toBeDefined();
    expect(activeMeta).toContain("Review");
    expect(activeMeta).toContain("running");
    expect(close).not.toHaveBeenCalled();

    close.mockClear();
    a.openScreen.mockClear();
    await view.change(() => pressableWithText(view, "Full view ↗").props.onPress());
    expect(close).toHaveBeenCalledOnce();
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id, runId: active.id } });
    expect(close.mock.invocationCallOrder[0]).toBeLessThan(a.openScreen.mock.invocationCallOrder[0]);
    expect(b.openScreen).not.toHaveBeenCalled();

    await view.change(() => pressableWithText(view, "← Back").props.onPress());
    const followCalls = view.invoke.mock.calls.filter(([method]) => method === "runs.follow").length;
    await view.change(() => pressableWithText(view, "All runs ↗").props.onPress());
    expect(close).toHaveBeenCalledTimes(2);
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id } });
    expect(b.openScreen).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(4200); });
    expect(view.invoke.mock.calls.filter(([method]) => method === "runs.follow").length).toBe(followCalls);

    const ghost = makeRun({ id: "ghost", name: "Ghost worker", lineage, currentTool: "Bash", currentToolIntent: "ghost probe" });
    a.response.mockResolvedValue({ ...makeScan({ runs: [ghost, active, stale, done] }), revision: "p3" });
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    await view.change(() => pressableContaining(view, "ghost probe").props.onPress());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.invoke).toHaveBeenLastCalledWith("runs.follow", { id: ghost.id, tailLines: 12 });
    expect(view.texts()).toContain("This run is no longer on disk.");
    expect(view.texts()).not.toContain("Answer preview");
  });

  it("caps the hero at four workers and counts every active run", async () => {
    vi.useFakeTimers();
    const actives = Array.from({ length: 5 }, (_, index) => makeRun({
      id: `active-${index}`,
      name: `Worker ${index}`,
      lineage: { ...lineage, stage: `S${index}` },
      elapsedS: 60,
      currentTool: "Read",
      currentToolIntent: `intent ${index}`,
    }));
    const a = installation({ ...makeScan({ runs: actives }), revision: "hero-1" });
    cleanups.push(a.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const Content = popoverContent(a);
    const view = await renderClient(
      <Content {...hostProps} host={{ id: "host-a", label: "Host A" }} layout={{ compact: true, platform: "ios" }}
        context="agent" workspaceId={parent.workspaceId} agentId={parent.id} close={vi.fn()} />,
      { pending: true },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(view.texts()).toContain("Host A · 5 running");
    expect(textContaining(view, "intent 0")).toBeDefined();
    expect(textContaining(view, "intent 3")).toBeDefined();
    expect(textContaining(view, "intent 4")).toBeUndefined();
  });

  it("bounds a large scan to six goal rows and collapses consecutive stages", async () => {
    vi.useFakeTimers();
    const goalRun = (id: string, goal: string, stage: string) => makeRun({
      id, name: id, finalized: true, state: "done", liveness: "settled",
      lineage: { goal, stage, parentAgentId: parent.id }, durationS: 30,
    });
    const fixes = Array.from({ length: 15 }, (_, index) => goalRun(`fix-${15 - index}`, "Observer rollout", "fix"));
    const observer = [...fixes, goalRun("implement", "Observer rollout", "Implement"), goalRun("plan", "Observer rollout", "Plan")];
    const others = [2, 3, 4, 5, 6, 7].flatMap((goal) =>
      Array.from({ length: 6 }, (_, run) => goalRun(`g${goal}-${run}`, `Goal G${goal}`, "Plan")));
    const runs = [...observer, ...others];
    expect(runs).toHaveLength(53);
    const a = installation({ ...makeScan({ runs }), revision: "scale-1" });
    cleanups.push(a.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const Content = popoverContent(a);
    const view = await renderClient(
      <Content {...hostProps} host={{ id: "host-a", label: "Host A" }} layout={{ compact: true, platform: "ios" }}
        context="agent" workspaceId={parent.workspaceId} agentId={parent.id} close={vi.fn()} />,
      { pending: true },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(view.texts()).toEqual(expect.arrayContaining([
      "Plan → Implement → fix×15 ✓", "View all 7 goals in GDD runs",
    ]));
    const groupTexts = nodes(view.root, "Pressable").map(textOf).filter((text) => text.startsWith("Goal G"));
    expect(groupTexts).toHaveLength(5);
    expect(groupTexts.some((text) => text.startsWith("Goal G7"))).toBe(false);
    const cachedList = view.query.getQueryData<{ runs: RunSummary[] }>(["gddRuns", "list"]);
    expect(cachedList?.runs).toHaveLength(53);
  });
});
