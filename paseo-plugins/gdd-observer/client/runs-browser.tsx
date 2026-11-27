import type { PluginScreenProps } from "@getpaseo/plugin/client";
import { useSettings, useTranslation } from "@getpaseo/plugin/client";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { OBSERVER_DEFAULTS, observerSettings } from "../shared/settings";
import { EmptyBlock } from "./empty-block";
import { messages } from "./messages";
import { RunDetailPane } from "./run-detail-pane";
import { RunsListPane } from "./runs-list-pane";
import { useObserverStyles } from "./styles";

export { eventKeys } from "./run-detail-pane";

export function RunsScreen({ theme, layout, host, params, navigation }: PluginScreenProps) {
  const runId = params.runId || null;
  const parentAgentId = params.parentAgentId || null;
  const [selected, onSelect] = useState(runId);
  const [agentFilter, setAgentFilter] = useState(parentAgentId);
  useEffect(() => onSelect(runId), [runId]);
  useEffect(() => setAgentFilter(parentAgentId), [parentAgentId]);
  const clearAgentFilter = useCallback(() => setAgentFilter(null), []);
  const onBack = useCallback(() => onSelect(null), []);
  const styles = useObserverStyles(theme, layout);
  const { t, locale } = useTranslation(messages);
  const settings = useSettings(observerSettings);
  const values = settings.status === "ready" ? settings.values : OBSERVER_DEFAULTS;

  return (
    <View style={styles.root}>
      {/* In compact mode, a hidden list holds no scan observer and joins no polling election. */}
      {!layout.compact || selected === null ? (
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
      ) : null}
      {selected !== null ? (
        <RunDetailPane
          theme={theme}
          layout={layout}
          host={host}
          navigation={navigation}
          selected={selected}
          tailLines={values.tailLines}
          pollIntervalMs={values.pollIntervalMs}
          onBack={onBack}
        />
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
