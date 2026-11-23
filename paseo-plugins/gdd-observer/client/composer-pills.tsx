import type {
  PluginButtonContentProps,
  PluginButtonRegistration,
  PluginClientContext,
  PluginText,
} from "@getpaseo/plugin/client";
import { useSettings, useTranslation } from "@getpaseo/plugin/client";
import type { QueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { Pressable, Text, View } from "react-native";
import { listRuns, type RunSummary } from "../shared/runs";
import { OBSERVER_DEFAULTS, observerSettings } from "../shared/settings";
import { summarizeRuns } from "../shared/stats";
import { errorText } from "./format";
import { messages } from "./messages";
import { RunRow } from "./runs-browser";
import { StatusStrip } from "./status-strip";
import { useObserverStyles } from "./styles";
import {
  applyListDelta,
  type CachedList,
  RUNS_LIST_QUERY_KEY,
  RunsListControllerContext,
  useRunsListQuery,
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
        title: messages.message("composer.title", { count: 0 }),
        icon: "Activity", visible: false, behavior: { kind: "popover", Content },
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
    const count = runs.length;
    let active = 0;
    let stale = 0;
    let failed = 0;
    let done = 0;
    for (const run of runs) {
      if (isActive(run)) active += 1;
      if (run.liveness === "stale") stale += 1;
      if (run.state === "failed") failed += 1;
      if (run.state === "done") done += 1;
    }
    const presentation = `${count}/${active}/${stale}/${failed}/${done}`;
    if (pill.presentation === presentation) return;
    pill.presentation = presentation;
    const key = active > 0
      ? stale > 0 ? "runningStale" : failed > 0 ? "runningFailed" : "running"
      : stale > 0 ? "stale" : failed > 0 ? done > 0 ? "failedDone" : "failed"
        : done === count ? "done" : "total";
    pill.registration.update({
      visible: true,
      title: messages.message("composer.title", { count }),
      label: messages.message(`composer.${key}`, { count, active, stale, failed, done }),
    });
  }
}

function isActive(run: RunSummary): boolean {
  return !run.finalized && (run.liveness === "running" || (run.state === "running" && run.liveness === "unknown"));
}

type PopoverProps = Extract<PluginButtonContentProps, { context: "agent" }> & {
  openScreen: PluginClientContext["openScreen"];
};

function AgentRunsPopover({ agentId, host, layout, theme, close, openScreen }: PopoverProps) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const settings = useSettings(observerSettings);
  const values = settings.status === "ready" ? settings.values : OBSERVER_DEFAULTS;
  const query = useRunsListQuery(values.pollIntervalMs);
  const population = query.data?.runs;
  const { runs, stats } = useMemo(() => {
    const runs = population?.filter((run) => run.lineage?.parentAgentId === agentId) ?? [];
    return { runs, stats: summarizeRuns(runs) };
  }, [population, agentId]);
  const open = useCallback((runId?: string) => {
    close();
    openScreen({ screenId: "runs", params: { parentAgentId: agentId, ...(runId ? { runId } : {}) } });
  }, [agentId, close, openScreen]);

  return (
    <View style={styles.listContent}>
      <Text style={styles.cardTitle}>{host.label} · {t("composer.title", { count: runs.length })}</Text>
      <StatusStrip stats={stats} theme={theme} layout={layout} />
      {query.error ? <Text style={styles.error}>{t("error.list", { error: errorText(query.error) })}</Text> : null}
      {query.isPending ? <Text style={styles.muted}>{t("list.scanning")}</Text> : null}
      {population && runs.length === 0 ? <Text style={styles.muted}>{t("list.emptyAgent")}</Text> : null}
      {runs.map((run) => (
        <RunRow key={run.id} run={run} theme={theme} layout={layout} selected={false} onSelect={open} showLineage />
      ))}
      <Pressable accessibilityRole="button" onPress={() => open()} style={styles.backRow}>
        <Text style={styles.backLabel}>{t("composer.openRuns")}</Text>
      </Pressable>
    </View>
  );
}
