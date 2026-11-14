import type { PluginTheme } from "@getpaseo/plugin";

export type ObserverTheme = PluginTheme;
export type ObserverLayout = {
  readonly compact: boolean;
  readonly platform: "ios" | "android" | "web";
};
export type ObserverHost = { readonly id: string; readonly label: string };
export type TabSelection = { selected: string | null };
