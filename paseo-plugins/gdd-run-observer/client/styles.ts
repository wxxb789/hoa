import { useMemo } from "react";
import type { TextStyle, ViewStyle } from "react-native";
import type { ObserverLayout, ObserverTheme } from "./types";

export interface ObserverStyles {
  root: ViewStyle;
  listWide: ViewStyle;
  listCompact: ViewStyle;
  listContent: ViewStyle;
  detail: ViewStyle;
  detailContent: ViewStyle;
  heading: TextStyle;
  sectionTitle: TextStyle;
  title: TextStyle;
  body: TextStyle;
  muted: TextStyle;
  faint: TextStyle;
  warn: TextStyle;
  error: TextStyle;
  link: TextStyle;
  card: ViewStyle;
  row: ViewStyle;
  rowSelected: ViewStyle;
  rowTop: ViewStyle;
  rowTitle: TextStyle;
  badge: ViewStyle;
  badgeText: TextStyle;
  header: ViewStyle;
  facts: ViewStyle;
  fact: ViewStyle;
  factLabel: TextStyle;
  factValue: TextStyle;
  eventRow: ViewStyle;
  eventClock: TextStyle;
  eventType: TextStyle;
  eventDetail: TextStyle;
  mono: TextStyle;
  pathRow: ViewStyle;
  pathLabel: TextStyle;
  pathValue: TextStyle;
  backRow: ViewStyle;
}

/** Styles follow the active theme and layout; every color comes from a theme token. */
export function observerStyles(theme: ObserverTheme, layout: ObserverLayout): ObserverStyles {
  const compact = layout.compact;
  const pad = compact ? 12 : 20;
  const mono = layout.platform === "ios" ? "Menlo" : "monospace";
  return {
    root: {
      flex: 1,
      flexDirection: compact ? "column" : "row",
      backgroundColor: theme.colors.surface0,
    },
    listWide: { width: 340, borderRightWidth: 1, borderRightColor: theme.colors.border },
    listCompact: { flex: 1 },
    listContent: { padding: pad, gap: compact ? 8 : 10 },
    detail: { flex: 1, minHeight: 0 },
    detailContent: { padding: pad, gap: compact ? 8 : 12 },
    heading: { color: theme.colors.foreground, fontSize: 16, fontWeight: "600" },
    sectionTitle: { color: theme.colors.foreground, fontSize: 13, fontWeight: "600", marginTop: 4 },
    title: { color: theme.colors.foreground, fontSize: compact ? 17 : 20, fontWeight: "600" },
    body: { color: theme.colors.foreground, fontSize: 13 },
    muted: { color: theme.colors.foregroundMuted, fontSize: 12 },
    faint: { color: theme.colors.foregroundMuted, fontSize: 11 },
    warn: { color: theme.colors.statusWarning, fontSize: 12 },
    error: { color: theme.colors.statusDanger, fontSize: 12 },
    link: { color: theme.colors.accent, fontSize: 13 },
    card: {
      backgroundColor: theme.colors.surface1,
      borderColor: theme.colors.border,
      borderWidth: 1,
      borderRadius: 8,
      padding: compact ? 10 : 12,
      gap: 6,
    },
    row: {
      backgroundColor: theme.colors.surface1,
      borderColor: theme.colors.border,
      borderWidth: 1,
      borderRadius: 8,
      padding: compact ? 10 : 12,
      gap: 4,
    },
    rowSelected: { borderColor: theme.colors.accent },
    rowTop: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
    rowTitle: { color: theme.colors.foreground, fontSize: 14, fontWeight: "600", flexShrink: 1 },
    badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 1 },
    badgeText: { fontSize: 11 },
    header: { gap: 6 },
    facts: { flexDirection: "row", flexWrap: "wrap", gap: compact ? 10 : 18 },
    fact: { minWidth: compact ? 120 : 160, gap: 2 },
    factLabel: { color: theme.colors.foregroundMuted, fontSize: 11 },
    factValue: { color: theme.colors.foreground, fontSize: 12 },
    eventRow: { gap: 1 },
    eventClock: { color: theme.colors.foregroundMuted, fontSize: 10 },
    eventType: { fontSize: 12, fontWeight: "600" },
    eventDetail: { color: theme.colors.foregroundMuted, fontSize: 11 },
    mono: { color: theme.colors.foreground, fontSize: 12, fontFamily: mono },
    pathRow: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 8,
    },
    pathLabel: { color: theme.colors.foreground, fontSize: 12 },
    pathValue: { color: theme.colors.foregroundMuted, fontSize: 11, flexShrink: 1 },
    backRow: { paddingVertical: 4 },
  };
}

export function useObserverStyles(theme: ObserverTheme, layout: ObserverLayout): ObserverStyles {
  return useMemo(() => observerStyles(theme, layout), [theme, layout]);
}
