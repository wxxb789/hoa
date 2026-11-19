import type { RunModel, RunModelUsage, RunSummary } from "../shared/runs";

/** Locale-aware formatters, built once per locale instead of once per rendered row. */
function perLocale<T>(cache: Map<string, T>, locale: string, build: () => T): T {
  const cached = cache.get(locale);
  if (cached !== undefined) return cached;
  const built = build();
  cache.set(locale, built);
  return built;
}

const dateTimes = new Map<string, Intl.DateTimeFormat>();
const times = new Map<string, Intl.DateTimeFormat>();
const counts = new Map<string, Intl.NumberFormat>();

export function formatDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}

export function formatCost(usd: number | null): string | null {
  if (usd === null || !Number.isFinite(usd)) return null;
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

export function formatCount(value: number, locale: string): string {
  if (!Number.isFinite(value)) return String(value);
  return perLocale(counts, locale, () => new Intl.NumberFormat(locale)).format(value);
}

export function formatBytes(bytes: number | null): string | null {
  if (bytes === null || !Number.isFinite(bytes)) return null;
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : String(Math.round(value))} ${units[unit]}`;
}

/** Date and time of a timestamp, in the client's locale. */
export function clockOf(iso: string | null, locale: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return perLocale(
    dateTimes,
    locale,
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
  ).format(date);
}

/** Wall clock of an event timestamp, second resolution. */
export function eventClockOf(at: string | null, locale: string): string | null {
  if (!at) return null;
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return at;
  return perLocale(
    times,
    locale,
    () =>
      new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
  ).format(date);
}

export function counterLine(parts: Array<string | null>): string {
  return parts.filter((part): part is string => part !== null && part !== "").join(" · ");
}

export type CounterKey = "counter.turns" | "counter.tools" | "counter.cost";

/**
 * The turns/tools/cost line every run surface shows, with missing counters left out. The caller
 * passes its own translator so this stays free of the host's i18n types.
 */
export function countersLine(
  counters: Pick<RunSummary, "turns" | "toolCalls" | "costUsd">,
  label: (key: CounterKey, value: string) => string,
  locale: string,
): string {
  return counterLine([
    counters.turns === null
      ? null
      : label("counter.turns", formatCount(counters.turns, locale)),
    counters.toolCalls === null
      ? null
      : label("counter.tools", formatCount(counters.toolCalls, locale)),
    formatCost(counters.costUsd),
  ]);
}

/** Message text of an unknown thrown value. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function usageLabel(usage: RunModelUsage | null): string | null {
  if (!usage) return null;
  const parts = [usage.provider, usage.model].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join("/") : null;
}

export function firstUsage(model: RunModel): RunModelUsage | null {
  return model.observed[0] ?? null;
}
