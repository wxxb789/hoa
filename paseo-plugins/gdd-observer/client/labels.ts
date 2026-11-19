import type {
  RunEvent,
  RunLiveness,
  RunRootSource,
  RunState,
  RunSummary,
  RunWarning,
} from "../shared/runs";
import { RUN_STATES } from "../shared/runs";
import type { ObserverTheme } from "./types";

export type StateKey = `state.${RunState}`;
export type LivenessKey = `liveness.${RunLiveness}`;
export type SourceKey = `source.${RunRootSource}`;
export type WarningKey = `warning.${RunWarning}`;
/** Only the two counted sources have copy; `none` has nothing to say about its origin. */
export type CounterSourceKey = `counter.from${"State" | "Events"}`;

const STATE_RANK: Record<RunState, number> = { running: 0, done: 1, failed: 2, killed: 3, unknown: 4 };

export const STATE_ORDER: readonly RunState[] = RUN_STATES.slice().sort(
  (left, right) => STATE_RANK[left] - STATE_RANK[right],
);

export function stateKey(state: RunState): StateKey {
  return `state.${state}`;
}

export function livenessKey(liveness: RunLiveness): LivenessKey {
  return `liveness.${liveness}`;
}

export function sourceKey(source: RunRootSource): SourceKey {
  return `source.${source}`;
}

export function warningKey(warning: RunWarning): WarningKey {
  return `warning.${warning}`;
}

export function counterSourceKey(from: RunSummary["countersFrom"]): CounterSourceKey | null {
  if (from === "state") return "counter.fromState";
  if (from === "events") return "counter.fromEvents";
  return null;
}

export function stateColor(state: RunState, theme: ObserverTheme): string {
  if (state === "running") return theme.colors.accent;
  if (state === "done") return theme.colors.statusSuccess;
  if (state === "killed") return theme.colors.statusWarning;
  if (state === "failed") return theme.colors.statusDanger;
  return theme.colors.foregroundMuted;
}

export function livenessColor(liveness: RunLiveness, theme: ObserverTheme): string {
  if (liveness === "running") return theme.colors.statusSuccess;
  if (liveness === "stale") return theme.colors.statusWarning;
  return theme.colors.foregroundMuted;
}

export function eventColor(event: RunEvent, theme: ObserverTheme): string {
  if (event.type === "truncated") return theme.colors.statusWarning;
  if (event.type.includes("error")) return theme.colors.statusDanger;
  if (event.type.includes("tool") && event.type.includes("start")) return theme.colors.accent;
  return theme.colors.foregroundMuted;
}
