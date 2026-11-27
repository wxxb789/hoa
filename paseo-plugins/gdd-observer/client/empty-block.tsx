import { Icon } from "@getpaseo/plugin/client/ui";
import { Text, View } from "react-native";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";

export function EmptyBlock({
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
