import type {
  PluginButtonContentProps,
  PluginButtonRegistration,
  PluginClientContext,
  PluginText,
} from "@getpaseo/plugin/client";
import type { QueryClient } from "@tanstack/react-query";
import { listRuns, type RunSummary } from "../shared/runs";
import { AgentRunsPopover } from "./agent-runs-popover";
import { composerPresentation, idleStatusIcon, isActive } from "./composer-presentation";
import { messages } from "./messages";
import {
  applyListDelta,
  type CachedList,
  RUNS_LIST_QUERY_KEY,
  RunsListControllerContext,
} from "./use-runs-query";

const MIN_BACKGROUND_INTERVAL_MS = 3000;
const DEFAULT_BACKGROUND_INTERVAL_MS = 5000;
const AGENT_PAGE_LIMIT = 200;

type Agent = { id: string; workspaceId?: string };
interface AgentListPage {
  entries: readonly { agent: Agent }[];
  pageInfo?: { hasMore?: boolean; nextCursor?: string | null };
}
type Pill = {
  workspaceId: string;
  registration: PluginButtonRegistration<PluginText>;
  presentation: string;
};

export class ComposerPillManager {
  readonly #lifetime = new AbortController();
  readonly #pills = new Map<string, Pill>();
  readonly #runsByParent = new Map<string, RunSummary[]>();
  #unlisten?: () => void;
  #scan?: CachedList;
  #inFlight?: Promise<CachedList>;
  #timer?: ReturnType<typeof setTimeout>;
  #lastScanAt = 0;
  #intervalMs = DEFAULT_BACKGROUND_INTERVAL_MS;
  #observers = 0;
  #hasActiveRuns = false;
  #needsScan = false;
  #snapshotSeq = 0;
  readonly #queryClients = new Map<QueryClient, number>();

  constructor(private readonly client: PluginClientContext) {
    void this.refresh().catch(() => {});
    void this.#listen();
  }

