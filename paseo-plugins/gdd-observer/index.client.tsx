import type { PluginClientContext } from "@getpaseo/plugin/client";
import { RunsScreen } from "./client/runs-browser";
import { RunsSidebarItem } from "./client/sidebar-item";
import { ObserverSettingsScreen } from "./client/settings-screen";
import { messages } from "./client/messages";

export default function contribute(client: PluginClientContext): () => void {
  const removeFooterItem = client.addSidebarFooterItem({
    id: "runs-footer",
    title: messages.message("screen.title"),
    Component: RunsSidebarItem,
  });
  const removeScreen = client.addScreen({
    id: "runs",
    title: messages.message("screen.title"),
    Component: RunsScreen,
  });
  const removeSettingsScreen = client.addSettingsScreen({
    id: "settings",
    title: messages.message("settingsScreen.title"),
    icon: "Activity",
    Component: ObserverSettingsScreen,
  });
  return () => {
    removeFooterItem();
    removeScreen();
    removeSettingsScreen();
  };
}
