import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { OBSERVER_DEFAULTS } from "../../shared/settings";
import { ObserverSettingsScreen } from "../settings-screen";
import { hostProps, makeScan, nodes, renderClient, type RenderedClient } from "./harness";
import { testHost } from "./setup";

// The settings screen owns the run-root override. These tests drive it only through the props the
// host supplies (labels, values, options, disabled flags, presses) and read back the persisted
// document, the visible root facts and the feedback a user sees.

type RootValues = { runRoot?: string; pollIntervalMs?: number; tailLines?: number };

const rootScreen = () => createElement(ObserverSettingsScreen, hostProps);

const rootInput = (view: RenderedClient) => nodes(view.root, "SettingsInput")[0];
const actions = (view: RenderedClient) => nodes(view.root, "SettingsAction");
const selects = (view: RenderedClient) => nodes(view.root, "SettingsSelect");

/** Drains the screen's save promise chain so its toast and state updates land before assertions. */
async function flushSave() {
  for (let tick = 0; tick < 4; tick += 1) await Promise.resolve();
}

function readyHost(
  options: { values?: RootValues; revision?: string; saving?: boolean; saveError?: string | null } = {},
) {
  const save = vi.fn<(values: unknown, revision: string) => Promise<boolean>>().mockResolvedValue(true);
  const values = options.values ?? {};
  testHost.settings = {
    status: "ready",
    values: {
      runRoot: values.runRoot ?? OBSERVER_DEFAULTS.runRoot,
      pollIntervalMs: values.pollIntervalMs ?? OBSERVER_DEFAULTS.pollIntervalMs,
      tailLines: values.tailLines ?? OBSERVER_DEFAULTS.tailLines,
    },
    revision: options.revision ?? "revision-1",
    saving: options.saving ?? false,
    saveError: options.saveError ?? null,
    save,
    reset: vi.fn().mockResolvedValue(true),
    reload: vi.fn().mockResolvedValue(undefined),
  };
  return { save };
}

function nonReadyHost(status: "loading" | "error" | "invalid", error = "fixture settings error") {
  const base = {
    saving: false,
    saveError: null as string | null,
    save: vi.fn().mockResolvedValue(true),
    reset: vi.fn().mockResolvedValue(true),
    reload: vi.fn().mockResolvedValue(undefined),
  };
  if (status === "loading") {
    testHost.settings = { ...base, status };
    return;
  }
  testHost.settings = status === "error"
    ? { ...base, status, error }
    : { ...base, status, error, revision: "revision-1" };
}

async function typeRoot(view: RenderedClient, text: string) {
  await view.change(() => {
    rootInput(view).props.onChangeText(text);
  });
}

async function press(view: RenderedClient, index: number) {
  await view.change(async () => {
    actions(view)[index].props.onPress();
    await flushSave();
  });
}

async function choose(view: RenderedClient, index: number, value: string) {
  await view.change(async () => {
    selects(view)[index].props.onValueChange(value);
    await flushSave();
  });
}

