import { useMemo } from "react";
import type { TextStyle, ViewStyle } from "react-native";
import type { ObserverLayout, ObserverTheme } from "./types";

/**
 * Styles follow the active theme and layout; every color comes from a theme token. Nothing here
 * paints a literal color: the only exception is `transparent`, which keeps a selected row's
 * accent bar from shifting its text.
 */
export interface ObserverStyles {
  root: ViewStyle;
  listWide: ViewStyle;
  listCompact: ViewStyle;
  listContent: ViewStyle;
  listHeader: ViewStyle;
  listTitleRow: ViewStyle;
  listLoading: ViewStyle;
  detail: ViewStyle;
  detailContent: ViewStyle;
  detailEmpty: ViewStyle;
  heading: TextStyle;
  headingMeta: TextStyle;
  sectionTitle: TextStyle;
  title: TextStyle;
  body: TextStyle;
  muted: TextStyle;
  faint: TextStyle;
  warn: TextStyle;
  error: TextStyle;
  note: TextStyle;
  card: ViewStyle;
  cardHeader: ViewStyle;
  cardTitle: TextStyle;
  statStrip: ViewStyle;
  statBar: ViewStyle;
  statBarSegment: ViewStyle;
  statHeadline: ViewStyle;
  statHeadlineValue: TextStyle;
  statHeadlineState: TextStyle;
  statLegend: ViewStyle;
  statLegendItem: ViewStyle;
  statDot: ViewStyle;
  statLegendValue: TextStyle;
  statLegendDim: TextStyle;
  statLegendLabel: TextStyle;
  statTotals: TextStyle;
  statNote: TextStyle;
  row: ViewStyle;
  rowSelected: ViewStyle;
  rowTop: ViewStyle;
  rowTitle: TextStyle;
  rowMeta: ViewStyle;
  badge: ViewStyle;
  badgeText: TextStyle;
  modelChip: ViewStyle;
  modelChipLabel: TextStyle;
  header: ViewStyle;
  facts: ViewStyle;
  fact: ViewStyle;
  factLabel: TextStyle;
  factValue: TextStyle;
  warningCard: ViewStyle;
  warningRow: TextStyle;
  eventRow: ViewStyle;
  eventTrack: ViewStyle;
  eventBody: ViewStyle;
  eventClock: TextStyle;
  eventType: TextStyle;
  eventDetail: TextStyle;
  pathRow: ViewStyle;
  pathLabel: TextStyle;
  pathValue: TextStyle;
  backRow: ViewStyle;
  backLabel: TextStyle;
  emptyBlock: ViewStyle;
  emptyTitle: TextStyle;
}

