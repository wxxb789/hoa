import type { RunEvent } from "../shared/runs";

export type OpenTool = { name: string; intent: string | null };

export type ModelUsage = {
  provider: string | null;
  model: string | null;
  api: string | null;
  messages: number;
};

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
const MESSAGE_LIMIT = 240;
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
    const dropped = asNumber(event.dropped_bytes) ?? 0;
    counters.droppedBytes = Math.max(counters.droppedBytes, dropped);
    return activity(type, at, dropped ? `${dropped} bytes dropped` : "log spliced");
  }
  if (type === "turn_end" || type === "turn.completed") {
    counters.turns += 1;
    return null;
  }
  if (type === "item.started" || type === "item.completed") {
    const item = asRecord(event.item);
    return item ? codexItem(counters, item, at, type === "item.started") : null;
  }
  if (type === "turn.failed" || type === "error") {
    return recordError(counters, type, at, errorDetail(event.error ?? event.message) ?? summarizeValue(event));
  }
  if (type === "result") {
    counters.open.clear();
    const subtype = asString(event.subtype);
    return event.is_error === true || (subtype && subtype !== "success")
      ? recordError(counters, "result_error", at, errorDetail(event.errors ?? event.error ?? event.result) ?? subtype)
      : null;
  }
  if (type === "agent_settled" && event.aborted === true) {
    return recordError(counters, "agent_aborted", at, errorDetail(event.error ?? event.reason));
  }
  if (type.includes("tool")) return foldOmpTool(counters, event, type, at);
  if (type.includes("error") || type.includes("failed") || type.includes("aborted")) {
    return recordError(counters, type, at, errorDetail(event.error ?? event.message ?? event.reason));
  }

  const message = asRecord(event.message);
  if (!message) return null;
  if (type === "assistant" || type === "user") return claudeMessage(counters, message, type, at);
  if (message.role !== "assistant") return null;
  if (type === "message_start") {
    attributeModel(counters, message, false);
    return null;
  }
  if (type !== "message_end") return null;
  attributeModel(counters, message, true);
  counters.costUsd += costOf(asRecord(message.usage)?.cost);
  const reason = message.stopReason;
  const failure = asString(message.errorMessage);
  if (failure && (reason === "error" || reason === "aborted" || reason === "length")) {
    return recordError(counters, reason === "aborted" ? "message_aborted" : "message_error", at, failure);
  }
  const text = messageText(message.content);
  return text === null ? null : activity(type, at, text, null, null, "assistant");
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

function foldOmpTool(
  counters: RunCounters, event: Record<string, unknown>, type: string, at: string | null,
): RunEvent | null {
  const tool = asString(event.toolName) ?? "tool";
  const id = asString(event.toolCallId);
  if (type.includes("start")) {
    const intent = asString(event.intent);
    counters.toolCalls += 1;
    counters.open.set(id ?? `${type}#${counters.lines}`, { name: tool, intent });
    return activity(type, at, summarizeValue(event.args), tool, intent);
  }
  const failed = type.includes("error") || type.includes("failed");
  if (type.includes("end") || failed) {
    if (id !== null) counters.open.delete(id);
    if (failed || event.isError === true || (event.error !== undefined && event.error !== null)) {
      return recordError(counters, failed ? type : "tool_execution_error", at,
        errorDetail(event.error) ?? messageText(asRecord(event.result)?.content) ?? summarizeValue(event), tool);
    }
  }
  return null;
}

function codexItem(
  counters: RunCounters, item: Record<string, unknown>, at: string | null, started: boolean,
): RunEvent | null {
  const type = asString(item.type);
  if (type === "agent_message" && !started) {
    const text = compactText(item.text, MESSAGE_LIMIT);
    return text === null ? null : activity(type, at, text, null, null, "assistant");
  }
  if (type === "error") return started ? null : recordError(counters, type, at, errorDetail(item.message));
  if (type !== "command_execution" && type !== "mcp_tool_call" && type !== "web_search" && type !== "file_change") return null;

  const id = asString(item.id);
  const exit = asNumber(item.exit_code);
  const failed = (exit !== null && exit !== 0) || item.status === "failed";
  if (!started) {
    const wasOpen = id !== null && counters.open.delete(id);
    if (type === "file_change" && !wasOpen) counters.toolCalls += 1;
    if (type !== "file_change" && !failed) return null;
  }
  let tool: string;
  let detail: string | null;
  switch (type) {
    case "command_execution":
      tool = "command";
      detail = compactCommand(item.command);
      break;
    case "mcp_tool_call": {
      const server = asString(item.server);
      const name = asString(item.tool);
      tool = name === null ? type : server === null ? name : `${server}/${name}`;
      detail = summarizeValue(item.arguments);
      break;
    }
    case "web_search":
      tool = type;
      detail = compactText(item.query, DETAIL_LIMIT) ?? summarizeValue(item.action);
      break;
    case "file_change":
      tool = type;
      detail = fileChanges(item.changes);
      break;
  }
  if (started) {
    counters.toolCalls += 1;
    if (id !== null) counters.open.set(id, { name: tool, intent: detail });
    return type === "file_change" ? null : activity(type, at, detail, tool);
  }
  if (failed) {
    const failure = exit !== null && exit !== 0 ? `Exit ${exit}` : errorDetail(item.error);
    return recordError(counters, `${type}_failed`, at,
      failure && detail ? `${failure} · ${detail}` : failure ?? detail, tool);
  }
  return activity(type, at, detail, tool);
}

