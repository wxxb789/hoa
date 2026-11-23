import type { PluginButtonIconProps, PluginButtonContentProps } from "@getpaseo/plugin/client";
import { View } from "react-native";
import type { RunSummary } from "../shared/runs";
import { messages } from "./messages";

type Theme = PluginButtonContentProps["theme"];
type DotTone = "statusSuccess" | "statusWarning" | "statusDanger" | "foregroundMuted";

export function isActive(run: RunSummary): boolean {
  return !run.finalized && (run.liveness === "running" || (run.state === "running" && run.liveness === "unknown"));
}

function needsAttention(run: RunSummary): boolean {
  return run.liveness === "stale" || (!run.finalized && run.liveness === "unknown");
}

function isFailure(run: RunSummary): boolean {
  return run.state === "failed" || run.state === "killed";
}

export function runDotColor(run: RunSummary, theme: Theme): string {
  return theme.colors[needsAttention(run) ? "statusWarning" : isActive(run) || run.state === "done"
    ? "statusSuccess" : isFailure(run) ? "statusDanger" : "foregroundMuted"];
}

function statusIcon(tone: DotTone) {
  return function StatusIcon({ theme, size }: PluginButtonIconProps) {
    return (
      <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: theme.colors[tone] }} />
      </View>
    );
  };
}

const icons = {
  statusSuccess: statusIcon("statusSuccess"),
  statusWarning: statusIcon("statusWarning"),
  statusDanger: statusIcon("statusDanger"),
  foregroundMuted: statusIcon("foregroundMuted"),
};

export function compactDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.floor(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m`;
  const remainder = minutes % 60;
  return `${Math.floor(minutes / 60)}h${remainder ? ` ${remainder}m` : ""}`;
}

function pillGoal(run: RunSummary): string {
  const goal = run.lineage?.goal ?? run.name;
  if (goal.length <= 20) return goal;
  const chars = Array.from(goal);
  return chars.length > 20 ? `${chars.slice(0, 19).join("").trimEnd()}…` : goal;
}

function presentation<Key extends Parameters<typeof messages.message>[0]>(
  tone: DotTone,
  ...args: Parameters<typeof messages.message<Key>>
) {
  return { label: messages.message<Key>(...args), icon: icons[tone], key: JSON.stringify([tone, ...args]) };
}

export function composerPresentation(runs: readonly RunSummary[]) {
  const latest = runs[0];
  let active = 0;
  let firstActive = latest;
  let stale = 0;
  let activeAttention = false;
  for (const run of runs) {
    if (isActive(run)) {
      if (active === 0) firstActive = run;
      active += 1;
      activeAttention ||= needsAttention(run);
    }
    if (run.liveness === "stale") stale += 1;
  }

  const attention = active > 0 ? activeAttention || stale > 0 : needsAttention(latest);
  const tone = attention ? "statusWarning" : active > 0 ? "statusSuccess"
    : isFailure(latest) ? "statusDanger" : "foregroundMuted";
  if (active === 1) {
    const stage = firstActive.lineage?.stage ?? "GDD";
    const goal = pillGoal(firstActive);
    const elapsed = compactDuration(firstActive.elapsedS);
    return elapsed === null ? presentation(tone, "composer.single", { stage, goal })
      : presentation(tone, "composer.singleElapsed", { stage, goal, elapsed });
  }
  if (active > 1) {
    return stale > 0 ? presentation(tone, "composer.runningStale", { active, stale })
      : presentation(tone, "composer.running", { active });
  }

  const goal = pillGoal(latest);
  const stage = latest.lineage?.stage ?? "GDD";
  if (latest.liveness === "stale") return presentation(tone, "composer.stale", { goal });
  if (latest.state === "failed") return presentation(tone, "composer.failed", { goal, stage });
  if (latest.state === "killed") return presentation(tone, "composer.killed", { goal, stage });
  return latest.state === "done" && latest.liveness === "settled"
    ? presentation(tone, "composer.done", { goal })
    : presentation(tone, "composer.quiet", { goal });
}

export const idleStatusIcon = icons.foregroundMuted;
