import type { PluginClientContext } from "@getpaseo/plugin/client";
import { RunsPanel, RunsScreen } from "./client/runs-browser";
import { ObserverSettingsScreen } from "./client/settings-screen";
import { messages } from "./client/messages";

/**
 * Three surfaces over one read-only observer: a workspace panel, a global screen reachable from
 * the Command Center, and the settings screen that owns the run root override.
 */
export default function contribute(client: PluginClientContext) {
  client.addWorkspacePanel({
    id: "runs",
    title: messages.message("panel.title"),
    icon: "Activity",
    Component: RunsPanel,
  });
  client.addScreen({
    id: "runs",
    title: messages.message("panel.title"),
    Component: RunsScreen,
  });
  client.addSettingsScreen({
    id: "settings",
    title: messages.message("settingsScreen.title"),
    icon: "Activity",
    Component: ObserverSettingsScreen,
  });
  client.addCommandCenterItem({
    id: "open-runs",
    title: messages.message("command.open"),
    icon: "Activity",
    keywords: ["gdd", "runs", "launcher", "observer"],
    context: "global",
    onSelect({ openScreen }) {
      openScreen({ screenId: "runs" });
    },
  });
  return () => {};
}
