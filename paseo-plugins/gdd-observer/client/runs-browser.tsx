import type { PluginScreenProps } from "@getpaseo/plugin/client";
import { useRpc, useSettings, useTranslation } from "@getpaseo/plugin/client";
import {
  FlatList,
  Icon,
  Loading,
  Markdown,
  ScrollView,
  copyText,
  useToast,
} from "@getpaseo/plugin/client/ui";
import { useQuery } from "@tanstack/react-query";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";
import {
  followRun,
  type FollowRunOutput,
  type ListRunsOutput,
  type RunEvent,
  type RunPath,
  type RunStats,
  type RunSummary,
  runPaths,
} from "../shared/runs";
import { OBSERVER_DEFAULTS, observerSettings } from "../shared/settings";
import { summarizeRuns } from "../shared/stats";
import {
  clockOf,
  counterLine,
  countersLine,
  errorText,
  eventClockOf,
  firstUsage,
  formatBytes,
  formatDuration,
  usageLabel,
} from "./format";
import { FactsCard } from "./facts";
import {
  counterSourceKey,
  eventColor,
  eventFailureKey,
  livenessKey,
  sourceKey,
  stateKey,
  warningKey,
} from "./labels";
import { messages } from "./messages";
import { ModelCard, ModelChip } from "./model-card";
import { LivenessBadge, StateBadge, StatusStrip } from "./status-strip";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";
import { useRunsListQuery } from "./use-runs-query";

export function RunsScreen({ theme, layout, host, params, navigation }: PluginScreenProps) {
  const runId = params.runId || null;
  const parentAgentId = params.parentAgentId || null;
  const [selected, onSelect] = useState(runId);
  const [agentFilter, setAgentFilter] = useState(parentAgentId);
  useEffect(() => onSelect(runId), [runId]);
  useEffect(() => setAgentFilter(parentAgentId), [parentAgentId]);
  const clearAgentFilter = useCallback(() => setAgentFilter(null), []);
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const toast = useToast();
  const settings = useSettings(observerSettings);
  const values = settings.status === "ready" ? settings.values : OBSERVER_DEFAULTS;
  const follow = useRpc(followRun);
  const paths = useRpc(runPaths);

  const followQuery = useQuery({
    queryKey: ["gddRuns", "follow", selected, values.tailLines],
    queryFn: () => follow({ id: selected ?? "", tailLines: values.tailLines }),
    enabled: selected !== null,
    refetchInterval: values.pollIntervalMs,
  });
  // The path list does not depend on the tail length, so changing it does not invalidate this.
  const pathsQuery = useQuery({
    queryKey: ["gddRuns", "paths", selected],
    queryFn: () => paths({ id: selected ?? "" }),
    enabled: selected !== null,
    staleTime: 30_000,
  });

  const summary = followQuery.data?.summary ?? null;
  const lineage = summary?.lineage ?? followQuery.data?.lineage;
  const initiatingAgentId = lineage?.parentAgentId;
  const gone = followQuery.data !== undefined && !followQuery.data.found;

  const listPane = (
    // The list owns the shared scan as its own component: compact mode unmounts it while a run's
    // detail covers it, so a hidden list holds no scan observer and joins no polling election.
    // Returning to it then re-runs the mount behaviour — an immediate refresh when it is the only
    // watcher, reuse of an already active scan otherwise.
    <RunsListPane
      theme={theme}
      layout={layout}
      locale={locale}
      hostLabel={host.label}
      agentFilter={agentFilter}
      clearAgentFilter={clearAgentFilter}
      selected={selected}
      pollIntervalMs={values.pollIntervalMs}
      onSelect={onSelect}
    />
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
            <Icon name="ChevronLeft" size={14} color={theme.colors.accent} />
            <Text style={styles.backLabel}>{t("list.back")}</Text>
          </Pressable>
        ) : null}
        {followQuery.error ? (
          <Text style={styles.error}>
            {t("detail.loadError", { error: errorText(followQuery.error) })}
          </Text>
        ) : null}
        {gone ? (
          <Text style={styles.warn}>{t("detail.gone")}</Text>
        ) : summary ? (
          <RunSummaryHeader summary={summary} theme={theme} layout={layout} locale={locale} />
        ) : (
          <Text style={styles.muted}>{t("list.scanning")}</Text>
        )}
        {summary ? (
          <RunLineageCard
            lineage={lineage}
            theme={theme}
            layout={layout}
            openAgent={initiatingAgentId && navigation?.openAgent
              ? () => navigation.openAgent({ agentId: initiatingAgentId, serverId: host.id })
              : undefined}
          />
        ) : null}
        <EventTail
          events={followQuery.data?.events ?? []}
          answerTail={followQuery.data?.answerTail ?? null}
          tailLines={values.tailLines}
          theme={theme}
          layout={layout}
          locale={locale}
        />
        {summary ? <ModelCard model={summary.model} theme={theme} layout={layout} /> : null}
        {summary ? <RunFacts summary={summary} theme={theme} layout={layout} locale={locale} /> : null}
        {pathsQuery.data?.paths.length ? (
          <FilePaths
            paths={pathsQuery.data.paths}
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
          {summary?.lastEventAt
            ? ` · ${t("detail.updated", { time: clockOf(summary.lastEventAt, locale) ?? "" })}`
            : ""}
        </Text>
      </ScrollView>
    </View>
  );

  return (
    <View style={styles.root}>
      {!layout.compact || selected === null ? listPane : null}
      {selected !== null ? (
        detailPane
      ) : !layout.compact ? (
        <View style={styles.detailEmpty}>
          <EmptyBlock
            title={t("list.noSelectionTitle")}
            body={t("list.noSelection")}
            hint={null}
            theme={theme}
            layout={layout}
          />
        </View>
      ) : null}
    </View>
  );
}

