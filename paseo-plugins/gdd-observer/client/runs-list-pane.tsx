import { useTranslation } from "@getpaseo/plugin/client";
import { FlatList, Icon, Loading } from "@getpaseo/plugin/client/ui";
import { memo, useCallback, useMemo } from "react";
import { Pressable, Text, View } from "react-native";
import type { ListRunsOutput, RunStats, RunSummary } from "../shared/runs";
import { summarizeRuns } from "../shared/stats";
import { EmptyBlock } from "./empty-block";
import { clockOf, countersLine, errorText, firstUsage, formatDuration, usageLabel } from "./format";
import { livenessKey, sourceKey, stateKey } from "./labels";
import { messages } from "./messages";
import { ModelChip } from "./model-card";
import { LivenessBadge, StateBadge, StatusStrip } from "./status-strip";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";
import { useRunsListQuery } from "./use-runs-query";

/**
 * The windowed run list and the shared scan behind it. Keeping it a separate component lets
 * compact mode unmount the scan together with the list it feeds: only a mounted pane observes,
 * polls, or fetches the scan, and a detail view's own `runs.follow` polling does not re-render it.
 */
export const RunsListPane = memo(function RunsListPane({
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
