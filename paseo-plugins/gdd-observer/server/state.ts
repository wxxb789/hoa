import {
  RUN_STATES,
  type EventStats,
  type RunLiveness,
  type RunState,
  type RunSummary,
  type RunWarning,
} from "../shared/runs";
import { asNumber, asString, type CounterSnapshot } from "./events";
import type { PidVerdict } from "./liveness";

export type RunStateFile = { present: boolean; readable: boolean; values: Record<string, unknown> };
export type RunLock = {
  pid: number | null;
  agentPid: number | null;
};
export type RunFinalized = { present: boolean; exitCode: number | null };
export type RunAnswer = { exists: boolean; bytes: number | null };
export type RunEventLog = { exists: boolean; bytes: number };

export type RunFiles = {
  dir: string;
  date: string;
  slug: string;
  state: RunStateFile;
  lock: RunLock | null;
  finalized: RunFinalized;
  stats: EventStats;
  answer: RunAnswer;
  events: RunEventLog;
  sessionIdFromFile: string | null;
  dirModifiedAt: string | null;
};

export type RunInputs = {
  files: RunFiles;
  counters: CounterSnapshot | null;
  /** Whether the counting pass could read the event log at all. */
  logReadable: boolean;
  verdicts: Map<number, PidVerdict>;
};

export function mapRun(inputs: RunInputs, nowMs: number): RunSummary {
  const { files, counters, logReadable, verdicts } = inputs;
  const values = files.state.values;
  const pids = pidsOf(values, files.lock);
  const liveness = livenessOf(files.finalized, pids, verdicts);
  const state = stateOf(values, files.finalized);
  const truncated =
    values.events_truncated === true ||
    files.stats?.truncated === true ||
    counters?.truncated === true;
  const { from: countersFrom, partial: countersPartial } = countersOf(
    files,
    counters,
    truncated,
  );
  const fromState = countersFrom === "state";
  const droppedBytes = Math.max(
    asNumber(values.events_dropped_bytes) ?? 0,
    files.stats?.droppedBytes ?? 0,
    counters?.droppedBytes ?? 0,
  );
  const startedAt = asString(values.started);
  const durationS = asNumber(values.duration_s) ?? elapsedFromTimestamps(startedAt, asString(values.ended));
  const warnings: RunWarning[] = [];
  if (!files.state.present) warnings.push("state-missing");
  else if (!files.state.readable) warnings.push("state-unreadable");
  if (pids.length === 0) warnings.push(values.pid === undefined ? "no-pids" : "no-lock");
  if (!files.events.exists || !logReadable) warnings.push("log-unreadable");
  if (truncated) warnings.push("log-truncated");
  if (liveness === "unknown" && !files.finalized.present) warnings.push("liveness-unknown");
  const stateErrorList = stateErrors(values);

  return {
    id: `${files.date}/${files.slug}`,
    date: files.date,
    slug: files.slug,
    runDir: files.dir,
    name: asString(values.name) ?? files.slug,
    state,
    liveness,
    finalized: files.finalized.present,
    exitCode: files.finalized.exitCode ?? asNumber(values.exit),
    startedAt,
    endedAt: asString(values.ended),
    durationS,
    elapsedS:
      liveness === "running" && startedAt
        ? elapsedFromTimestamps(startedAt, new Date(nowMs).toISOString())
        : durationS,
    model: modelOf(values, counters),
    maxTime: asString(values.max_time),
    sessionId: asString(values.session_id) ?? files.sessionIdFromFile,
    turns: fromState ? asNumber(values.turns) : (counters?.turns ?? null),
    toolCalls: fromState ? asNumber(values.tool_calls) : (counters?.toolCalls ?? null),
    costUsd: fromState ? asNumber(values.cost_usd) : (counters?.costUsd ?? null),
    countersFrom,
    countersPartial,
    currentTool: counters?.currentTool?.name ?? null,
    currentToolIntent: counters?.currentTool?.intent ?? null,
    lastError: counters?.lastError ?? stateErrorList[stateErrorList.length - 1] ?? null,
    errorCount: Math.max(counters?.errorCount ?? 0, stateErrorList.length),
    answerChars: asNumber(values.answer_chars) ?? files.answer.bytes,
    hasAnswer: files.answer.exists,
    eventsBytes: files.events.bytes,
    eventsDroppedBytes: droppedBytes,
    eventsTruncated: truncated,
    eventLines: counters?.lines ?? 0,
    pids: { pid: pids[0] ?? null, agentPid: pids[1] ?? null },
    livePids: pids.filter((pid) => verdicts.get(pid) === "alive"),
    lastEventAt: counters?.lastEventAt ?? null,
    dirModifiedAt: files.dirModifiedAt,
    warnings,
  };
}

