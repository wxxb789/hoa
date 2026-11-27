import type { PluginScreenProps } from "@getpaseo/plugin/client";
import { useRpc, useTranslation } from "@getpaseo/plugin/client";
import { Icon, Markdown, ScrollView, copyText, useToast } from "@getpaseo/plugin/client/ui";
import { useQuery } from "@tanstack/react-query";
import { memo, useMemo } from "react";
import { Pressable, Text, View } from "react-native";
import { followRun, runPaths, type FollowRunOutput, type RunEvent, type RunPath, type RunSummary } from "../shared/runs";
import { FactsCard } from "./facts";
import { clockOf, counterLine, countersLine, errorText, eventClockOf, formatBytes, formatDuration } from "./format";
import { counterSourceKey, eventColor, eventFailureKey, warningKey } from "./labels";
import { messages } from "./messages";
import { ModelCard } from "./model-card";
import { LivenessBadge, StateBadge } from "./status-strip";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";

export function RunDetailPane({
  theme,
  layout,
  host,
  navigation,
  selected,
  tailLines,
  pollIntervalMs,
  onBack,
}: Pick<PluginScreenProps, "theme" | "layout" | "host" | "navigation"> & {
  selected: string;
  tailLines: number;
  pollIntervalMs: number;
  onBack(): void;
}) {
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const toast = useToast();
  const follow = useRpc(followRun);
  const paths = useRpc(runPaths);

  const followQuery = useQuery({
    queryKey: ["gddRuns", "follow", selected, tailLines],
    queryFn: () => follow({ id: selected, tailLines: tailLines }),
    refetchInterval: pollIntervalMs,
  });
  // The path list does not depend on the tail length, so changing it does not invalidate this.
  const pathsQuery = useQuery({
    queryKey: ["gddRuns", "paths", selected],
    queryFn: () => paths({ id: selected }),
    staleTime: 30_000,
  });

  const summary = followQuery.data?.summary ?? null;
  const lineage = summary?.lineage ?? followQuery.data?.lineage;
  const initiatingAgentId = lineage?.parentAgentId;
  const gone = followQuery.data !== undefined && !followQuery.data.found;

  return (
    <View style={styles.detail}>
      <ScrollView contentContainerStyle={styles.detailContent}>
        {layout.compact ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t("list.back")}
            onPress={onBack}
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
          tailLines={tailLines}
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
}

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
