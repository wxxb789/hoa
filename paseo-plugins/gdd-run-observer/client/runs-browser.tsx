import type { PluginTab, PluginWorkspacePanelProps, PluginScreenProps } from "@getpaseo/plugin/client";
import { useRpc, useSettings, useTranslation } from "@getpaseo/plugin/client";
import { ScrollView, copyText, useToast } from "@getpaseo/plugin/client/ui";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";
import {
  followRun,
  listRuns,
  runDetail,
  type ListRunsOutput,
  type RunEvent,
  type RunLiveness,
  type RunRootSource,
  type RunState,
  type RunSummary,
  type RunWarning,
} from "../shared/runs";
import { OBSERVER_DEFAULTS, observerSettings } from "../shared/settings";
import { clockOf, counterLine, eventClockOf, formatBytes, formatCost, formatDuration } from "./format";
import { messages } from "./messages";
import { useObserverStyles, type ObserverStyles } from "./styles";
import type { ObserverHost, ObserverLayout, ObserverTheme } from "./types";

type BrowserProps = {
  theme: ObserverTheme;
  layout: ObserverLayout;
  host: ObserverHost;
  selected: string | null;
  onSelect(id: string | null): void;
};

/** Workspace panel: selection survives tab restoration through the tab's opaque state. */
export function RunsPanel({ theme, layout, host, tab }: PluginWorkspacePanelProps) {
  const [selection, setSelection] = useTabSelection(tab);
  return (
    <RunsBrowser
      theme={theme}
      layout={layout}
      host={host}
      selected={selection.selected}
      onSelect={(id) => setSelection({ selected: id })}
    />
  );
}

/** Global screen, reachable from the Command Center on any host. */
export function RunsScreen({ theme, layout, host }: PluginScreenProps) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <RunsBrowser
      theme={theme}
      layout={layout}
      host={host}
      selected={selected}
      onSelect={setSelected}
    />
  );
}

