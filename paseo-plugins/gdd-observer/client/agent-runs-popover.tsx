import type { PluginButtonContentProps, PluginClientContext } from "@getpaseo/plugin/client";
import { useRpc, useSettings, useTranslation } from "@getpaseo/plugin/client";
import { ScrollView } from "@getpaseo/plugin/client/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { Pressable, Text, View, type TextStyle, type ViewStyle } from "react-native";
import { followRun, type RunSummary } from "../shared/runs";
import { OBSERVER_DEFAULTS, observerSettings } from "../shared/settings";
import { compactDuration, isActive, runDotColor } from "./composer-presentation";
import { counterLine, countersLine, errorText } from "./format";
import { eventColor, eventFailureKey, livenessKey, stateKey } from "./labels";
import { messages } from "./messages";
import { eventKeys } from "./runs-browser";
import { useRunsListQuery } from "./use-runs-query";

const MAX_WORKERS = 4;
const MAX_GOALS = 6;
const MAX_EVENTS = 6;
const CHIP_COUNT = 5;
const PEEK_TAIL_LINES = 12;

type PopoverProps = Extract<PluginButtonContentProps, { context: "agent" }> & {
  openScreen: PluginClientContext["openScreen"];
};
type PopoverTheme = PluginButtonContentProps["theme"];
type PeekTarget = { id: string; runDir: string };

function goalOf(run: RunSummary): string {
  return run.lineage?.goal ?? run.name;
}

function stageOf(run: RunSummary): string {
  return run.lineage?.stage ?? run.name;
}

function chronologicalRuns(runs: readonly RunSummary[]): RunSummary[] {
  const ordered = runs.slice().reverse();
  if (ordered.every((run) => run.startedAt !== null)) {
    ordered.sort((left, right) => (left.startedAt ?? "").localeCompare(right.startedAt ?? ""));
  }
  return ordered;
}

function stageSummary(runs: readonly RunSummary[]): string {
  const trail: Array<{ stage: string; count: number }> = [];
  for (const run of chronologicalRuns(runs)) {
    const stage = stageOf(run);
    const last = trail[trail.length - 1];
    if (last !== undefined && last.stage === stage) last.count += 1;
    else trail.push({ stage, count: 1 });
  }
  const text = trail.map(({ stage, count }) => (count > 1 ? `${stage}×${count}` : stage)).join(" → ");
  return `${text} ${statusSymbol(runs[0])}`;
}

function statusSymbol(run: RunSummary): string {
  if (run.liveness === "stale") return "◌";
  if (run.liveness === "unknown") return "?";
  switch (run.state) {
    case "running":
      return "●";
    case "done":
      return "✓";
    case "failed":
      return "✗";
    case "killed":
      return "⊘";
    default:
      return "?";
  }
}

function runDuration(run: RunSummary): string | null {
  return compactDuration(run.finalized ? run.durationS ?? run.elapsedS : run.elapsedS);
}

function goalChips(siblings: RunSummary[] | undefined, selectedId: string) {
  if (!siblings || siblings.length < 2) return [];
  const recentIds = new Set(siblings.slice(0, CHIP_COUNT).map((run) => run.id));
  if (!recentIds.has(selectedId)) {
    const kept = siblings.slice(0, CHIP_COUNT - 1).map((run) => run.id);
    recentIds.clear();
    for (const id of kept) recentIds.add(id);
    recentIds.add(selectedId);
  }
  const totals = new Map<string, number>();
  const chips: { id: string; runDir: string; stage: string; index: number }[] = [];
  for (const run of chronologicalRuns(siblings)) {
    const stage = stageOf(run);
    const count = (totals.get(stage) ?? 0) + 1;
    totals.set(stage, count);
    if (recentIds.has(run.id)) {
      chips.push({ id: run.id, runDir: run.runDir, stage, index: count });
    }
  }
  return chips.map((chip) => ({ ...chip, repeat: totals.get(chip.stage)! > 1 }));
}

function answerPreview(answerTail: string): string {
  return answerTail.trimEnd().slice(-400).split(/\r?\n/).slice(-8).join("\n").trimStart();
}

