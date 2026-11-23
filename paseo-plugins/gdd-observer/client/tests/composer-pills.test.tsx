import type { PluginClientContext } from "@getpaseo/plugin/client";
import { act } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import contribute from "../../index.client";
import type { ListRunsUpdate } from "../../shared/runs";
import { hostProps, makeRun, makeScan, makeScanFacts, nodes, renderClient, textOf } from "./harness";

type Contribution = Parameters<PluginClientContext["addComposerPill"]>[0];
type Agent = { id: string; workspaceId?: string };
type DirectoryUpdate = { kind: "upsert"; agent: Agent } | { kind: "remove"; agentId: string };

const parent = { id: "parent", workspaceId: "workspace" };
const sibling = { id: "sibling", workspaceId: "workspace" };
const lineage = { goal: "Observer rollout", stage: "Implement", parentAgentId: parent.id };
const live = makeRun({ id: "live", name: "Linked worker", lineage });
const stale = makeRun({ id: "stale", state: "running", liveness: "stale", lineage });
const done = { ...live, finalized: true, state: "done", liveness: "settled" } as const;
const untracked = makeRun({ id: "untracked", sessionId: parent.id, finalized: true, state: "done", liveness: "settled" });

function installation(initial: ListRunsUpdate) {
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

describe("host-scoped Composer Pills", () => {
  it("uses exact lineage, isolates identical agents by host, and only refreshes active or signaled hosts", async () => {
    vi.useFakeTimers();
    const a = installation({ ...makeScan({ runs: [live, stale] }), revision: "a1" });
    const b = installation({ ...makeScan({ runs: [untracked] }), revision: "b1" });
    cleanups.push(a.cleanup, b.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const aPill = a.registered.get(parent.id)!;
    expect(aPill).toMatchObject({ id: "gdd-workers", workspaceId: parent.workspaceId, button: { visible: true, icon: "Activity" } });
    expect(a.registered.get(sibling.id)?.button.visible).toBe(false);
    expect(a.registered.has("unassigned")).toBe(false);
    expect(b.registered.get(parent.id)?.button.visible).toBe(false);

    const view = await renderClient(<></>);
    expect(view.translations.resolve(aPill.button.label!, "en")).toBe("GDD · 1 running · 1 stale");
    expect(view.translations.resolve(aPill.button.label!, "zh-CN")).toBe("GDD · 1 运行中 · 1 疑似失联");

    a.response.mockResolvedValueOnce({ ...makeScanFacts(), revision: "a2", changes: [done], removed: [] });
    await vi.advanceTimersByTimeAsync(5000);
    expect(a.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "a1" });
    expect(view.translations.resolve(aPill.button.label!, "en")).toBe("GDD · 1 stale");
    await vi.advanceTimersByTimeAsync(24_000);
    expect(a.rpc).toHaveBeenCalledTimes(2);
    expect(b.rpc).toHaveBeenCalledTimes(1);

    b.response.mockResolvedValueOnce({ ...makeScanFacts(), revision: "b2", changes: [done], removed: [untracked.id], order: [done.id] });
    b.update({ kind: "upsert", agent: parent });
    b.update({ kind: "upsert", agent: sibling });
    await vi.advanceTimersByTimeAsync(1);
    expect(b.rpc).toHaveBeenCalledTimes(2);
    expect(b.rpc).toHaveBeenLastCalledWith(expect.anything(), { knownRevision: "b1" });
    expect(view.translations.resolve(b.registered.get(parent.id)!.button.label!, "en")).toBe("GDD · 1 done");
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

  it("keeps a compact popover current and opens only its installation's screen", async () => {
    vi.useFakeTimers();
    const peer = { ...done, id: "peer", name: "Sibling worker", lineage: { ...lineage, parentAgentId: sibling.id } };
    const a = installation({ ...makeScan({ runs: [done, peer] }), revision: "a1" });
    const b = installation({ ...makeScan(), revision: "b1" });
    cleanups.push(a.cleanup, b.cleanup);
    await vi.advanceTimersByTimeAsync(0);
    const behavior = a.registered.get(parent.id)!.button.behavior;
    if (behavior.kind !== "popover") throw new Error("Expected a popover");
    const close = vi.fn();
    const aHost = { id: "host-a", label: "Host A" };
    const Content = behavior.Content;
    const view = await renderClient(<Content {...hostProps} host={aHost} layout={{ compact: true, platform: "ios" }}
      context="agent" workspaceId={parent.workspaceId} agentId={parent.id} close={close} />, {
      locale: "zh-CN", pending: true,
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(view.texts()).toEqual(expect.arrayContaining(["Host A · GDD 运行（1）", "Observer rollout · Implement", done.name]));
    expect(view.texts()).not.toContain(peer.name);
    expect(view.query.getQueryData(["gddRuns", "list"])).toMatchObject({ runs: [done, peer] });
    expect(a.rpc).toHaveBeenCalledTimes(2);

    a.response.mockResolvedValueOnce({ ...makeScanFacts(), revision: "a2", changes: [{ ...done, name: "Final worker" }], removed: [] });
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(view.texts()).toContain("Final worker");
    expect(a.rpc).toHaveBeenCalledTimes(3);

    const row = nodes(view.root, "Pressable").find((node) => String(node.props.accessibilityLabel).includes("Final worker"))!;
    await view.change(() => row.props.onPress());
    expect(close).toHaveBeenCalledOnce();
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id, runId: done.id } });
    expect(close.mock.invocationCallOrder[0]).toBeLessThan(a.openScreen.mock.invocationCallOrder[0]);
    const footer = nodes(view.root, "Pressable").find((node) => textOf(node) === "在 GDD 运行中打开")!;
    await view.change(() => footer.props.onPress());
    expect(a.openScreen).toHaveBeenLastCalledWith({ screenId: "runs", params: { parentAgentId: parent.id } });
    expect(b.openScreen).not.toHaveBeenCalled();

    await view.update(<></>);
    await vi.advanceTimersByTimeAsync(8000);
    expect(a.rpc).toHaveBeenCalledTimes(3);
    expect(b.rpc).toHaveBeenCalledTimes(1);
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