function RunsBrowser({ theme, layout, host, selected, onSelect }: BrowserProps) {
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const toast = useToast();
  const settings = useSettings(observerSettings);
  const values = settings.status === "ready" ? settings.values : OBSERVER_DEFAULTS;
  const list = useRpc(listRuns);
  const follow = useRpc(followRun);
  const detail = useRpc(runDetail);

  const listQuery = useQuery({
    queryKey: ["gddRuns", "list"],
    queryFn: () => list({}),
    refetchInterval: values.pollIntervalMs,
  });
  // The selected run is polled while this surface is mounted, and stops the moment it unmounts.
  const followQuery = useQuery({
    queryKey: ["gddRuns", "follow", selected, values.tailLines],
    queryFn: () => follow({ id: selected ?? "", tailLines: values.tailLines }),
    enabled: selected !== null,
    refetchInterval: values.pollIntervalMs,
  });
  const detailQuery = useQuery({
    queryKey: ["gddRuns", "detail", selected, values.tailLines],
    queryFn: () => detail({ id: selected ?? "", tailLines: values.tailLines }),
    enabled: selected !== null,
    staleTime: 30_000,
  });

  const scan = listQuery.data;
  const runs = scan?.runs ?? [];
  const summary = followQuery.data?.summary ?? null;
  const showList = !layout.compact || selected === null;

  const listPane = (
    <View style={layout.compact ? styles.listCompact : styles.listWide}>
      <ScrollView contentContainerStyle={styles.listContent}>
        <Text style={styles.heading}>{t("list.runs")}</Text>
        {scan ? (
          <RootFacts scan={scan} theme={theme} layout={layout} locale={locale} />
        ) : (
          <Text style={styles.muted}>{t("list.scanning")}</Text>
        )}
        {listQuery.error ? (
          <Text style={styles.error}>{t("error.list", { error: messageOf(listQuery.error) })}</Text>
        ) : null}
        {scan && !scan.rootExists ? (
          <Text style={styles.warn}>{t("list.missing")}</Text>
        ) : null}
        {scan && runs.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.body}>{t("list.empty", { root: scan.runRoot })}</Text>
            <Text style={styles.muted}>{t("list.emptyHint")}</Text>
          </View>
        ) : null}
        {scan?.warnings.map((warning) => (
          <Text key={warning} style={styles.warn}>
            {warning}
          </Text>
        ))}
        {runs.map((run) => (
          <RunRow
            key={run.id}
            run={run}
            theme={theme}
            layout={layout}
            selected={run.id === selected}
            onPress={() => onSelect(run.id)}
          />
        ))}
      </ScrollView>
    </View>
  );

  const detailPane = (
    <View style={styles.detail}>
      <ScrollView contentContainerStyle={styles.detailContent}>
        {layout.compact ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t("list.back")}
            onPress={() => onSelect(null)}
            style={styles.backRow}
          >
            <Text style={styles.link}>{`‹ ${t("list.back")}`}</Text>
          </Pressable>
        ) : null}
        {summary ? (
          <RunHeader summary={summary} theme={theme} layout={layout} locale={locale} />
        ) : (
          <Text style={styles.muted}>{t("list.scanning")}</Text>
        )}
        {followQuery.error ? (
          <Text style={styles.error}>
            {t("detail.loadError", { error: messageOf(followQuery.error) })}
          </Text>
        ) : null}
        {followQuery.data && !followQuery.data.found ? (
          <Text style={styles.warn}>{t("list.missing")}</Text>
        ) : null}
        <EventTail
          events={followQuery.data?.events ?? []}
          answerTail={followQuery.data?.answerTail ?? null}
          tailLines={values.tailLines}
          theme={theme}
          layout={layout}
          locale={locale}
        />
        {detailQuery.data?.paths.length ? (
          <FilePaths
            paths={detailQuery.data.paths}
            theme={theme}
            layout={layout}
            onCopy={(path) => {
              void copyText(path)
                .then(() => toast.show(t("detail.copied"), { variant: "success" }))
                .catch(() => toast.error(t("detail.copyFailed")));
            }}
          />
        ) : null}
        <Text style={styles.faint}>
          {host.label}
          {summary?.lastEventAt ? ` · ${t("detail.updated", { time: clockOf(summary.lastEventAt, locale) ?? "" })}` : ""}
        </Text>
      </ScrollView>
    </View>
  );

  return (
    <View style={styles.root}>
      {showList ? listPane : null}
      {selected !== null ? detailPane : null}
      {selected === null && !layout.compact ? (
        <View style={styles.detail}>
          <Text style={styles.muted}>{t("list.noSelection")}</Text>
        </View>
      ) : null}
    </View>
  );
}