function buildStyles({ colors }: PopoverTheme, compact: boolean) {
  return {
    body: { gap: 10, width: compact ? undefined : 380 },
    row: { flexDirection: "row", alignItems: "center", gap: 6 },
    nav: { justifyContent: "space-between" },
    flex: { flex: 1 },
    linkButton: { minHeight: 28, justifyContent: "center" },
    link: { color: colors.accent, fontSize: 12, fontWeight: "600" },
    sectionTitle: { color: colors.foregroundMuted, fontSize: 11, fontWeight: "600" },
    surface: { backgroundColor: colors.surface2, borderRadius: 10, padding: 10, gap: 6 },
    item: { gap: 2 },
    dot: { width: 8, height: 8, borderRadius: 4 },
    tag: {
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surface1,
      borderRadius: 6,
      paddingHorizontal: 6,
      paddingVertical: 1,
      maxWidth: "36%",
    },
    tagText: { color: colors.foreground, fontSize: 11, fontWeight: "600" },
    goal: { color: colors.foreground, fontSize: 13, fontWeight: "500" },
    strong: { fontWeight: "600" },
    muted: { color: colors.foregroundMuted, fontSize: 12 },
    numeric: { fontVariant: ["tabular-nums"] },
    detail: { color: colors.foregroundMuted, fontSize: 11, marginLeft: 14 },
    list: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, overflow: "hidden" },
    goalItem: { paddingHorizontal: 12, paddingVertical: 9 },
    divider: { height: 1, backgroundColor: colors.border },
    footer: { alignItems: "center" },
    error: { color: colors.statusDanger, fontSize: 12 },
    alert: { color: colors.statusWarning, fontSize: 12 },
    peekTitle: { color: colors.foreground, fontSize: 14, fontWeight: "600", flex: 1 },
    chipRow: { gap: 4 },
    chip: { backgroundColor: colors.surface2, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
    chipOn: { backgroundColor: colors.accent },
    chipText: { color: colors.foregroundMuted, fontSize: 11, fontVariant: ["tabular-nums"] },
    chipTextOn: { color: colors.accentForeground },
    activity: { gap: 6 },
    event: { borderLeftWidth: 2, paddingLeft: 8, gap: 2 },
    answer: { color: colors.foreground, fontSize: 12, lineHeight: 17 },
  } satisfies Record<string, ViewStyle | TextStyle>;
}

type PopoverStyles = ReturnType<typeof buildStyles>;

function OverviewRow({
  run,
  styles,
  theme,
  detail,
  worker = false,
  onOpen,
}: {
  run: RunSummary;
  styles: PopoverStyles;
  theme: PopoverTheme;
  detail: string;
  worker?: boolean;
  onOpen(): void;
}) {
  const stage = stageOf(run);
  const goal = goalOf(run);
  const duration = runDuration(run);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={worker ? `${stage} · ${goal}` : goal}
      onPress={onOpen}
      style={[styles.item, !worker && styles.goalItem]}
    >
      <View style={styles.row}>
        <View style={[styles.dot, { backgroundColor: runDotColor(run, theme) }]} />
        <Text style={[styles.goal, styles.flex, worker && styles.strong]} numberOfLines={1}>{goal}</Text>
        {worker ? (
          <View style={styles.tag}>
            <Text style={styles.tagText} numberOfLines={1}>{stage}</Text>
          </View>
        ) : null}
        {duration === null ? null : <Text style={[styles.muted, styles.numeric]}>{duration}</Text>}
        <Text style={styles.muted}>›</Text>
      </View>
      <Text style={[styles.detail, styles.numeric]} numberOfLines={1}>{detail}</Text>
    </Pressable>
  );
}

