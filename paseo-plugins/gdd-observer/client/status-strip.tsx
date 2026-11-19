import { useTranslation } from "@getpaseo/plugin/client";
import { Text, View } from "react-native";
import type { RunLiveness, RunState, RunStats } from "../shared/runs";
import { counterLine, formatCost, formatCount } from "./format";
import { STATE_ORDER, livenessColor, livenessKey, stateColor, stateKey } from "./labels";
import { messages } from "./messages";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";

type StatusProps = { theme: ObserverTheme; layout: ObserverLayout };

export function StatusStrip({ stats, theme, layout }: StatusProps & { stats: RunStats }) {
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const live = stats.byLiveness.running;
  const totals =
    stats.countedRuns === 0
      ? t("stats.noCounters")
      : counterLine([
          t("counter.turns", { value: formatCount(stats.turns, locale) }),
          t("counter.tools", { value: formatCount(stats.toolCalls, locale) }),
          formatCost(stats.costUsd),
        ]);
  return (
    <View style={styles.statStrip}>
      <DistributionBar stats={stats} theme={theme} layout={layout} />
      <View style={styles.statHeadline}>
        <Text style={styles.statHeadlineValue}>{t("list.count", { count: stats.total })}</Text>
        {live > 0 ? (
          <Text style={[styles.statHeadlineState, { color: livenessColor("running", theme) }]}>
            {t("stats.live", { count: live })}
          </Text>
        ) : null}
        {stats.byLiveness.stale > 0 ? (
          <Text style={[styles.statHeadlineState, { color: livenessColor("stale", theme) }]}>
            {t("stats.stale", { count: stats.byLiveness.stale })}
          </Text>
        ) : null}
      </View>
      <View style={styles.statLegend}>
        {STATE_ORDER.map((state) => (
          <Legend
            key={state}
            state={state}
            value={stats.byState[state]}
            theme={theme}
            layout={layout}
          />
        ))}
      </View>
      <Text style={styles.statTotals}>{totals}</Text>
      <Text style={styles.statNote}>
        {counterLine([
          stats.countedRuns === 0
            ? null
            : t("stats.reported", { count: stats.countedRuns, total: stats.total }),
          stats.partialRuns > 0 ? t("stats.partial", { count: stats.partialRuns }) : null,
          stats.flagged > 0 ? t("stats.flagged", { count: stats.flagged }) : null,
        ])}
      </Text>
    </View>
  );
}

function DistributionBar({ stats, theme, layout }: StatusProps & { stats: RunStats }) {
  const styles = useObserverStyles(theme, layout);
  if (stats.total === 0) return null;
  return (
    <View style={styles.statBar}>
      {STATE_ORDER.filter((state) => stats.byState[state] > 0).map((state) => (
        <View
          key={state}
          style={[
            styles.statBarSegment,
            { flexGrow: stats.byState[state], backgroundColor: stateColor(state, theme) },
          ]}
        />
      ))}
    </View>
  );
}

function Legend({ state, value, theme, layout }: StatusProps & { state: RunState; value: number }) {
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const dim = value === 0;
  return (
    <View style={styles.statLegendItem}>
      <View
        style={[styles.statDot, { backgroundColor: stateColor(state, theme), opacity: dim ? 0.35 : 1 }]}
      />
      <Text style={[styles.statLegendValue, dim ? styles.statLegendDim : null]}>
        {formatCount(value, locale)}
      </Text>
      <Text style={styles.statLegendLabel}>{t(stateKey(state))}</Text>
    </View>
  );
}

/** The one badge shape behind both status badges; the caller decides color and label. */
function Badge({ color, label, theme, layout }: StatusProps & { color: string; label: string }) {
  const styles = useObserverStyles(theme, layout);
  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Text style={[styles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

export function StateBadge({ state, theme, layout }: StatusProps & { state: RunState }) {
  const { t } = useTranslation(messages);
  return (
    <Badge
      color={stateColor(state, theme)}
      label={t(stateKey(state))}
      theme={theme}
      layout={layout}
    />
  );
}

export function LivenessBadge({ liveness, theme, layout }: StatusProps & { liveness: RunLiveness }) {
  const { t } = useTranslation(messages);
  return (
    <Badge
      color={livenessColor(liveness, theme)}
      label={t(livenessKey(liveness))}
      theme={theme}
      layout={layout}
    />
  );
}
