import type { RunEvent } from "../shared/runs";

export type OpenTool = { name: string; intent: string | null };

export type ModelUsage = {
  provider: string | null;
  model: string | null;
  api: string | null;
  messages: number;
};

/**
 * Running counters for one `events.ndjson`, derived with the same rules the launcher's finalizer
 * uses: `turns` counts `turn_end`, `tool_calls` counts every `*tool*start*` event, `cost` sums
 * assistant `message_end` usage, and a `truncated` line is the writer's splice marker.
 */
export type RunCounters = {
  turns: number;
  toolCalls: number;
  costUsd: number;
  errorCount: number;
  errors: string[];
  open: Map<string, OpenTool>;
  models: Map<string, ModelUsage>;
  lastEventAt: string | null;
  lines: number;
  badLines: number;
  truncated: boolean;
  droppedBytes: number;
  splices: number;
};

export type CounterSnapshot = {
  turns: number;
  toolCalls: number;
  costUsd: number;
  errorCount: number;
  lastError: string | null;
  currentTool: OpenTool | null;
  models: ModelUsage[];
  lastEventAt: string | null;
  lines: number;
  badLines: number;
  truncated: boolean;
  droppedBytes: number;
};

const DETAIL_LIMIT = 160;
const ERROR_LIMIT = 300;
const KEPT_ERRORS = 5;
const SUPPRESSED_KEYS: Record<string, true> = {
  content: true,
  result: true,
  partialResult: true,
  details: true,
  output: true,
  text: true,
  diff: true,
  patch: true,
};

export function createCounters(): RunCounters {
  return {
    turns: 0,
    toolCalls: 0,
    costUsd: 0,
    errorCount: 0,
    errors: [],
    open: new Map(),
    models: new Map(),
    lastEventAt: null,
    lines: 0,
    badLines: 0,
    truncated: false,
    droppedBytes: 0,
    splices: 0,
  };
}

export function snapshotCounters(counters: RunCounters): CounterSnapshot {
  return {
    turns: counters.turns,
    toolCalls: counters.toolCalls,
    costUsd: counters.costUsd,
    errorCount: counters.errorCount,
    lastError: counters.errors.length > 0 ? counters.errors[counters.errors.length - 1] : null,
    currentTool: currentToolOf(counters),
    models: Array.from(counters.models.values(), (usage) => ({ ...usage })),
    lastEventAt: counters.lastEventAt,
    lines: counters.lines,
    badLines: counters.badLines,
    truncated: counters.truncated,
    droppedBytes: counters.droppedBytes,
  };
}

function currentToolOf(counters: RunCounters): OpenTool | null {
  let last: OpenTool | null = null;
  for (const tool of counters.open.values()) last = tool;
  return last;
}

export function applyEventLine(counters: RunCounters, line: string): RunEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    counters.badLines += 1;
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    counters.badLines += 1;
    return null;
  }
  const event = parsed as Record<string, unknown>;
  const type = asString(event.type);
  if (!type) {
    counters.badLines += 1;
    return null;
  }
  counters.lines += 1;

  const at = timestampOf(event.timestamp);
  if (at) counters.lastEventAt = at;

  if (type === "truncated") {
    counters.splices += 1;
    counters.truncated = true;
    counters.droppedBytes = Math.max(counters.droppedBytes, asNumber(event.dropped_bytes) ?? 0);
  } else if (type === "turn_end") {
    counters.turns += 1;
  }

  const tool = asString(event.toolName);
  if (type.includes("tool")) {
    const id = asString(event.toolCallId) ?? `${type}#${counters.lines}`;
    if (type.includes("start")) {
      counters.toolCalls += 1;
      counters.open.set(id, { name: tool ?? "tool", intent: asString(event.intent) });
    } else if (type.includes("end")) {
      counters.open.delete(id);
    } else if (type.includes("error")) {
      counters.errorCount += 1;
      counters.errors.push(clip(JSON.stringify(event), ERROR_LIMIT));
      if (counters.errors.length > KEPT_ERRORS) {
        counters.errors.splice(0, counters.errors.length - KEPT_ERRORS);
      }
    }
  }

  const message = asRecord(event.message);
  const role = message ? asString(message.role) : null;
  if (message && role === "assistant" && (type === "message_start" || type === "message_end")) {
    // Both events carry the provider/model that produced the message; only `message_end` is
    // counted, so one message is counted once while a streaming message still names its model.
    attributeModel(counters, message, type === "message_end");
  }
  if (type === "message_end" && role === "assistant") {
    const usage = message ? asRecord(message.usage) : null;
    counters.costUsd += costOf(usage?.cost);
  }

  return { type, at, tool, intent: asString(event.intent), detail: detailOf(type, event), role };
}

export function parseEventWindow(text: string, limit: number): RunEvent[] {
  const counters = createCounters();
  const events: RunEvent[] = [];
  const lines = text.split("\n");
  for (let index = lines.length - 1; index >= 0 && events.length < limit; index -= 1) {
    const event = applyEventLine(counters, lines[index]);
    if (!event) continue;
    events.push(event);
  }
  events.reverse();
  return events;
}

export function summarizeValue(value: unknown, limit = DETAIL_LIMIT): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value === "string") return clip(value, limit);
  try {
    const json = JSON.stringify(value, (key, item) => {
      if (SUPPRESSED_KEYS[key]) return "[…]";
      if (typeof item === "string" && item.length > limit) return `${item.slice(0, limit)}…`;
      return item;
    });
    return json ? clip(json, limit) : null;
  } catch {
    return null;
  }
}

function detailOf(type: string, event: Record<string, unknown>): string | null {
  if (type === "truncated") {
    const dropped = asNumber(event.dropped_bytes);
    return dropped ? `${dropped} bytes dropped` : "log spliced";
  }
  if (type.includes("tool")) {
    return (
      summarizeValue(event.args) ??
      summarizeValue(event.partialResult) ??
      summarizeValue(event.error) ??
      null
    );
  }
  return null;
}

function costOf(cost: unknown): number {
  const direct = asNumber(cost);
  if (direct !== null) return direct;
  const record = asRecord(cost);
  return record ? (asNumber(record.total) ?? 0) : 0;
}

function attributeModel(
  counters: RunCounters,
  message: Record<string, unknown>,
  counted: boolean,
): void {
  const provider = asString(message.provider);
  const model = asString(message.model);
  const api = asString(message.api);
  if (provider === null && model === null && api === null) return;
  const key = `${provider ?? ""}\u0000${model ?? ""}\u0000${api ?? ""}`;
  const usage = counters.models.get(key) ?? { provider, model, api, messages: 0 };
  if (counted) usage.messages += 1;
  counters.models.set(key, usage);
}

function timestampOf(value: unknown): string | null {
  const text = asString(value);
  if (text) return text;
  const numeric = asNumber(value);
  if (numeric === null) return null;
  const date = new Date(numeric);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function clip(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
