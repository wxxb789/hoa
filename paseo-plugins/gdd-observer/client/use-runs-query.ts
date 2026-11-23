import { useRpc } from "@getpaseo/plugin/client";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import {
  listRuns,
  type ListRunsDelta,
  type ListRunsOutput,
  type ListRunsUpdate,
  type RunSummary,
} from "../shared/runs";

/**
 * The one run-scan query every surface reads. The panel and the settings screen both mount over
 * this key, so it lives here: a surface that invented its own key would scan the launcher twice
 * per tick. The detail views keep their own `runs.follow`/`runs.paths` queries.
 */
export const RUNS_LIST_QUERY_KEY = ["gddRuns", "list"] as const;

/**
 * Cached with the data it describes so a canceled or failed poll cannot relabel an older scan.
 * A snapshot seeded without a revision (e.g. by a test) asks for a full response.
 */
export type CachedList = ListRunsOutput & { revision?: string };

export const RunsListControllerContext = createContext<{
  refresh(): Promise<CachedList>;
  reload(): Promise<CachedList>;
  observe(intervalMs: number): () => void;
  bindQueryClient?(queryClient: QueryClient): () => void;
} | null>(null);

/** The full variant; `runs` is the union's only discriminator. */
type FullListRunsUpdate = Extract<ListRunsUpdate, { runs: RunSummary[] }>;

function isFullListRunsUpdate(update: ListRunsUpdate): update is FullListRunsUpdate {
  return "runs" in update;
}

/**
 * Folds one delta into the snapshot it was computed against: listed summaries replace their run
 * (or add it), `removed` drops ids, and `order` restates the whole sequence when it changed.
 * Unchanged rows keep their summary objects, and a delta with no row change keeps the run array
 * itself, so a poll that changed nothing leaves the list's data and its mounted window alone.
 */
export function applyListDelta(base: ListRunsOutput, delta: ListRunsDelta): CachedList {
  const { changes, removed, order, ...facts } = delta;
  if (changes.length === 0 && removed.length === 0 && order === undefined) {
    return { ...facts, runs: base.runs };
  }
  if (order === undefined) {
    // Only summaries changed, the common poll: index the changes, not the whole population.
    const replacements = new Map(changes.map((run) => [run.id, run]));
    const dropped = removed.length === 0 ? null : new Set(removed);
    const runs: RunSummary[] = [];
    for (const run of base.runs) {
      if (dropped !== null && dropped.has(run.id)) continue;
      runs.push(replacements.get(run.id) ?? run);
    }
    return { ...facts, runs };
  }
  const byId = new Map(base.runs.map((run) => [run.id, run]));
  for (const run of changes) byId.set(run.id, run);
  for (const id of removed) byId.delete(id);
  const runs: RunSummary[] = [];
  for (const id of order) {
    const run = byId.get(id);
    if (run === undefined) throw new Error(`runs.list delta order names unknown run: ${id}`);
    runs.push(run);
  }
  return { ...facts, runs };
}

type FetchRunsList = (input: { knownRevision?: string }) => Promise<ListRunsUpdate>;

/**
 * One scan step for one host: ask from the revision of the snapshot in this host's cache, then
 * fold the answer back into that snapshot so a poll transfers only what changed. React Query
 * aborts the step when a newer scan replaces it, so a superseded step never claims a revision it
 * did not store; a delta that arrives after its base left the cache has nothing to fold into and
 * is answered with one full read instead of a corrupted list.
 */
async function fetchRunsList(
  client: QueryClient,
  list: FetchRunsList,
  signal: AbortSignal,
): Promise<CachedList> {
  const base = client.getQueryData<CachedList>(RUNS_LIST_QUERY_KEY);
  const knownRevision = base?.revision;
  const update = await list(knownRevision === undefined ? {} : { knownRevision });
  // A canceled step was replaced by a newer scan; its answer must not relabel a cache that
  // belongs to the replacement.
  if (signal.aborted) throw new Error("runs.list scan was superseded by a newer one");
  if (isFullListRunsUpdate(update)) return update;
  if (base === undefined || client.getQueryData(RUNS_LIST_QUERY_KEY) !== base) {
    // The delta's base is no longer cached, so the delta cannot be folded anywhere: replace it
    // with one full read.
    const full = await list({});
    if (signal.aborted) throw new Error("runs.list scan was superseded by a newer one");
    if (!isFullListRunsUpdate(full)) {
      throw new Error("runs.list answered a request without a known revision with a delta");
    }
    return full;
  }
  return applyListDelta(base, update);
}

type Registration = { id: symbol; intervalMs: number };

type PollingSnapshot = { ownerId: symbol | null; intervalMs: number | null };

const NO_OWNER: PollingSnapshot = { ownerId: null, intervalMs: null };

