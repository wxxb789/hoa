import type { PluginClientContext, PluginScreenProps, PluginSurfaceProps } from "@getpaseo/plugin/client";
import { ComposerPillManager } from "./client/composer-pills";
import { RunsScreen } from "./client/runs-browser";
import { RunsSidebarItem } from "./client/sidebar-item";
import { ObserverSettingsScreen } from "./client/settings-screen";
import { messages } from "./client/messages";
import { RunsListControllerContext } from "./client/use-runs-query";

export default function contribute(client: PluginClientContext): () => void {
  const pills = client.paseo?.agents && typeof client.addComposerPill === "function" && typeof client.rpc === "function"
    ? new ComposerPillManager(client) : null;
  const removeFooterItem = client.addSidebarFooterItem({
    id: "runs-footer",
    title: messages.message("screen.title"),
    Component: RunsSidebarItem,
  });
  const removeScreen = client.addScreen({
    id: "runs",
    title: messages.message("screen.title"),
    Component: (props: PluginScreenProps) => (
      <RunsListControllerContext.Provider value={pills}><RunsScreen {...props} /></RunsListControllerContext.Provider>
    ),
  });
  const removeSettingsScreen = client.addSettingsScreen({
    id: "settings",
    title: messages.message("settingsScreen.title"),
    icon: "Activity",
    Component: (props: PluginSurfaceProps) => (
      <RunsListControllerContext.Provider value={pills}><ObserverSettingsScreen {...props} /></RunsListControllerContext.Provider>
    ),
  });
  return () => {
    pills?.dispose();
    removeFooterItem();
    removeScreen();
    removeSettingsScreen();
  };
}