function claudeMessage(
  counters: RunCounters, message: Record<string, unknown>, type: "assistant" | "user", at: string | null,
): RunEvent | null {
  if (type === "assistant") attributeModel(counters, message, true);
  const blocks = message.content;
  if (!Array.isArray(blocks)) return null;
  let toolEvent: RunEvent | null = null;
  for (const value of blocks) {
    const block = asRecord(value);
    if (!block) continue;
    if (type === "assistant" && block.type === "tool_use") {
      const name = asString(block.name);
      if (name === null || name === "StructuredOutput") continue;
      const id = asString(block.id);
      const detail = summarizeValue(block.input);
      counters.toolCalls += 1;
      if (id !== null) counters.open.set(id, { name, intent: detail });
      toolEvent ??= activity("tool_use", at, detail, name);
    } else if (type === "user" && block.type === "tool_result") {
      const id = asString(block.tool_use_id);
      if (id !== null) counters.open.delete(id);
      if (block.is_error === true) {
        const error = recordError(counters, "tool_result_error", at,
          messageText(block.content) ?? errorDetail(block.content));
        toolEvent ??= error;
      }
    }
  }
  const text = type === "assistant" ? messageText(blocks) : null;
  return text === null ? toolEvent : activity(type, at, text, null, null, "assistant");
}

function activity(
  type: string, at: string | null, detail: string | null,
  tool: string | null = null, intent: string | null = null, role: string | null = null,
): RunEvent {
  return { type, at, tool, intent, detail, role };
}

function recordError(
  counters: RunCounters, type: string, at: string | null, detail: string | null, tool: string | null = null,
): RunEvent {
  const error = compactText(detail, ERROR_LIMIT) ?? type;
  counters.errorCount += 1;
  if (counters.errors.length === KEPT_ERRORS) counters.errors.shift();
  counters.errors.push(error);
  return activity(type, at, error, tool);
}

function errorDetail(value: unknown): string | null {
  return compactText(value, ERROR_LIMIT) ?? compactText(asRecord(value)?.message, ERROR_LIMIT) ??
    summarizeValue(value, ERROR_LIMIT);
}

function messageText(content: unknown): string | null {
  if (!Array.isArray(content)) return compactText(content, MESSAGE_LIMIT);
  let text = "";
  for (const value of content) {
    const block = asRecord(value);
    if (block?.type !== "text") continue;
    const part = compactText(block.text, MESSAGE_LIMIT);
    if (part === null) continue;
    text = text ? `${text} ${part}` : part;
    if (text.length > MESSAGE_LIMIT) return clip(text, MESSAGE_LIMIT);
  }
  return text || null;
}

function compactText(value: unknown, limit: number): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim().replace(/\s+/gu, " ");
  return text ? clip(text, limit) : null;
}

function compactCommand(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const command = value.trim().replace(
    /^(?:"[^"\n]*[\\/](?:pwsh|powershell|bash|sh)(?:\.exe)?"|(?:\S*[\\/])?(?:pwsh|powershell|bash|sh)(?:\.exe)?)\s+(?:-Command|-lc|-c)\s+/iu,
    "",
  );
  return compactText(command, 200);
}

function fileChanges(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  let text = "";
  for (const change of value) {
    const record = asRecord(change);
    const path = asString(record?.path);
    if (path === null) continue;
    const kind = asString(record?.kind);
    text += `${text ? ", " : ""}${kind ? `${kind} ` : ""}${path}`;
    if (text.length > DETAIL_LIMIT) return clip(text, DETAIL_LIMIT);
  }
  return text || null;
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