/**
 * The windowed run list and the shared scan behind it. Keeping it a separate component lets
 * compact mode unmount the scan together with the list it feeds: only a mounted pane observes,
 * polls, or fetches the scan, and a detail view's own `runs.follow` polling does not re-render it.
 */
const RunsListPane = memo(function RunsListPane({
  theme,
  layout,
  locale,
  hostLabel,
  agentFilter,
  clearAgentFilter,
  selected,
  pollIntervalMs,
  onSelect,
}: {
  theme: ObserverTheme;
  layout: ObserverLayout;
  locale: string;
  hostLabel: string;
  agentFilter: string | null;
  clearAgentFilter(): void;
  selected: string | null;
  pollIntervalMs: number;
  onSelect(id: string): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  // Shares the scan with the settings screen: this surface asks for its configured cadence and the
  // polling election uses whichever mounted surface asked for the fastest one.
  const listQuery = useRunsListQuery(pollIntervalMs);
  const scan = listQuery.data;
  const population = scan?.runs;
  const filtered = useMemo(() => {
    if (population === undefined || agentFilter === null) return null;
    const runs = population.filter((run) => run.lineage?.parentAgentId === agentFilter);
    return { runs, stats: summarizeRuns(runs) };
  }, [population, agentFilter]);
  const keyExtractor = useCallback((run: RunSummary) => run.id, []);
  // Stable row props let `RunRow`'s memo skip every run a delta did not touch.
  const renderItem = useCallback(
    ({ item }: { item: RunSummary }) => (
      <RunRow
        run={item}
        theme={theme}
        layout={layout}
        selected={item.id === selected}
        onSelect={onSelect}
      />
    ),
    [theme, layout, selected, onSelect],
  );
  return (
    <View style={layout.compact ? styles.listCompact : styles.listWide}>
      {scan === undefined ? (
        <View style={styles.listLoading}>
          {listQuery.error ? (
            <Text style={styles.error}>
              {t("error.list", { error: errorText(listQuery.error) })}
            </Text>
          ) : (
            <Loading />
          )}
        </View>
      ) : (
        // The host list owns virtualization: rows mount in a bounded window around the viewport
        // instead of every run in the scan. Run ids stay the row keys, and the header, warnings
        // and empty guidance ride in their list slots so their content and order do not change.
        <FlatList
          data={filtered?.runs ?? scan.runs}
          keyExtractor={keyExtractor}
          renderItem={renderItem}
          ListHeaderComponent={
            <>
              <ListHeader
                scan={scan}
                stats={filtered?.stats ?? scan.stats}
                theme={theme}
                layout={layout}
                locale={locale}
                hostLabel={hostLabel}
                agentFilter={agentFilter}
                clearAgentFilter={clearAgentFilter}
              />
              {!scan.rootExists ? (
                <View style={styles.warningCard}>
                  <Text style={styles.warningRow}>{t("list.missing")}</Text>
                </View>
              ) : null}
              {scan.warnings.map((warning) => (
                <Text key={warning} style={styles.warn}>
                  {warning}
                </Text>
              ))}
            </>
          }
          ListEmptyComponent={
            <EmptyBlock
              title={t("list.emptyTitle")}
              body={agentFilter === null ? t("list.empty", { root: scan.runRoot }) : t("list.emptyAgent")}
              hint={agentFilter === null ? t("list.emptyHint") : null}
              theme={theme}
              layout={layout}
            />
          }
          contentContainerStyle={styles.listContent}
          initialNumToRender={10}
          maxToRenderPerBatch={10}
          windowSize={3}
        />
      )}
    </View>
  );
});

const ListHeader = memo(function ListHeader({
  scan,
  stats,
  theme,
  layout,
  locale,
  hostLabel,
  agentFilter,
  clearAgentFilter,
}: {
  scan: ListRunsOutput;
  stats: RunStats;
  theme: ObserverTheme;
  layout: ObserverLayout;
  locale: string;
  hostLabel: string;
  agentFilter: string | null;
  clearAgentFilter(): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  return (
    <View style={styles.listHeader}>
      <View style={styles.listTitleRow}>
        <Text style={styles.heading}>{t("list.runs")}</Text>
        <Text style={styles.headingMeta} numberOfLines={1}>
          {t("list.scanned", { time: clockOf(scan.scannedAt, locale) ?? scan.scannedAt })}
        </Text>
      </View>
      <Text style={styles.muted} numberOfLines={1}>{hostLabel}</Text>
      {agentFilter === null ? null : (
        <View style={styles.card}>
          <Text style={styles.muted} numberOfLines={1}>{t("list.agentFilter", { agent: agentFilter })}</Text>
          <Pressable accessibilityRole="button" onPress={clearAgentFilter} style={styles.backRow}>
            <Text style={styles.backLabel}>{t("list.clearAgentFilter")}</Text>
          </Pressable>
        </View>
      )}
      <StatusStrip stats={stats} theme={theme} layout={layout} />
      <Text style={styles.faint} numberOfLines={2} selectable>
        {t("list.root")}: {scan.runRoot}
      </Text>
      <Text style={styles.faint} numberOfLines={1}>
        {t("list.source", { source: t(sourceKey(scan.rootSource)) })} ·{" "}
        {t("list.probe", { probe: scan.probe })}
      </Text>
    </View>
  );
});

const RunRow = memo(function RunRow({
  run,
  theme,
  layout,
  selected,
  onSelect,
}: {
  run: RunSummary;
  theme: ObserverTheme;
  layout: ObserverLayout;
  selected: boolean;
  onSelect(id: string): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const running = run.liveness === "running";
  const duration = formatDuration(run.finalized ? run.durationS ?? run.elapsedS : run.elapsedS);
  const counters = countersLine(run, (key, value) => t(key, { value }), locale);
  const disagreement = run.liveness === "stale" || (!run.finalized && run.liveness === "unknown") ? run.liveness : null;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={t("a11y.run", {
        name: run.name,
        state: t(stateKey(run.state)),
        liveness: t(livenessKey(run.liveness)),
        model: usageLabel(firstUsage(run.model)) ?? run.model.requested ?? t("model.none"),
      })}
      onPress={() => onSelect(run.id)}
      style={[styles.row, selected ? styles.rowSelected : null]}
    >
      <View style={styles.rowTop}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {run.name}
        </Text>
        <StateBadge state={run.state} theme={theme} layout={layout} />
        {disagreement ? (
          <LivenessBadge liveness={disagreement} theme={theme} layout={layout} />
        ) : null}
      </View>
      <View style={styles.rowMeta}>
        <ModelChip model={run.model} theme={theme} layout={layout} />
        {duration ? (
          <Text style={styles.faint}>
            {running ? t("detail.elapsed") : t("detail.duration")} {duration}
          </Text>
        ) : null}
      </View>
      <Text style={styles.muted} numberOfLines={2}>
        {counters === "" ? t("counter.none") : counters}
      </Text>
      {run.currentTool ? (
        <View style={styles.rowMeta}>
          <Icon name="Terminal" size={11} color={theme.colors.accent} />
          <Text style={styles.muted} numberOfLines={1}>
            {run.currentTool}
            {run.currentToolIntent ? ` · ${run.currentToolIntent}` : ""}
          </Text>
        </View>
      ) : null}
      {run.liveness === "stale" ? <Text style={styles.warn}>{t("warning.stale")}</Text> : null}
      {run.eventsTruncated ? (
        <Text style={styles.faint}>{t("warning.log-truncatedShort")}</Text>
      ) : null}
    </Pressable>
  );
});

function RunSummaryHeader({
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
  const running = summary.liveness === "running";
  const duration = formatDuration(summary.elapsedS);
  const counters = counterLine([
    duration === null ? null : `${running ? t("detail.elapsed") : t("detail.duration")} ${duration}`,
    countersLine(summary, (key, value) => t(key, { value }), locale),
  ]);
  const countersSource = counterSourceKey(summary.countersFrom);
  const warnings = summary.warnings.filter((warning) => warning !== "log-truncated");
  return (
    <View style={styles.header}>
      <Text style={styles.title}>{summary.name}</Text>
      <View style={styles.rowTop}>
        <StateBadge state={summary.state} theme={theme} layout={layout} />
        <LivenessBadge liveness={summary.liveness} theme={theme} layout={layout} />
        <Text style={styles.faint} selectable>
          {summary.id}
        </Text>
      </View>
      <Text style={styles.body}>{counters}</Text>
      <Text style={styles.muted}>
        {counterLine([
          countersSource === null ? null : t(countersSource),
          summary.countersPartial ? t("counter.partial") : null,
          summary.eventsTruncated ? t("warning.log-truncatedShort") : null,
        ])}
      </Text>
      {summary.currentTool ? (
        <View style={styles.rowMeta}>
          <Icon name="Terminal" size={12} color={theme.colors.accent} />
          <Text style={styles.body}>
            {summary.currentTool}
            {summary.currentToolIntent ? ` · ${summary.currentToolIntent}` : ""}
          </Text>
        </View>
      ) : null}
      {summary.lastError ? (
        <View style={styles.warningCard}>
          <Text style={styles.warningRow}>
            {t("detail.lastError")}: {summary.lastError}
          </Text>
        </View>
      ) : null}
      {warnings.length > 0 ? (
        <View style={styles.warningCard}>
          <View style={styles.cardHeader}>
            <Icon name="Gauge" size={13} color={theme.colors.statusWarning} />
            <Text style={styles.cardTitle}>{t("detail.warnings")}</Text>
          </View>
          {warnings.map((warning) => (
            <Text key={warning} style={styles.warningRow}>
              {t(warningKey(warning))}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function RunFacts({
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
  const facts: Array<[string, string | null]> = [
    [t("detail.started"), clockOf(summary.startedAt, locale)],
    [t("detail.ended"), clockOf(summary.endedAt, locale)],
    [t("detail.maxTime"), summary.maxTime],
    [t("detail.exit"), summary.exitCode === null ? null : String(summary.exitCode)],
    [t("detail.events"), formatBytes(summary.eventsBytes)],
    [
      t("detail.answer"),
      summary.answerChars === null
        ? null
        : t("counter.answer", { value: String(summary.answerChars) }),
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
  return (
    <FactsCard
      title={t("detail.run")}
      icon="Activity"
      facts={facts}
      theme={theme}
      layout={layout}
    >
      <Text style={styles.muted} selectable>
        {summary.runDir}
      </Text>
    </FactsCard>
  );
}

/**
 * Dispatch context for one found run: the GDD goal and stage it was launched for and, when the
 * dispatch came from a Paseo agent, that agent's id. Older runs and direct adapter starts have
 * none; the run's own session and pids are never shown as a substitute.
 */
function RunLineageCard({
  lineage,
  theme,
  layout,
  openAgent,
}: {
  lineage: FollowRunOutput["lineage"];
  theme: ObserverTheme;
  layout: ObserverLayout;
  openAgent?: () => void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  if (!lineage) {
    return (
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Icon name="GitBranch" size={13} color={theme.colors.foregroundMuted} />
          <Text style={styles.cardTitle}>{t("detail.lineage")}</Text>
        </View>
        <Text style={styles.muted}>{t("detail.lineageMissing")}</Text>
      </View>
    );
  }
  return (
    <FactsCard
      title={t("detail.lineage")}
      icon="GitBranch"
      theme={theme}
      layout={layout}
      facts={[
        [t("detail.lineageGoal"), lineage.goal],
        [t("detail.lineageStage"), lineage.stage],
        [t("detail.lineageAgent"), lineage.parentAgentId ?? t("detail.lineageAgentMissing")],
      ]}
    >
      {openAgent ? (
        <Pressable accessibilityRole="button" onPress={openAgent} style={styles.backRow}>
          <Text style={styles.backLabel}>{t("detail.openInitiatingAgent")}</Text>
        </Pressable>
      ) : null}
    </FactsCard>
  );
}

const EventTail = memo(function EventTail({
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
  const keys = useMemo(() => eventKeys(events), [events]);
  return (
    <>
      <Text style={styles.sectionTitle}>
        {t("detail.eventTail")} · {t("detail.tailLines", { count: tailLines })}
      </Text>
      <View style={styles.card}>
        {events.length === 0 ? (
          <Text style={styles.muted}>{t("detail.noEvents")}</Text>
        ) : (
          events.map((event, index) => {
            const color = eventColor(event, theme);
            const clock = eventClockOf(event.at, locale);
            const failure = eventFailureKey(event.type);
            const title = failure ? counterLine([event.tool, t(failure)])
              : event.role === "assistant" ? t("detail.activityAssistant")
              : event.type === "truncated" ? t("detail.activityTruncated") : event.tool ?? event.type;
            const detail = event.intent ?? event.detail;
            return (
              <View key={keys[index]} style={styles.eventRow}>
                <View style={[styles.eventTrack, { backgroundColor: color }]} />
                {clock ? <Text style={styles.eventClock}>{clock}</Text> : null}
                <View style={styles.eventBody}>
                  <Text style={[styles.eventType, { color }]}>{title}</Text>
                  {detail ? (
                    <Text
                      style={[styles.eventDetail, event.role === "assistant" ? styles.body : null]}
                      numberOfLines={event.role === "assistant" ? 4 : 3}
                    >
                      {detail}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })
        )}
      </View>
      <Text style={styles.sectionTitle}>{t("detail.answerTail")}</Text>
      <View style={styles.card}>
        {answerTail ? (
          <>
            <Text style={styles.note}>{t("detail.answerFragment")}</Text>
            <Markdown>{answerTail}</Markdown>
          </>
        ) : (
          <Text style={styles.muted}>{t("detail.noAnswer")}</Text>
        )}
      </View>
    </>
  );
});

function FilePaths({
  paths,
  theme,
  layout,
  onCopy,
}: {
  paths: RunPath[];
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
            <View style={styles.rowMeta}>
              <Icon name="FileText" size={12} color={theme.colors.foregroundMuted} />
              <Text style={styles.pathLabel}>{path.label}</Text>
            </View>
            <Text style={styles.pathValue}>
              {path.exists ? (formatBytes(path.bytes) ?? "") : t("settingsScreen.no")}
            </Text>
          </View>
          <Text style={styles.faint} numberOfLines={2} selectable>
            {path.path}
          </Text>
        </Pressable>
      ))}
    </>
  );
}

/**
 * Keys for a sliding window: an event's own content plus how many identical events precede it, so
 * appending one event keeps the rows already on screen mounted instead of renumbering them all.
 */
export function eventKeys(events: readonly RunEvent[]): string[] {
  const seen = new Map<string, number>();
  return events.map((event) => {
    const content = [
      event.at ?? "",
      event.type,
      event.tool ?? "",
      event.intent ?? "",
      event.detail ?? "",
    ].join("|");
    const occurrence = seen.get(content) ?? 0;
    seen.set(content, occurrence + 1);
    return `${content}#${occurrence}`;
  });
}

function EmptyBlock({
  title,
  body,
  hint,
  theme,
  layout,
}: {
  title: string;
  body: string;
  hint: string | null;
  theme: ObserverTheme;
  layout: ObserverLayout;
}) {
  const styles = useObserverStyles(theme, layout);
  return (
    <View style={styles.emptyBlock}>
      <Icon name="Activity" size={20} color={theme.colors.foregroundMuted} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.muted}>{body}</Text>
      {hint ? <Text style={styles.note}>{hint}</Text> : null}
    </View>
  );
}