describe("observer settings screen", () => {
  it.each(["en", "zh-CN"] as const)("shows only the host loading placeholder in %s", async (locale) => {
    nonReadyHost("loading");
    const view = await renderClient(rootScreen(), { locale });
    expect(nodes(view.root, "Loading")).toHaveLength(1);
    expect(nodes(view.root, "SettingsSection")).toHaveLength(0);
    expect(nodes(view.root, "SettingsInput")).toHaveLength(0);
    expect(actions(view)).toHaveLength(0);
    expect(selects(view)).toHaveLength(0);
    expect(view.texts()).toEqual([]);
  });

  it.each([
    {
      locale: "en" as const,
      invalid: "Stored settings are invalid: runRoot must be a string",
      error: "Stored settings are invalid: the settings host is offline",
    },
    {
      locale: "zh-CN" as const,
      invalid: "已存储的设置无效：runRoot must be a string",
      error: "已存储的设置无效：the settings host is offline",
    },
  ])("surfaces invalid and errored stored settings without save controls in $locale", async ({ locale, invalid, error }) => {
    nonReadyHost("invalid", "runRoot must be a string");
    const view = await renderClient(rootScreen(), { locale });
    expect(view.texts()).toEqual([invalid]);
    expect(nodes(view.root, "Loading")).toHaveLength(0);
    expect(nodes(view.root, "SettingsInput")).toHaveLength(0);
    expect(actions(view)).toHaveLength(0);
    expect(selects(view)).toHaveLength(0);
    nonReadyHost("error", "the settings host is offline");
    await view.update(rootScreen());
    expect(view.texts()).toEqual([error]);
  });

  it("shows scanning placeholders and no missing-root claim while the first scan is pending", async () => {
    const view = await renderClient(rootScreen(), { pending: true });
    expect(view.texts().filter((text) => text === "Scanning…")).toHaveLength(3);
    expect(view.texts().filter((text) => text === "—")).toHaveLength(2);
    expect(view.texts()).not.toContain("0 runs");
    expect(rootInput(view).props.error).toBeNull();
  });

  it.each(["en", "zh-CN"] as const)("shows the scan failure instead of invented root facts in %s", async (locale) => {
    const view = await renderClient(rootScreen(), { locale });
    await view.change(() => {
      view.query
        .getQueryCache()
        .find({ queryKey: ["gddRuns", "list"] })!
        .setState({ status: "error", error: new Error("fixture denied"), data: undefined });
    });
    expect(view.texts()).toContain(
      locale === "en" ? "Could not read runs: fixture denied" : "无法读取运行列表：fixture denied",
    );
    expect(view.texts()).toContain(locale === "en" ? "Scanning…" : "扫描中…");
    expect(view.texts()).not.toContain(locale === "en" ? "no" : "否");
  });

  it.each([
    ["setting", "the plugin setting", "插件设置"],
    ["env", "GDD_RUN_ROOT", "GDD_RUN_ROOT"],
    ["xdg", "XDG_STATE_HOME", "XDG_STATE_HOME"],
    ["home", "the home state directory", "用户状态目录"],
    ["localappdata", "LOCALAPPDATA", "LOCALAPPDATA"],
    ["default", "the documented default", "文档默认值"],
  ] as const)("names the %s resolved root source and candidate in both locales", async (rootSource, en, zh) => {
    const scan = makeScan({
      runRoot: "/host/gdd/runs",
      rootSource,
      candidates: [{ path: "/host/gdd/runs", source: rootSource, exists: true }],
    });
    const enView = await renderClient(rootScreen(), { scan });
    expect(enView.texts()).toContain(en);
    expect(enView.texts()).toContain(`✓ /host/gdd/runs (${en})`);
    const zhView = await renderClient(rootScreen(), { locale: "zh-CN", scan });
    expect(zhView.texts()).toContain(zh);
    expect(zhView.texts()).toContain(`✓ /host/gdd/runs (${zh})`);
  });

  it.each([
    { locale: "en" as const, yes: "yes", no: "no" },
    { locale: "zh-CN" as const, yes: "是", no: "否" },
  ])("reports root existence, every candidate probe result and the liveness probe in $locale", async ({ locale, yes, no }) => {
    const view = await renderClient(rootScreen(), {
      locale,
      scan: makeScan({
        runRoot: "/host/gdd/runs",
        rootExists: false,
        probe: "win32",
        candidates: [
          { path: "C:\\gdd\\runs", source: "setting", exists: false },
          { path: "\\\\nas\\share\\gdd\\runs", source: "env", exists: true },
        ],
      }),
    });
    expect(view.texts()).toEqual(
      expect.arrayContaining([
        no,
        "win32",
        locale === "en"
          ? "· C:\\gdd\\runs (the plugin setting)\n✓ \\\\nas\\share\\gdd\\runs (GDD_RUN_ROOT)"
          : "· C:\\gdd\\runs (插件设置)\n✓ \\\\nas\\share\\gdd\\runs (GDD_RUN_ROOT)",
      ]),
    );
    await view.change(() => {
      view.query.setQueryData(
        ["gddRuns", "list"],
        makeScan({ runRoot: "/host/gdd/runs", rootExists: true, probe: "posix" }),
      );
    });
    expect(view.texts()).toEqual(expect.arrayContaining([yes, "posix"]));
  });

  it.each([
    { locale: "en" as const, notice: "Run root not found on the daemon host" },
    { locale: "zh-CN" as const, notice: "守护进程主机上未找到运行根目录" },
  ])("shows the missing-root notice until the root field is edited in $locale", async ({ locale, notice }) => {
    const { save } = readyHost();
    const view = await renderClient(rootScreen(), {
      locale,
      scan: makeScan({ rootExists: false, runRoot: "/absent/runs" }),
    });
    expect(rootInput(view).props.error).toBe(notice);
    await typeRoot(view, "   ");
    expect(rootInput(view).props.error).toBeNull();
    await press(view, 0);
    expect(save).not.toHaveBeenCalled();
    expect(testHost.toast.show).not.toHaveBeenCalled();
    expect(testHost.toast.error).not.toHaveBeenCalled();
    expect(rootInput(view).props.error).toBe(notice);
  });

  it.each([
    { locale: "en" as const, saved: "Saved" },
    { locale: "zh-CN" as const, saved: "已保存" },
  ])("saves the trimmed root as a full document against the edit revision in $locale", async ({ locale, saved }) => {
    const { save } = readyHost({ values: { runRoot: "", pollIntervalMs: 2000, tailLines: 80 } });
    const view = await renderClient(rootScreen(), { locale });
    await typeRoot(view, "  /host/gdd/runs  ");
    await press(view, 0);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith(
      { runRoot: "/host/gdd/runs", pollIntervalMs: 2000, tailLines: 80 },
      "revision-1",
    );
    expect(testHost.toast.show).toHaveBeenCalledWith(saved, { variant: "success" });
    expect(testHost.toast.error).not.toHaveBeenCalled();
  });

  it("saves against the revision captured at edit time, not the host's newer revision", async () => {
    const first = readyHost({ values: { runRoot: "/host/gdd/runs" }, revision: "revision-1" });
    const view = await renderClient(rootScreen());
    await typeRoot(view, "/host/gdd/runs-2");
    const second = readyHost({ values: { runRoot: "/host/gdd/runs" }, revision: "revision-2" });
    await view.update(rootScreen());
    await press(view, 0);
    expect(second.save).toHaveBeenCalledWith(
      { runRoot: "/host/gdd/runs-2", pollIntervalMs: 2000, tailLines: 80 },
      "revision-1",
    );
    expect(first.save).not.toHaveBeenCalled();
  });

  it("falls back to the host's current revision when the root field was never edited", async () => {
    readyHost({ values: { runRoot: "" }, revision: "revision-1" });
    const view = await renderClient(rootScreen());
    const second = readyHost({ values: { runRoot: "/host/gdd/runs" }, revision: "revision-2" });
    await view.update(rootScreen());
    await press(view, 0);
    expect(second.save).toHaveBeenCalledWith({ runRoot: "", pollIntervalMs: 2000, tailLines: 80 }, "revision-2");
  });

  it.each([
    { locale: "en" as const, message: "An absolute path is required." },
    { locale: "zh-CN" as const, message: "需要绝对路径。" },
  ])("rejects a relative root without persisting it in $locale", async ({ locale, message }) => {
    const { save } = readyHost({ values: { runRoot: "/host/gdd/runs" } });
    const view = await renderClient(rootScreen(), { locale });
    await typeRoot(view, "relative/gdd/runs");
    await press(view, 0);
    expect(save).not.toHaveBeenCalled();
    expect(testHost.toast.error).toHaveBeenCalledWith(message);
    expect(testHost.toast.show).not.toHaveBeenCalled();
  });

  it.each(["/home/ops/.local/state/gdd/runs", "C:\\gdd\\runs", "\\\\nas\\share\\gdd\\runs"])(
    "accepts the daemon-host path %s unchanged",
    async (path) => {
      const { save } = readyHost();
      const view = await renderClient(rootScreen());
      await typeRoot(view, path);
      await press(view, 0);
      expect(save).toHaveBeenCalledWith({ runRoot: path, pollIntervalMs: 2000, tailLines: 80 }, "revision-1");
      expect(testHost.toast.show).toHaveBeenCalledWith("Saved", { variant: "success" });
      expect(testHost.toast.error).not.toHaveBeenCalled();
    },
  );

  it("clears the root to the host default with the current revision", async () => {
    const { save } = readyHost({ values: { runRoot: "/host/gdd/runs" } });
    const view = await renderClient(rootScreen());
    await press(view, 1);
    expect(rootInput(view).props.value).toBe("");
    expect(save).toHaveBeenCalledWith({ runRoot: "", pollIntervalMs: 2000, tailLines: 80 }, "revision-1");
    expect(testHost.toast.show).toHaveBeenCalledWith("Saved", { variant: "success" });
  });

  it("does not persist a clear when the stored root is already the host default", async () => {
    const { save } = readyHost({ values: { runRoot: "" } });
    const view = await renderClient(rootScreen());
    await press(view, 1);
    expect(save).not.toHaveBeenCalled();
    expect(testHost.toast.show).not.toHaveBeenCalled();
    expect(testHost.toast.error).not.toHaveBeenCalled();
  });

  it.each([
    { locale: "en" as const, saveError: null, message: "Could not save settings." },
    { locale: "en" as const, saveError: "The settings document changed elsewhere.", message: "The settings document changed elsewhere." },
    { locale: "zh-CN" as const, saveError: null, message: "无法保存设置。" },
  ])("reports a failed root save in $locale and keeps the edited draft", async ({ locale, saveError, message }) => {
    const { save } = readyHost({ values: { runRoot: "/host/gdd/runs" }, saveError });
    const view = await renderClient(rootScreen(), { locale, scan: makeScan({ rootExists: false }) });
    await typeRoot(view, "/host/gdd/runs-2");
    save.mockResolvedValue(false);
    await press(view, 0);
    expect(save).toHaveBeenCalledTimes(1);
    expect(testHost.toast.error).toHaveBeenCalledWith(message);
    expect(testHost.toast.show).not.toHaveBeenCalled();
    expect(rootInput(view).props.error).toBeNull();
    expect(rootInput(view).props.value).toBe("/host/gdd/runs-2");
  });

  it.each([
    {
      locale: "en" as const,
      pollLabel: "Poll interval",
      pollLabels: ["1 s", "2 s", "5 s", "15 s", "30 s"],
    },
    {
      locale: "zh-CN" as const,
      pollLabel: "轮询间隔",
      pollLabels: ["1 秒", "2 秒", "5 秒", "15 秒", "30 秒"],
    },
  ])("offers the shipped poll and tail choices with the stored values selected in $locale", async ({
    locale,
    pollLabel,
    pollLabels,
  }) => {
    readyHost({ values: { runRoot: "/host/gdd/runs", pollIntervalMs: 5000, tailLines: 200 } });
    const view = await renderClient(rootScreen(), { locale });
    const [poll, tail] = selects(view);
    expect(poll.props.label).toBe(pollLabel);
    expect(poll.props.value).toBe("5000");
    expect(tail.props.value).toBe("200");
    const pollOptions: { label: string; value: string }[] = poll.props.options;
    const tailOptions: { label: string; value: string }[] = tail.props.options;
    expect(pollOptions.map((option) => option.label)).toEqual(pollLabels);
    expect(pollOptions.map((option) => option.value)).toEqual(["1000", "2000", "5000", "15000", "30000"]);
    expect(tailOptions.map((option) => option.value)).toEqual(["40", "80", "200", "500"]);
    expect(poll.props.disabled).toBe(false);
    expect(tail.props.disabled).toBe(false);
  });

  it("persists a poll interval choice as a full document against the current revision", async () => {
    const { save } = readyHost({ values: { runRoot: "/host/gdd/runs", pollIntervalMs: 2000, tailLines: 200 } });
    const view = await renderClient(rootScreen());
    await choose(view, 0, "15000");
    expect(save).toHaveBeenCalledWith(
      { runRoot: "/host/gdd/runs", pollIntervalMs: 15000, tailLines: 200 },
      "revision-1",
    );
    expect(testHost.toast.show).not.toHaveBeenCalled();
    expect(testHost.toast.error).not.toHaveBeenCalled();
  });

  it("persists a tail length choice as a full document and keeps the stored value on failure", async () => {
    const { save } = readyHost({ values: { runRoot: "/host/gdd/runs", pollIntervalMs: 2000, tailLines: 80 } });
    const view = await renderClient(rootScreen());
    save.mockResolvedValue(false);
    await choose(view, 1, "500");
    expect(save).toHaveBeenCalledWith(
      { runRoot: "/host/gdd/runs", pollIntervalMs: 2000, tailLines: 500 },
      "revision-1",
    );
    expect(testHost.toast.error).toHaveBeenCalledWith("Could not save settings.");
    expect(selects(view)[1].props.value).toBe("80");
  });

  it("disables both root actions and both choices while a save is in flight", async () => {
    readyHost({ values: { runRoot: "/host/gdd/runs", pollIntervalMs: 5000, tailLines: 200 }, saving: true });
    const view = await renderClient(rootScreen());
    const [saveRoot, clear] = actions(view);
    expect(saveRoot.props.label).toBe("Save root");
    expect(saveRoot.props.actionLabel).toBe("Save root");
    expect(clear.props.label).toBe("Use default");
    expect(clear.props.actionLabel).toBe("Use default");
    expect(saveRoot.props.disabled).toBe(true);
    expect(clear.props.disabled).toBe(true);
    for (const select of selects(view)) expect(select.props.disabled).toBe(true);
  });

  it.each([
    {
      locale: "en" as const,
      sections: ["Run root", "Status", "Resolved root", "Poll interval"],
      rows: ["Resolved root", "Resolved from", "On disk", "Liveness probe", "Candidates"],
      hint: "Absolute path on the daemon host. Empty resolves GDD_RUN_ROOT, then the documented default.",
    },
    {
      locale: "zh-CN" as const,
      sections: ["运行根目录", "状态", "解析后的根目录", "轮询间隔"],
      rows: ["解析后的根目录", "解析来源", "磁盘上存在", "存活性探测", "备选路径"],
      hint: "守护进程主机上的绝对路径。留空则取 GDD_RUN_ROOT，其次取文档默认值。",
    },
  ])("titles the settings sections and scan rows in $locale", async ({ locale, sections, rows, hint }) => {
    const view = await renderClient(rootScreen(), { locale });
    expect(nodes(view.root, "SettingsSection").map((node) => node.props.title)).toEqual(sections);
    expect(nodes(view.root, "SettingsSection")[0].props.info).toBe(hint);
    expect(nodes(view.root, "SettingsRow").map((node) => node.props.label)).toEqual(rows);
    expect(rootInput(view).props.label).toBe(sections[0]);
    expect(rootInput(view).props.hint).toBe(hint);
  });
});
