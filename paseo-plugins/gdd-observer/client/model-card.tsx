import { useTranslation } from "@getpaseo/plugin/client";
import { Icon } from "@getpaseo/plugin/client/ui";
import { Text, View } from "react-native";
import type { RunModel } from "../shared/runs";
import { FactsCard } from "./facts";
import { firstUsage, usageLabel } from "./format";
import { messages } from "./messages";
import { useObserverStyles } from "./styles";
import type { ObserverLayout, ObserverTheme } from "./types";

type ModelProps = { model: RunModel; theme: ObserverTheme; layout: ObserverLayout };

export function ModelChip({ model, theme, layout }: ModelProps) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const observed = usageLabel(firstUsage(model));
  const label = observed ?? model.requested ?? t("model.none");
  const contradicts = observed !== null && model.requested !== null && model.requested !== observed;
  return (
    <View style={styles.rowMeta}>
      <View style={styles.modelChip}>
        <Icon name="Cpu" size={11} color={theme.colors.foregroundMuted} />
        <Text style={styles.modelChipLabel} numberOfLines={1}>
          {label}
        </Text>
      </View>
      {contradicts ? (
        <Text style={styles.faint} numberOfLines={1}>
          {t("model.requestedChip", { value: model.requested })}
        </Text>
      ) : null}
    </View>
  );
}

export function ModelCard({ model, theme, layout }: ModelProps) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const observed = firstUsage(model);
  const rest = model.observed.slice(1);
  return (
    <FactsCard
      title={t("model.title")}
      icon="Cpu"
      theme={theme}
      layout={layout}
      facts={[
        [
          t("model.ranOn"),
          observed === null ? t("model.unknown") : (observed.model ?? usageLabel(observed)),
        ],
        [t("model.provider"), observed?.provider ?? model.requestedProvider],
        [t("model.api"), observed?.api ?? null],
        [t("model.requested"), model.requested ?? t("model.default")],
        [t("model.thinking"), model.thinking ?? t("model.default")],
      ]}
    >
      {rest.map((usage, index) => {
        const label = usageLabel(usage) ?? usage.api ?? "";
        return (
          <Text key={`${index}:${label}`} style={styles.muted}>
            {t("model.also", {
              value: label,
              messages: t("model.messages", { count: usage.messages }),
            })}
          </Text>
        );
      })}
      {model.requested === null ? <Text style={styles.note}>{t("model.defaultNote")}</Text> : null}
    </FactsCard>
  );
}