export function pidsOf(values: Record<string, unknown>, lock: RunLock | null): number[] {
  const pids: number[] = [];
  const push = (pid: number | null) => {
    if (pid !== null && Number.isInteger(pid) && pid > 0 && !pids.includes(pid)) pids.push(pid);
  };
  push(asNumber(values.pid));
  push(asNumber(values.agent_pid));
  push(lock?.pid ?? null);
  push(lock?.agentPid ?? null);
  return pids;
}

function livenessOf(
  finalized: RunFinalized,
  pids: number[],
  verdicts: Map<number, PidVerdict>,
): RunLiveness {
  if (finalized.present) return "settled";
  if (pids.length === 0) return "unknown";
  const verdictList = pids.map((pid) => verdicts.get(pid) ?? "unknown");
  if (verdictList.includes("alive")) return "running";
  return verdictList.every((verdict) => verdict === "dead") ? "stale" : "unknown";
}

function stateOf(values: Record<string, unknown>, finalized: RunFinalized): RunState {
  const written = asString(values.state);
  const declared = RUN_STATES.find((candidate) => candidate === written);
  if (finalized.present && (declared === undefined || declared === "running")) {
    return stateFromExit(finalized.exitCode);
  }
  return declared ?? "unknown";
}

function stateFromExit(exitCode: number | null): RunState {
  if (exitCode === null) return "unknown";
  if (exitCode === 0) return "done";
  return exitCode === 130 || exitCode === 137 || exitCode === 143 || exitCode === -2
    ? "killed"
    : "failed";
}

function countersOf(
  files: RunFiles,
  counters: CounterSnapshot | null,
  truncated: boolean,
): { from: RunSummary["countersFrom"]; partial: boolean } {
  const stateHasCounters =
    asNumber(files.state.values.turns) !== null ||
    asNumber(files.state.values.tool_calls) !== null ||
    asNumber(files.state.values.cost_usd) !== null;
  const eventsHaveCounters = counters !== null && counters.lines > 0;
  if (stateHasCounters && (files.finalized.present || !eventsHaveCounters)) {
    const values = files.state.values;
    return {
      from: "state",
      partial:
        values.turns_partial === true ||
        values.tool_calls_partial === true ||
        values.cost_partial === true,
    };
  }
  if (eventsHaveCounters) {
    return { from: "events", partial: truncated || counters.badLines > 0 };
  }
  return { from: "none", partial: false };
}

function stateErrors(values: Record<string, unknown>): string[] {
  const raw = values.errors;
  if (!Array.isArray(raw)) return [];
  return raw.filter((entry): entry is string => typeof entry === "string");
}

/**
 * Model attribution: what the launcher asked for, and what the run's own events prove it used.
 * A run that recorded no `model` used the tool's own default, which the event log then names.
 */
function modelOf(
  values: Record<string, unknown>,
  counters: CounterSnapshot | null,
): RunSummary["model"] {
  const requested = asString(values.model);
  const split = requested === null || requested.startsWith("@") ? null : splitModelId(requested);
  return {
    requested,
    requestedProvider: split?.provider ?? null,
    requestedModel: split?.model ?? null,
    thinking: asString(values.thinking),
    observed: counters?.models ?? [],
  };
}

function splitModelId(value: string): { provider: string | null; model: string | null } {
  const index = value.indexOf("/");
  if (index <= 0 || index === value.length - 1) return { provider: null, model: value };
  return { provider: value.slice(0, index), model: value.slice(index + 1) };
}

function elapsedFromTimestamps(startedAt: string | null, endedAt: string | null): number | null {
  if (!startedAt || !endedAt) return null;
  const started = Date.parse(startedAt);
  const ended = Date.parse(endedAt);
  if (Number.isNaN(started) || Number.isNaN(ended)) return null;
  return Math.max(0, Math.round((ended - started) / 100) / 10);
}