/**
 * Elects one polling surface per query cache. React Query keeps one interval timer per observer,
 * so without an election a panel and a settings screen mounted together would each scan the
 * launcher on their own timer. Every mounted surface registers the cadence it wants; the fastest
 * cadence wins, unmounting the owner hands polling to the next fastest surface, and unmounting
 * the last surface leaves nobody polling.
 */
class RunsListPolling {
  readonly #registrations = new Map<symbol, Registration>();
  readonly #listeners = new Set<() => void>();
  #snapshot: PollingSnapshot = NO_OWNER;

  register = (id: symbol, intervalMs: number): void => {
    this.#registrations.set(id, { id, intervalMs });
    this.#publish();
  };

  /** A surface that changed its requested cadence keeps its place in the tie order. */
  update = (id: symbol, intervalMs: number): void => {
    const registration = this.#registrations.get(id);
    if (registration === undefined || registration.intervalMs === intervalMs) return;
    registration.intervalMs = intervalMs;
    this.#publish();
  };

  unregister = (id: symbol): void => {
    if (this.#registrations.delete(id)) this.#publish();
  };

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): PollingSnapshot => this.#snapshot;

  #publish(): void {
    let owner: Registration | null = null;
    for (const registration of this.#registrations.values()) {
      if (owner === null || registration.intervalMs < owner.intervalMs) owner = registration;
    }
    const ownerId = owner === null ? null : owner.id;
    const intervalMs = owner === null ? null : owner.intervalMs;
    if (ownerId === this.#snapshot.ownerId && intervalMs === this.#snapshot.intervalMs) return;
    this.#snapshot = { ownerId, intervalMs };
    for (const listener of this.#listeners) listener();
  }
}

const pollingByClient = new WeakMap<QueryClient, RunsListPolling>();

function pollingFor(client: QueryClient): RunsListPolling {
  const existing = pollingByClient.get(client);
  if (existing !== undefined) return existing;
  const created = new RunsListPolling();
  pollingByClient.set(client, created);
  return created;
}

/**
 * Observes the shared, revisioned run scan — each step folds the server's full snapshot or delta
 * onto the cached snapshot — and joins its polling election with this surface's requested cadence.
 * The elected surface's cadence plus explicit invalidations (a saved run root) are the scan
 * triggers, so staggered mounts cannot multiply RPCs; scan loading and error state stay on the
 * shared cache entry, so every surface renders the same result.
 */
export function useRunsListQuery(
  requestedIntervalMs: number,
  backgroundIntervalMs = requestedIntervalMs,
): UseQueryResult<ListRunsOutput, Error> {
  const client = useQueryClient();
  const list = useRpc(listRuns);
  const controller = useContext(RunsListControllerContext);
  useEffect(() => controller?.observe(backgroundIntervalMs), [controller, backgroundIntervalMs]);
  useEffect(() => controller?.bindQueryClient?.(client), [controller, client]);
  const polling = useMemo(() => pollingFor(client), [client]);
  const registrationId = useRef<symbol | null>(null);
  if (registrationId.current === null) registrationId.current = Symbol("runs-list-surface");
  const requestedRef = useRef(requestedIntervalMs);
  const { ownerId, intervalMs } = useSyncExternalStore(polling.subscribe, polling.getSnapshot);

  useEffect(() => {
    const id = registrationId.current;
    if (id === null) return undefined;
    polling.register(id, requestedRef.current);
    return () => polling.unregister(id);
  }, [polling]);

  useEffect(() => {
    const id = registrationId.current;
    if (id === null) return;
    requestedRef.current = requestedIntervalMs;
    polling.update(id, requestedIntervalMs);
  }, [polling, requestedIntervalMs]);

  const pollInterval = ownerId === registrationId.current && intervalMs !== null ? intervalMs : false;
  // Mount behaviour follows the scan's active observers instead of a fixed policy: a surface that
  // opens while nothing else watches the scan keeps the baseline immediate refresh of stale or
  // failed data, and a surface joining an already active observer reuses the scan instead of
  // adding one. `QueryObserver.onSubscribe` adds the observer to the query before it decides
  // (verified in the installed query-core), so both mount predicates see this observer itself and
  // `<= 1` means "no other active observer", including a sole-surface replacement in one commit.
  return useQuery({
    queryKey: RUNS_LIST_QUERY_KEY,
    queryFn: (context) => controller?.refresh() ?? fetchRunsList(client, list, context.signal),
    // Only the elected surface holds a timer; every other surface passes `false` so a previous
    // ownership does not keep ticking.
    refetchInterval: pollInterval,
    refetchOnMount: (query) => query.getObserversCount() <= 1,
    retryOnMount: (query) => query.getObserversCount() <= 1,
  });
}