function observerStyles(theme: ObserverTheme, layout: ObserverLayout): ObserverStyles {
  const compact = layout.compact;
  const pad = compact ? 12 : 20;
  const gutter = compact ? 10 : 12;
  const rowPadding = compact ? 9 : 10;
  const mono = layout.platform === "ios" ? "Menlo" : "monospace";
  return {
    root: {
      flex: 1,
      flexDirection: compact ? "column" : "row",
      backgroundColor: theme.colors.surface0,
    },
    listWide: { width: 340, borderRightWidth: 1, borderRightColor: theme.colors.border },
    listCompact: { flex: 1 },
    listContent: { paddingHorizontal: gutter, paddingTop: 14, paddingBottom: 20, gap: 4 },
    listHeader: { gap: 8, paddingBottom: 6 },
    listTitleRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
    listLoading: { flex: 1, alignItems: "center", justifyContent: "center" },
    detail: { flex: 1, minHeight: 0 },
    detailContent: { padding: compact ? 12 : 16, gap: compact ? 10 : 14, paddingBottom: 32 },
    detailEmpty: { flex: 1, padding: pad, alignItems: "center", justifyContent: "center" },
    heading: { color: theme.colors.foreground, fontSize: 16, fontWeight: "600", flexShrink: 1 },
    headingMeta: { color: theme.colors.foregroundMuted, fontSize: 11, flexShrink: 1 },
    sectionTitle: {
      color: theme.colors.foregroundMuted,
      fontSize: 11,
      fontWeight: "600",
      letterSpacing: 0.6,
      textTransform: "uppercase",
    },
    title: { color: theme.colors.foreground, fontSize: compact ? 18 : 20, fontWeight: "600" },
    body: { color: theme.colors.foreground, fontSize: 13, lineHeight: 19 },
    muted: { color: theme.colors.foregroundMuted, fontSize: 12, lineHeight: 18 },
    faint: { color: theme.colors.foregroundMuted, fontSize: 11, lineHeight: 16 },
    warn: { color: theme.colors.statusWarning, fontSize: 12, lineHeight: 18 },
    error: { color: theme.colors.statusDanger, fontSize: 12, lineHeight: 18 },
    note: { color: theme.colors.foregroundMuted, fontSize: 11, lineHeight: 16 },

    card: {
      backgroundColor: theme.colors.surface1,
      borderColor: theme.colors.border,
      borderWidth: 1,
      borderRadius: 10,
      padding: compact ? 10 : 12,
      gap: 8,
    },
    cardHeader: { flexDirection: "row", alignItems: "center", gap: 6 },
    cardTitle: { color: theme.colors.foreground, fontSize: 12, fontWeight: "600" },

    statStrip: { gap: 7 },
    statBar: {
      flexDirection: "row",
      height: 4,
      borderRadius: 999,
      overflow: "hidden",
      backgroundColor: theme.colors.surface2,
    },
    statBarSegment: { height: 4, flexBasis: 0 },
    statHeadline: { flexDirection: "row", alignItems: "baseline", flexWrap: "wrap", gap: 8 },
    statHeadlineValue: { color: theme.colors.foreground, fontSize: 14, fontWeight: "600" },
    statHeadlineState: { fontSize: 14, fontWeight: "600" },
    statLegend: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    statLegendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
    statDot: { width: 6, height: 6, borderRadius: 999 },
    statLegendValue: { color: theme.colors.foreground, fontSize: 12, fontWeight: "600" },
    statLegendDim: { color: theme.colors.foregroundMuted, fontWeight: "500" },
    statLegendLabel: { color: theme.colors.foregroundMuted, fontSize: 12 },
    statTotals: { color: theme.colors.foreground, fontSize: 12, lineHeight: 18 },
    statNote: { color: theme.colors.foregroundMuted, fontSize: 11, lineHeight: 16 },

    row: {
      backgroundColor: theme.colors.surface0,
      borderLeftWidth: 3,
      borderLeftColor: "transparent",
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.border,
      paddingLeft: rowPadding,
      paddingRight: rowPadding,
      paddingVertical: rowPadding,
      gap: 4,
    },
    rowSelected: { borderLeftColor: theme.colors.accent, backgroundColor: theme.colors.surface2 },
    rowTop: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
    rowTitle: { color: theme.colors.foreground, fontSize: 14, fontWeight: "600", flexShrink: 1 },
    rowMeta: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },

    badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 1 },
    badgeText: { fontSize: 11 },

    modelChip: {
      flexDirection: "row",
      alignItems: "center",
      gap: 4,
      maxWidth: "100%",
      backgroundColor: theme.colors.surface1,
      borderRadius: 6,
      paddingHorizontal: 6,
      paddingVertical: 2,
    },
    modelChipLabel: { color: theme.colors.foreground, fontSize: 11, flexShrink: 1 },

    header: { gap: 8 },
    facts: { flexDirection: "row", flexWrap: "wrap", gap: compact ? 10 : 18 },
    fact: { minWidth: compact ? 116 : 156, gap: 2, flexShrink: 1 },
    factLabel: { color: theme.colors.foregroundMuted, fontSize: 11 },
    factValue: { color: theme.colors.foreground, fontSize: 12, lineHeight: 17 },

    warningCard: {
      backgroundColor: theme.colors.surface1,
      borderColor: theme.colors.border,
      borderWidth: 1,
      borderLeftWidth: 3,
      borderLeftColor: theme.colors.statusWarning,
      borderRadius: 10,
      padding: compact ? 10 : 12,
      gap: 4,
    },
    warningRow: { color: theme.colors.statusWarning, fontSize: 12, lineHeight: 18 },

    eventRow: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
    eventTrack: { width: 3, borderRadius: 999, alignSelf: "stretch" },
    eventBody: { flex: 1, gap: 1 },
    eventClock: {
      color: theme.colors.foregroundMuted,
      fontSize: 11,
      fontFamily: mono,
      lineHeight: 16,
      width: 62,
    },
    eventType: { fontSize: 12, fontWeight: "600", lineHeight: 18, flexShrink: 1 },
    eventDetail: { color: theme.colors.foregroundMuted, fontSize: 12, lineHeight: 18 },

    pathRow: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 8,
    },
    pathLabel: { color: theme.colors.foreground, fontSize: 12, flexShrink: 1 },
    pathValue: { color: theme.colors.foregroundMuted, fontSize: 11, flexShrink: 1 },

    backRow: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44 },
    backLabel: { color: theme.colors.accent, fontSize: 13 },

    emptyBlock: { gap: 6, paddingVertical: 18, alignItems: "center" },
    emptyTitle: { color: theme.colors.foreground, fontSize: 13, fontWeight: "600" },
  };
}

/**
 * One style object per theme and layout, shared by every component that renders under them: the
 * styles are pure and never mutated, so a hundred rows can hold the same object instead of each
 * building its own copy.
 */
const styleCache = new WeakMap<ObserverTheme, WeakMap<ObserverLayout, ObserverStyles>>();

export function useObserverStyles(theme: ObserverTheme, layout: ObserverLayout): ObserverStyles {
  return useMemo(() => {
    const byTheme = styleCache.get(theme) ?? new WeakMap<ObserverLayout, ObserverStyles>();
    styleCache.set(theme, byTheme);
    const cached = byTheme.get(layout);
    if (cached) return cached;
    const built = observerStyles(theme, layout);
    byTheme.set(layout, built);
    return built;
  }, [theme, layout]);
}
