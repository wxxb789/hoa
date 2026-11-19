import { Icon } from "@getpaseo/plugin/client/ui";
import { Text, View } from "react-native";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";

/**
 * A card of label/value cells, the shape both the model attribution and the run bookkeeping use.
 * The caller keeps its own facts; only the markup and the empty-value rule live here.
 */
export function FactsCard({
  title,
  icon,
  facts,
  theme,
  layout,
  children,
}: {
  title: string;
  icon: string;
  facts: Array<[string, string | null]>;
  theme: ObserverTheme;
  layout: ObserverLayout;
  children?: React.ReactNode;
}) {
  const styles = useObserverStyles(theme, layout);
  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <Icon name={icon} size={13} color={theme.colors.foregroundMuted} />
        <Text style={styles.cardTitle}>{title}</Text>
      </View>
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
      {children}
    </View>
  );
}
