import type { PluginHostProps } from "@getpaseo/plugin/client";

/**
 * The host props this plugin's surfaces use, named once. They stay derived from the SDK contract,
 * so a host that widens or narrows `theme`, `layout`, or `host` moves these with it.
 */
export type ObserverTheme = PluginHostProps["theme"];
export type ObserverLayout = PluginHostProps["layout"];
export type ObserverHost = PluginHostProps["host"];
