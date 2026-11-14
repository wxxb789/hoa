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
  backend: string | null;
  startedAt: string | null;
};
export type RunFinalized = { present: boolean; exitCode: number | null };
export type RunAnswer = { exists: boolean; bytes: number | null };
export type RunEventLog = { exists: boolean; bytes: number; readable: boolean };

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
  verdicts: Map<number, PidVerdict>;
};

/** Fold the on-disk run files plus derived counters into the summary the client renders. */
export function mapRun(inputs: RunInputs, nowMs: number): RunSummary {
  const { files, counters, verdicts } = inputs;
  const values = files.state.values;
  const pids = pidsOf(values, files.lock);
  const liveness = livenessOf(files.finalized, pids, verdicts);
  const state = stateOf(values, files.finalized);
  const countersFrom = counterSource(files, counters);
  const truncated =
    values.events_truncated === true ||
    files.stats?.truncated === true ||
    counters?.truncated === true;
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
  if (!files.events.exists || !files.events.readable) warnings.push("log-unreadable");
  if (truncated) warnings.push("log-truncated");
  if (liveness === "unknown" && !files.finalized.present) warnings.push("liveness-unknown");

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
    model: asString(values.model),
    thinking: asString(values.thinking),
    maxTime: asString(values.max_time),
    sessionId: asString(values.session_id) ?? files.sessionIdFromFile,
    turns: countersFrom === "state" ? asNumber(values.turns) : (counters?.turns ?? null),
    toolCalls: countersFrom === "state" ? asNumber(values.tool_calls) : (counters?.toolCalls ?? null),
    costUsd: countersFrom === "state" ? asNumber(values.cost_usd) : (counters?.costUsd ?? null),
    countersFrom,
    countersPartial:
      truncated ||
      values.turns_partial === true ||
      values.tool_calls_partial === true ||
      values.cost_partial === true,
    currentTool: counters?.currentTool?.name ?? null,
    currentToolIntent: counters?.currentTool?.intent ?? null,
    lastError: counters?.lastError ?? lastStateError(values),
    errorCount: Math.max(counters?.errorCount ?? 0, stateErrors(values).length),
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
  // `finalized` is authoritative: a run that finalized without leaving a usable state is
  // classified from its exit code, and a stale `running` is never reported as running.
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

function counterSource(
  files: RunFiles,
  counters: CounterSnapshot | null,
): RunSummary["countersFrom"] {
  const stateHasCounters =
    asNumber(files.state.values.turns) !== null ||
    asNumber(files.state.values.tool_calls) !== null ||
    asNumber(files.state.values.cost_usd) !== null;
  const eventsHaveCounters = counters !== null && counters.lines > 0;
  if (files.finalized.present && stateHasCounters) return "state";
  if (eventsHaveCounters) return "events";
  return stateHasCounters ? "state" : "none";
}

function stateErrors(values: Record<string, unknown>): string[] {
  const raw = values.errors;
  if (!Array.isArray(raw)) return [];
  return raw.filter((entry): entry is string => typeof entry === "string");
}

function lastStateError(values: Record<string, unknown>): string | null {
  const errors = stateErrors(values);
  return errors.length > 0 ? errors[errors.length - 1] : null;
}

function elapsedFromTimestamps(startedAt: string | null, endedAt: string | null): number | null {
  if (!startedAt || !endedAt) return null;
  const started = Date.parse(startedAt);
  const ended = Date.parse(endedAt);
  if (Number.isNaN(started) || Number.isNaN(ended)) return null;
  return Math.max(0, Math.round((ended - started) / 100) / 10);
}