  refresh(): Promise<CachedList> {
    if (this.#inFlight) return this.#inFlight;
    if (this.#lifetime.signal.aborted) return Promise.reject(new Error("GDD observer installation is closed"));
    this.#clearTimer();
    this.#lastScanAt = Date.now();
    this.#needsScan = false;
    const base = this.#scan;
    this.#inFlight = this.client.rpc(listRuns, base?.revision === undefined ? {} : { knownRevision: base.revision })
      .then((update) => {
        let scan: CachedList;
        if ("runs" in update) scan = update;
        else if (base?.revision !== undefined) scan = applyListDelta(base, update);
        else {
          throw new Error("runs.list answered a request without a known revision with a delta");
        }
        if (!this.#lifetime.signal.aborted) this.#acceptScan(scan);
        return scan;
      })
      .finally(() => {
        this.#inFlight = undefined;
        this.#schedule();
      });
    return this.#inFlight;
  }

  async reload(): Promise<CachedList> {
    await this.#inFlight?.catch(() => {});
    return this.refresh();
  }

  observe(intervalMs: number): () => void {
    this.#intervalMs = intervalMs;
    this.#observers += 1;
    this.#clearTimer();
    return () => {
      this.#observers -= 1;
      this.#schedule();
    };
  }

  bindQueryClient(queryClient: QueryClient): () => void {
    this.#queryClients.set(queryClient, (this.#queryClients.get(queryClient) ?? 0) + 1);
    return () => {
      const remaining = (this.#queryClients.get(queryClient) ?? 1) - 1;
      if (remaining <= 0) this.#queryClients.delete(queryClient);
      else this.#queryClients.set(queryClient, remaining);
    };
  }

  dispose(): void {
    if (this.#lifetime.signal.aborted) return;
    this.#lifetime.abort();
    this.#unlisten?.();
    this.#clearTimer();
    for (const pill of this.#pills.values()) pill.registration.remove();
    this.#pills.clear();
    this.#runsByParent.clear();
    this.#queryClients.clear();
    this.#scan = undefined;
  }

  async #listen(): Promise<void> {
    try {
      const { subscription } = await this.client.paseo.agents.list({
        scope: "active",
        page: { limit: AGENT_PAGE_LIMIT },
        subscribe: {},
        signal: this.#lifetime.signal,
      });
      if (this.#lifetime.signal.aborted) return;
      let firstSnapshot = true;
      let activePresent: Set<string> | null = null;
      let activeRemoved: Set<string> | null = null;
      this.#unlisten = subscription.subscribe({
        snapshot: ({ entries, pageInfo }) => {
          const seq = ++this.#snapshotSeq;
          const present = new Set<string>();
          for (const { agent } of entries) {
            present.add(agent.id);
            this.#upsert(agent);
          }
          if (pageInfo?.hasMore && pageInfo.nextCursor) {
            const removed = new Set<string>();
            activePresent = present;
            activeRemoved = removed;
            void this.#loadRemainingPages(seq, pageInfo.nextCursor, present, removed).finally(() => {
              if (this.#snapshotSeq === seq) {
                activePresent = null;
                activeRemoved = null;
              }
            });
          } else {
            activePresent = null;
            activeRemoved = null;
            for (const id of this.#pills.keys()) if (!present.has(id)) this.#remove(id);
          }
          if (!firstSnapshot || (!this.#scan && !this.#inFlight)) this.#onAgentActivity();
          firstSnapshot = false;
        },
        update: (message) => {
          if (message.type !== "agent_update") return;
          const update = message.payload;
          if (update.kind === "remove") {
            activePresent?.delete(update.agentId);
            activeRemoved?.add(update.agentId);
            this.#remove(update.agentId);
          } else {
            activeRemoved?.delete(update.agent.id);
            activePresent?.add(update.agent.id);
            this.#upsert(update.agent);
          }
          this.#onAgentActivity();
        },
      });
    } catch {
      // The subscription can reject when the installation is removed before the first snapshot.
    }
  }

  async #loadRemainingPages(
    seq: number,
    nextCursor: string,
    present: Set<string>,
    removed: Set<string>,
  ): Promise<void> {
    let cursor: string | null = nextCursor;
    try {
      while (cursor && !this.#lifetime.signal.aborted && this.#snapshotSeq === seq) {
        const response: AgentListPage = await this.client.paseo.agents.list({
          scope: "active",
          page: { limit: AGENT_PAGE_LIMIT, cursor },
          signal: this.#lifetime.signal,
        });
        if (this.#lifetime.signal.aborted || this.#snapshotSeq !== seq) return;
        for (const { agent } of response.entries) {
          if (removed.has(agent.id)) continue;
          present.add(agent.id);
          this.#upsert(agent);
        }
        cursor = response.pageInfo?.hasMore ? (response.pageInfo.nextCursor ?? null) : null;
      }
      if (!this.#lifetime.signal.aborted && this.#snapshotSeq === seq) {
        for (const id of this.#pills.keys()) if (!present.has(id)) this.#remove(id);
      }
    } catch {
      // Reconnect or disposal supersedes in-flight cursor pagination.
    }
  }

  #onAgentActivity(): void {
    this.#needsScan = true;
    this.#schedule();
  }

  #schedule(): void {
    if (this.#lifetime.signal.aborted || this.#observers > 0 || this.#timer !== undefined ||
        this.#inFlight || (!this.#needsScan && !this.#hasActiveRuns)) return;
    const interval = Math.max(MIN_BACKGROUND_INTERVAL_MS, this.#intervalMs);
    this.#timer = setTimeout(() => {
      this.#timer = undefined;
      void this.refresh().catch(() => {});
    }, Math.max(0, this.#lastScanAt + interval - Date.now()));
  }

  #clearTimer(): void {
    if (this.#timer === undefined) return;
    clearTimeout(this.#timer);
    this.#timer = undefined;
  }

  #acceptScan(scan: CachedList): void {
    const previous = this.#scan?.runs;
    this.#scan = scan;
    for (const queryClient of this.#queryClients.keys()) {
      queryClient.setQueryData(RUNS_LIST_QUERY_KEY, scan);
    }
    if (scan.runs === previous) return;
    this.#runsByParent.clear();
    this.#hasActiveRuns = false;
    for (const run of scan.runs) {
      if (isActive(run)) this.#hasActiveRuns = true;
      const id = run.lineage?.parentAgentId;
      if (id === undefined) continue;
      const siblings = this.#runsByParent.get(id);
      if (siblings === undefined) this.#runsByParent.set(id, [run]);
      else siblings.push(run);
    }
    for (const [id, pill] of this.#pills) this.#present(id, pill);
  }

  #upsert({ id, workspaceId }: Agent): void {
    if (this.#pills.get(id)?.workspaceId === workspaceId) return;
    this.#remove(id);
    if (!workspaceId) return;
    const client = this.client;
    const Content = (props: PluginButtonContentProps) => props.context === "agent" ? (
      <RunsListControllerContext.Provider value={this}>
        <AgentRunsPopover {...props} openScreen={(input) => client.openScreen(input)} />
      </RunsListControllerContext.Provider>
    ) : null;
    const registration = client.addComposerPill({
      id: "gdd-workers", workspaceId, agentId: id,
      button: {
        title: messages.message("composer.sheetTitle"),
        icon: idleStatusIcon, visible: false, behavior: { kind: "popover", Content },
      },
    });
    const pill = { workspaceId, registration, presentation: "" };
    this.#pills.set(id, pill);
    this.#present(id, pill);
  }

  #remove(id: string): void {
    this.#pills.get(id)?.registration.remove();
    this.#pills.delete(id);
  }

  #present(id: string, pill: Pill): void {
    const runs = this.#runsByParent.get(id);
    if (!runs) {
      if (pill.presentation !== "") pill.registration.update({ visible: false });
      pill.presentation = "";
      return;
    }
    const { label, icon, key } = composerPresentation(runs);
    if (pill.presentation === key) return;
    pill.presentation = key;
    pill.registration.update({ visible: true, icon, label });
  }
}