export function AgentRunsPopover({ agentId, host, layout, theme, close, openScreen }: PopoverProps) {
  const styles = useMemo(() => buildStyles(theme, layout.compact), [theme, layout.compact]);
  const { t, locale } = useTranslation(messages);
  const settings = useSettings(observerSettings);
  const values = settings.status === "ready" ? settings.values : OBSERVER_DEFAULTS;
  const listQuery = useRunsListQuery(values.pollIntervalMs);
  const [peek, setPeek] = useState<PeekTarget | null>(null);
  const population = listQuery.data?.runs;
  const { byId, hero, groups, recent, activeCount } = useMemo(() => {
    const byId = new Map<string, RunSummary>();
    const groups = new Map<string, RunSummary[]>();
    const hero: RunSummary[] = [];
    const stale: RunSummary[] = [];
    const recent: RunSummary[][] = [];
    let activeCount = 0;
    // runs.list is newest first; Map insertion order gives the newest goal first too.
    for (const run of population ?? []) {
      if (run.lineage?.parentAgentId !== agentId) continue;
      byId.set(run.id, run);
      const goal = goalOf(run);
      const siblings = groups.get(goal);
      if (siblings) siblings.push(run);
      else {
        const group = [run];
        groups.set(goal, group);
        if (recent.length < MAX_GOALS) recent.push(group);
      }
      if (isActive(run)) {
        activeCount += 1;
        if (hero.length < MAX_WORKERS) hero.push(run);
      } else if (run.liveness === "stale" && stale.length < MAX_WORKERS) {
        stale.push(run);
      }
    }
    hero.push(...stale.slice(0, MAX_WORKERS - hero.length));
    return { byId, hero, groups, recent, activeCount };
  }, [population, agentId]);

  const listedRun = peek === null ? undefined : byId.get(peek.id);
  const selectedRun = listedRun?.runDir === peek?.runDir ? listedRun : undefined;
  const follow = useRpc(followRun);
  const followQuery = useQuery({
    queryKey: ["gddRuns", "follow", peek?.id ?? null, PEEK_TAIL_LINES, peek?.runDir ?? null],
    queryFn: peek ? () => follow({ id: peek.id, tailLines: PEEK_TAIL_LINES }) : skipToken,
    refetchInterval: (query) => (query.state.data?.summary?.finalized ? false : values.pollIntervalMs),
  });

  const openRuns = (runId?: string) => {
    close();
    openScreen({ screenId: "runs", params: { parentAgentId: agentId, ...(runId === undefined ? {} : { runId }) } });
  };
  const countersOf = (run: RunSummary) => countersLine(run, (key, value) => t(key, { value }), locale);

  const workerDetail = (run: RunSummary): string => {
    if (run.currentTool !== null) {
      return `▸ ${counterLine([run.currentTool, run.currentToolIntent])}`;
    }
    if (run.liveness === "stale") return t("composer.staleHint");
    return countersOf(run) || t("counter.none");
  };

  if (peek === null) {
    return (
      <View style={styles.body}>
        <View style={[styles.row, styles.nav]}>
          <Text style={[styles.muted, styles.flex]} numberOfLines={1}>
            {host.label}
            {" · "}
            {activeCount > 0
              ? t("composer.activeCount", { count: activeCount })
              : t("composer.goals", { count: groups.size })}
          </Text>
          <Pressable accessibilityRole="button" onPress={() => openRuns()} style={styles.linkButton}>
            <Text style={styles.link}>{t("composer.allRuns")}</Text>
          </Pressable>
        </View>
        {listQuery.error ? (
          <Text style={styles.error}>{t("error.list", { error: errorText(listQuery.error) })}</Text>
        ) : null}
        {listQuery.data === undefined && !listQuery.error ? (
          <Text style={styles.muted}>{t("list.scanning")}</Text>
        ) : null}
        {listQuery.data !== undefined && groups.size === 0 ? (
          <Text style={styles.muted}>{t("list.emptyAgent")}</Text>
        ) : null}
        {hero.length > 0 ? (
          <View style={styles.surface}>
            {hero.map((run) => (
              <OverviewRow key={run.id} run={run} styles={styles} theme={theme} worker
                detail={workerDetail(run)} onOpen={() => setPeek({ id: run.id, runDir: run.runDir })} />
            ))}
          </View>
        ) : null}
        {groups.size > 0 ? (
          <>
            {hero.length > 0 ? <Text style={styles.sectionTitle}>{t("composer.recentGoals")}</Text> : null}
            <View style={styles.list}>
              {recent.map((runs, index) => (
                <Fragment key={goalOf(runs[0])}>
                  {index > 0 ? <View style={styles.divider} /> : null}
                  <OverviewRow run={runs[0]} styles={styles} theme={theme}
                    detail={stageSummary(runs)} onOpen={() => setPeek({ id: runs[0].id, runDir: runs[0].runDir })} />
                </Fragment>
              ))}
            </View>
            {groups.size > MAX_GOALS ? (
              <Pressable accessibilityRole="button" onPress={() => openRuns()} style={[styles.linkButton, styles.footer]}>
                <Text style={styles.link}>{t("composer.viewAll", { count: groups.size })}</Text>
              </Pressable>
            ) : null}
          </>
        ) : null}
      </View>
    );
  }

  const data = followQuery.data;
  const sameDirectory = data?.summary === null || data?.summary === undefined || data.summary.runDir === peek.runDir;
  const followAgent = (data?.summary?.lineage ?? data?.lineage)?.parentAgentId;
  const followData = data?.found && sameDirectory && (followAgent === agentId || (followAgent === undefined && selectedRun !== undefined))
    ? data
    : undefined;
  const gone = data !== undefined && followData === undefined;
  const run = followData?.summary ?? selectedRun;
  const goal = run ? goalOf(run) : null;
  const chips = goal === null ? [] : goalChips(groups.get(goal), peek.id);
  const preview = followData?.answerTail ? answerPreview(followData.answerTail) : "";
  const counters = run ? countersOf(run) : "";
  const recentEvents = followData ? followData.events.slice(-MAX_EVENTS) : [];
  const recentEventKeys = eventKeys(recentEvents);

  return (
    <View style={styles.body}>
      <View style={[styles.row, styles.nav]}>
        <Pressable accessibilityRole="button" onPress={() => setPeek(null)} style={styles.linkButton}>
          <Text style={styles.link}>{t("composer.back")}</Text>
        </Pressable>
        {!gone ? (
          <Pressable
            accessibilityRole="button"
            onPress={() => openRuns(peek.id)}
            style={styles.linkButton}
          >
            <Text style={styles.link}>{t("composer.fullView")}</Text>
          </Pressable>
        ) : null}
      </View>
      {followQuery.error ? (
        <Text style={styles.error} numberOfLines={2}>{t("detail.loadError", { error: errorText(followQuery.error) })}</Text>
      ) : null}
      {gone ? <Text style={styles.alert}>{t("detail.gone")}</Text> : null}
      {run ? (
        <View style={styles.item}>
          <View style={styles.row}>
            <View style={[styles.dot, { backgroundColor: runDotColor(run, theme) }]} />
            <Text style={styles.peekTitle} numberOfLines={1}>{goalOf(run)}</Text>
          </View>
          <Text style={[styles.muted, styles.numeric]} numberOfLines={1}>
            {counterLine([
              stageOf(run),
              t(run.liveness === "stale" || run.liveness === "unknown" ? livenessKey(run.liveness) : stateKey(run.state)),
              runDuration(run),
            ])}
          </Text>
          <Text style={[styles.muted, styles.numeric]} numberOfLines={1}>{counters || t("counter.none")}</Text>
        </View>
      ) : null}
      {chips.length > 1 ? (
        <ScrollView horizontal nestedScrollEnabled contentContainerStyle={styles.chipRow}>
          {chips.map((chip) => {
            const selected = chip.id === peek.id;
            return (
              <Pressable
                key={chip.id}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                onPress={() => setPeek({ id: chip.id, runDir: chip.runDir })}
                style={[styles.chip, selected && styles.chipOn]}
              >
                <Text style={[styles.chipText, selected && styles.chipTextOn]} numberOfLines={1}>
                  {chip.repeat ? t("composer.attempt", { stage: chip.stage, index: chip.index }) : chip.stage}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}
      {run && (run.liveness === "stale" || run.lastError) ? (
        <View style={styles.surface}>
          <Text style={run.lastError ? styles.error : styles.alert} numberOfLines={2}>
            {run.lastError || t("composer.staleHint")}
          </Text>
        </View>
      ) : null}
      {followQuery.isPending && !gone ? <Text style={styles.muted}>{t("list.scanning")}</Text> : null}
      {followData ? (
        <>
          <Text style={styles.sectionTitle}>{t("composer.latestActivity")}</Text>
          <View style={styles.activity}>
            {recentEvents.length === 0 ? (
              <Text style={styles.muted}>{t("detail.noEvents")}</Text>
            ) : (
              recentEvents.map((event, index) => {
                const failure = eventFailureKey(event.type);
                const color = eventColor(event, theme);
                const title = failure !== null
                  ? counterLine([event.tool, t(failure)])
                  : event.role === "assistant"
                    ? t("detail.activityAssistant")
                    : event.type === "truncated"
                      ? t("detail.activityTruncated")
                      : event.tool ?? event.type;
                return (
                  <View key={recentEventKeys[index]} style={[styles.event, { borderLeftColor: color }]}>
                    <Text style={[styles.muted, { color }]} numberOfLines={1}>{title}</Text>
                    {event.intent || event.detail ? (
                      <Text style={styles.muted} numberOfLines={2}>{event.intent ?? event.detail}</Text>
                    ) : null}
                  </View>
                );
              })
            )}
          </View>
        </>
      ) : null}
      {preview ? (
        <>
          <Text style={styles.sectionTitle}>{t("composer.answerPreview")}</Text>
          <View style={styles.surface}>
            <Text style={styles.answer}>{preview}</Text>
          </View>
        </>
      ) : null}
    </View>
  );
}
