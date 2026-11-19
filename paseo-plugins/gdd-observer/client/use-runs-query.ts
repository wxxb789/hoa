import { useRpc } from "@getpaseo/plugin/client";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { listRuns, type ListRunsOutput } from "../shared/runs";

/**
 * The one run-scan query every surface reads. The panel and the settings screen both mount over
 * this key, so it lives here: a surface that invented its own key would scan the launcher twice
 * per tick. The detail views keep their own `runs.follow`/`runs.paths` queries.
 */
export const RUNS_LIST_QUERY_KEY = ["gddRuns", "list"] as const;

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
 * Observes the shared run scan and joins its polling election with this surface's requested
 * cadence. The elected surface's cadence plus explicit invalidations (a saved run root) are the
 * scan triggers, so staggered mounts cannot multiply RPCs; scan loading and error state stay on
 * the shared cache entry, so every surface renders the same result.
 */
export function useRunsListQuery(
  requestedIntervalMs: number,
): UseQueryResult<ListRunsOutput, Error> {
  const client = useQueryClient();
  const list = useRpc(listRuns);
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
    queryFn: () => list({}),
    // Only the elected surface holds a timer; every other surface passes `false` so a previous
    // ownership does not keep ticking.
    refetchInterval: pollInterval,
    refetchOnMount: (query) => query.getObserversCount() <= 1,
    retryOnMount: (query) => query.getObserversCount() <= 1,
  });
}