function RootFacts({
  scan,
  theme,
  layout,
  locale,
}: {
  scan: ListRunsOutput;
  theme: ObserverTheme;
  layout: ObserverLayout;
  locale: string;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  return (
    <>
      <Text style={styles.body} selectable>
        {t("list.root")}: {scan.runRoot}
      </Text>
      <Text style={styles.muted}>{t("list.source", { source: t(sourceKey(scan.rootSource)) })}</Text>
      <Text style={styles.muted}>
        {t("list.count", { count: scan.runs.length })} · {t("list.probe", { probe: scan.probe })}
      </Text>
      <Text style={styles.faint}>
        {t("list.scanned", { time: clockOf(scan.scannedAt, locale) ?? scan.scannedAt })}
      </Text>
    </>
  );
}

function RunRow({
  run,
  theme,
  layout,
  selected,
  onPress,
}: {
  run: RunSummary;
  theme: ObserverTheme;
  layout: ObserverLayout;
  selected: boolean;
  onPress(): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const duration = formatDuration(run.liveness === "running" ? run.elapsedS : run.durationS);
  const cost = formatCost(run.costUsd);
  const counters = counterLine([
    run.turns === null ? null : t("counter.turns", { value: String(run.turns) }),
    run.toolCalls === null ? null : t("counter.tools", { value: String(run.toolCalls) }),
    cost === null ? null : t("counter.cost", { value: cost }),
  ]);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${run.name} ${t(stateKey(run.state))} ${t(livenessKey(run.liveness))}`}
      onPress={onPress}
      style={[styles.row, selected ? styles.rowSelected : null]}
    >
      <View style={styles.rowTop}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {run.name}
        </Text>
        <StateBadge state={run.state} theme={theme} layout={layout} />
        <TimingBadge liveness={run.liveness} theme={theme} layout={layout} />
      </View>
      <Text style={styles.muted} numberOfLines={1}>
        {counterLine([
          duration === null
            ? null
            : `${run.liveness === "running" ? t("detail.elapsed") : t("detail.duration")} ${duration}`,
          counters === "" ? t("counter.none") : counters,
          run.model,
        ])}
      </Text>
      {run.currentTool ? (
        <Text style={styles.body} numberOfLines={1}>
          {t("detail.currentTool")}: {run.currentTool}
          {run.currentToolIntent ? ` · ${run.currentToolIntent}` : ""}
        </Text>
      ) : null}
      {run.liveness === "stale" ? (
        <Text style={styles.warn} numberOfLines={2}>
          {t("warning.stale")}
        </Text>
      ) : null}
      {run.eventsTruncated ? (
        <Text style={styles.warn} numberOfLines={2}>
          {t("warning.log-truncated")}
        </Text>
      ) : null}
      <Text style={styles.faint} numberOfLines={1}>
        {run.id} · {formatBytes(run.eventsBytes) ?? "0 B"}
      </Text>
    </Pressable>
  );
}

function RunHeader({
  summary,
  theme,
  layout,
  locale,
}: {
  summary: RunSummary;
  theme: ObserverTheme;
  layout: ObserverLayout;
  locale: string;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const duration = formatDuration(
    summary.liveness === "running" ? summary.elapsedS : summary.durationS,
  );
  const cost = formatCost(summary.costUsd);
  const facts: Array<[string, string | null]> = [
    [t("detail.model"), summary.model],
    [t("detail.thinking"), summary.thinking],
    [t("detail.maxTime"), summary.maxTime],
    [t("detail.started"), clockOf(summary.startedAt, locale)],
    [t("detail.ended"), clockOf(summary.endedAt, locale)],
    [summary.liveness === "running" ? t("detail.elapsed") : t("detail.duration"), duration],
    [t("detail.exit"), summary.exitCode === null ? null : String(summary.exitCode)],
    [
      t("detail.currentTool"),
      summary.currentTool
        ? `${summary.currentTool}${summary.currentToolIntent ? ` · ${summary.currentToolIntent}` : ""}`
        : t("detail.noTool"),
    ],
    [t("detail.events"), formatBytes(summary.eventsBytes)],
    [
      t("detail.answer"),
      summary.answerChars === null ? null : t("counter.answer", { value: String(summary.answerChars) }),
    ],
    [t("detail.session"), summary.sessionId],
    [
      t("detail.pids"),
      counterLine([
        summary.pids.pid === null ? null : `launcher ${summary.pids.pid}`,
        summary.pids.agentPid === null ? null : `agent ${summary.pids.agentPid}`,
      ]),
    ],
  ];
  const counters = counterLine([
    summary.turns === null ? null : t("counter.turns", { value: String(summary.turns) }),
    summary.toolCalls === null ? null : t("counter.tools", { value: String(summary.toolCalls) }),
    cost === null ? null : t("counter.cost", { value: cost }),
    summary.countersFrom === "state" ? t("counter.fromState") : null,
    summary.countersFrom === "events" ? t("counter.fromEvents") : null,
    summary.countersPartial ? t("counter.partial") : null,
  ]);
  return (
    <View style={styles.header}>
      <Text style={styles.title}>{summary.name}</Text>
      <View style={styles.rowTop}>
        <StateBadge state={summary.state} theme={theme} layout={layout} />
        <TimingBadge liveness={summary.liveness} theme={theme} layout={layout} />
        <Text style={styles.faint}>{summary.id}</Text>
      </View>
      <Text style={styles.body}>{counters}</Text>
      {summary.liveness === "stale" || summary.liveness === "unknown" ? (
        <Text style={styles.warn}>{t("warning.stale")}</Text>
      ) : null}
      {summary.warnings.map((warning) => (
        <Text key={warning} style={styles.warn}>
          {t(warningKey(warning))}
        </Text>
      ))}
      {summary.lastError ? (
        <Text style={styles.warn} numberOfLines={3}>
          {t("detail.lastError")}: {summary.lastError}
        </Text>
      ) : null}
      <View style={styles.facts}>
        {facts
          .filter(([, value]) => value !== null && value !== "")
          .map(([label, value]) => (
            <View key={label} style={styles.fact}>
              <Text style={styles.factLabel}>{label}</Text>
              <Text style={styles.factValue} selectable>
                {value}
              </Text>
            </View>
          ))}
      </View>
      <Text style={styles.muted} selectable>
        {summary.runDir}
      </Text>
    </View>
  );
}

function EventTail({
  events,
  answerTail,
  tailLines,
  theme,
  layout,
  locale,
}: {
  events: RunEvent[];
  answerTail: string | null;
  tailLines: number;
  theme: ObserverTheme;
  layout: ObserverLayout;
  locale: string;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  return (
    <>
      <Text style={styles.sectionTitle}>
        {t("detail.eventTail")} · {t("detail.tailLines", { count: tailLines })}
      </Text>
      <View style={styles.card}>
        {events.length === 0 ? (
          <Text style={styles.muted}>{t("detail.noEvents")}</Text>
        ) : (
          events.map((event, index) => (
            <View key={`${index}:${event.type}:${event.at ?? ""}`} style={styles.eventRow}>
              <Text style={styles.eventClock}>{eventClockOf(event.at, locale) ?? "--:--:--"}</Text>
              <Text style={[styles.eventType, { color: eventColor(event, theme) }]}>
                {event.type}
                {event.tool ? ` · ${event.tool}` : ""}
              </Text>
              {event.intent ?? event.detail ? (
                <Text style={styles.eventDetail} numberOfLines={2}>
                  {event.intent ?? event.detail}
                </Text>
              ) : null}
            </View>
          ))
        )}
      </View>
      <Text style={styles.sectionTitle}>{t("detail.answerTail")}</Text>
      <View style={styles.card}>
        {answerTail ? (
          <Text style={styles.mono} selectable>
            {answerTail}
          </Text>
        ) : (
          <Text style={styles.muted}>{t("detail.noAnswer")}</Text>
        )}
      </View>
    </>
  );
}

function FilePaths({
  paths,
  theme,
  layout,
  onCopy,
}: {
  paths: { label: string; path: string; exists: boolean; bytes: number | null }[];
  theme: ObserverTheme;
  layout: ObserverLayout;
  onCopy(path: string): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  return (
    <>
      <Text style={styles.sectionTitle}>{t("detail.files")}</Text>
      {paths.map((path) => (
        <Pressable
          key={path.label}
          accessibilityRole="button"
          accessibilityLabel={`${t("detail.copyPath")}: ${path.path}`}
          onPress={() => onCopy(path.path)}
          style={styles.card}
        >
          <View style={styles.pathRow}>
            <Text style={styles.pathLabel}>{path.label}</Text>
            <Text style={styles.pathValue} numberOfLines={1}>
              {path.exists ? (formatBytes(path.bytes) ?? "") : t("settingsScreen.no")}
            </Text>
          </View>
          <Text style={styles.faint} numberOfLines={2}>
            {path.path}
          </Text>
        </Pressable>
      ))}
    </>
  );
}

function StateBadge({
  state,
  theme,
  layout,
}: {
  state: RunState;
  theme: ObserverTheme;
  layout: ObserverLayout;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const color = stateColor(state, theme);
  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Text style={[styles.badgeText, { color: theme.colors.foreground }]}>{t(stateKey(state))}</Text>
    </View>
  );
}

function TimingBadge({
  liveness,
  theme,
  layout,
}: {
  liveness: RunLiveness;
  theme: ObserverTheme;
  layout: ObserverLayout;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  return (
    <View style={[styles.badge, { borderColor: livenessColor(liveness, theme) }]}>
      <Text style={[styles.badgeText, { color: theme.colors.foregroundMuted }]}>
        {t(livenessKey(liveness))}
      </Text>
    </View>
  );
}

function useTabSelection(tab: PluginTab): [{ selected: string | null }, (next: { selected: string | null }) => void] {
  const stored = tab.state;
  const selection = useMemo(() => parseSelection(stored), [stored]);
  return useMemo(
    () => [
      selection,
      (next: { selected: string | null }) => {
        tab.setState(next);
      },
    ],
    [selection, tab],
  );
}

export function parseSelection(value: unknown): { selected: string | null } {
  if (typeof value !== "object" || value === null || !("selected" in value)) return { selected: null };
  const selected = value.selected;
  return { selected: typeof selected === "string" ? selected : null };
}

export type StateKey =
  | "state.running"
  | "state.done"
  | "state.killed"
  | "state.failed"
  | "state.unknown";
export type LivenessKey =
  | "liveness.running"
  | "liveness.settled"
  | "liveness.stale"
  | "liveness.unknown";
export type SourceKey =
  | "source.setting"
  | "source.env"
  | "source.xdg"
  | "source.home"
  | "source.localappdata"
  | "source.default";
export type WarningKey =
  | "warning.stale"
  | "warning.state-missing"
  | "warning.state-unreadable"
  | "warning.no-lock"
  | "warning.no-pids"
  | "warning.liveness-unknown"
  | "warning.log-unreadable"
  | "warning.log-truncated";

const STATE_KEYS: Record<RunState, StateKey> = {
  running: "state.running",
  done: "state.done",
  killed: "state.killed",
  failed: "state.failed",
  unknown: "state.unknown",
};

const LIVENESS_KEYS: Record<RunLiveness, LivenessKey> = {
  running: "liveness.running",
  settled: "liveness.settled",
  stale: "liveness.stale",
  unknown: "liveness.unknown",
};

const SOURCE_KEYS: Record<RunRootSource, SourceKey> = {
  setting: "source.setting",
  env: "source.env",
  xdg: "source.xdg",
  home: "source.home",
  localappdata: "source.localappdata",
  default: "source.default",
};

const WARNING_KEYS: Record<RunWarning, WarningKey> = {
  "state-missing": "warning.state-missing",
  "state-unreadable": "warning.state-unreadable",
  "no-lock": "warning.no-lock",
  "no-pids": "warning.no-pids",
  "liveness-unknown": "warning.liveness-unknown",
  "log-unreadable": "warning.log-unreadable",
  "log-truncated": "warning.log-truncated",
};

export function stateKey(state: RunState): StateKey {
  return STATE_KEYS[state];
}

export function livenessKey(liveness: RunLiveness): LivenessKey {
  return LIVENESS_KEYS[liveness];
}

export function sourceKey(source: RunRootSource): SourceKey {
  return SOURCE_KEYS[source];
}

export function warningKey(warning: RunWarning): WarningKey {
  return WARNING_KEYS[warning];
}

function stateColor(state: RunState, theme: ObserverTheme): string {
  if (state === "running") return theme.colors.accent;
  if (state === "done") return theme.colors.statusSuccess;
  if (state === "killed") return theme.colors.statusWarning;
  if (state === "failed") return theme.colors.statusDanger;
  return theme.colors.foregroundMuted;
}

function livenessColor(liveness: RunLiveness, theme: ObserverTheme): string {
  if (liveness === "running") return theme.colors.statusSuccess;
  if (liveness === "stale") return theme.colors.statusWarning;
  return theme.colors.foregroundMuted;
}

function eventColor(event: RunEvent, theme: ObserverTheme): string {
  if (event.type === "truncated") return theme.colors.statusWarning;
  if (event.type.includes("error")) return theme.colors.statusDanger;
  if (event.type.includes("tool")) return theme.colors.accent;
  return theme.colors.foreground;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
