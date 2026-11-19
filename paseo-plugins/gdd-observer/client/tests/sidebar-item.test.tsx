import { createElement } from "react";
import type {
  PluginClientContext,
  PluginOpenScreenInput,
  PluginSidebarItemContribution,
  PluginSidebarItemProps,
  PluginText,
} from "@getpaseo/plugin/client";
import { describe, expect, it, vi } from "vitest";
import contribute from "../../index.client";
import { hostProps, nodes, renderClient } from "./harness";

// Render the registered sidebar row and resolve its title as the host would.

const titles = { en: "GDD runs", "zh-CN": "GDD 运行" } as const;

function collectSidebarContributions() {
  const header: PluginSidebarItemContribution<PluginText>[] = [];
  const footer: PluginSidebarItemContribution<PluginText>[] = [];
  const client = {
    addWorkspacePanel: vi.fn(),
    addScreen: vi.fn(),
    addSettingsScreen: vi.fn(),
    addCommandCenterItem: vi.fn(),
    addSlashCommand: vi.fn(),
    addSidebarHeaderItem: vi.fn((contribution: PluginSidebarItemContribution<PluginText>) => {
      header.push(contribution);
      return () => {};
    }),
    addSidebarFooterItem: vi.fn((contribution: PluginSidebarItemContribution<PluginText>) => {
      footer.push(contribution);
      return () => {};
    }),
  } as unknown as PluginClientContext;
  contribute(client);
  return { header, footer };
}

const contributions = collectSidebarContributions();
const item = contributions.footer[0];

function itemProps(
  compact: boolean,
  currentScreen: PluginSidebarItemProps["currentScreen"],
  openScreen: (input: PluginOpenScreenInput) => void = () => {},
): PluginSidebarItemProps {
  return {
    ...hostProps,
    layout: { ...hostProps.layout, compact },
    currentScreen,
    openScreen,
    openPopover: () => {},
  };
}

const cases = (["en", "zh-CN"] as const).flatMap((locale) => [
  { locale, layout: "wide", compact: false },
  { locale, layout: "compact", compact: true },
]);

describe("runs sidebar item", () => {
  it.each(["en", "zh-CN"] as const)("shows exactly one sidebar entry, in the footer, in %s", async (locale) => {
    const view = await renderClient(createElement(item.Component, itemProps(false, null)), { locale });
    expect(contributions.header.map(({ title }) => view.translations.resolve(title))).toEqual([]);
    expect(contributions.footer.map(({ title }) => view.translations.resolve(title))).toEqual([titles[locale]]);
  });

  it.each(cases)(
    "footer item in $locale ($layout) stays inactive away from the runs screen and opens it on press",
    async ({ locale, compact }) => {
      const openScreen = vi.fn();
      const view = await renderClient(createElement(item.Component, itemProps(compact, null, openScreen)), { locale });
      const row = () => nodes(view.root, "SidebarRow")[0];
      expect(row().props.icon).toBe("Activity");
      expect(row().props.active).toBe(false);
      await view.update(
        createElement(item.Component, itemProps(compact, { screenId: "another-plugin", params: {} }, openScreen)),
      );
      expect(row().props.active).toBe(false);
      expect(openScreen).not.toHaveBeenCalled();
      await view.update(
        createElement(
          item.Component,
          itemProps(compact, { screenId: "runs", params: { run: "2026-11-14/stage-implement" } }, openScreen),
        ),
      );
      expect(row().props.active).toBe(true);
      await view.change(() => {
        row().props.onPress();
      });
      expect(openScreen).toHaveBeenCalledTimes(1);
      expect(openScreen).toHaveBeenCalledWith({ screenId: "runs" });
    },
  );
});
