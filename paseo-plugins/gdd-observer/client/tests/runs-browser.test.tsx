import { describe, expect, it } from "vitest";
import type { ReactTestInstance } from "react-test-renderer";
import type { FollowRunOutput, ListRunsUpdate, RunEvent, RunSummary } from "../../shared/runs";
import { RunsScreen } from "../runs-browser";
import {
  hostProps,
  makeEvent,
  makeRun,
  makeScan,
  makeScanFacts,
  mountedListRows,
  nodes,
  renderClient,
  textOf,
  type RenderedClient,
} from "./harness";
import { testHost } from "./setup";

const compactProps = { ...hostProps, layout: { ...hostProps.layout, compact: true } };

async function selectRun(run: RunSummary, options: Parameters<typeof renderClient>[1] = {}) {
  const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, {
    ...options, scan: makeScan({ runs: [run] }),
  });
  if (options.pending) {
    await view.change(() => { view.query.setQueryData(["gddRuns", "list"], makeScan({ runs: [run] })); });
  }
  const row = nodes(view.root, "Pressable").find((node) => String(node.props.accessibilityLabel).includes(run.name));
  expect(row).toBeDefined();
  await view.change(() => row!.props.onPress());
  return view;
}

async function detailView(run: RunSummary, options: {
  locale?: "en" | "zh-CN";
  events?: RunEvent[];
  answerTail?: string | null;
  lineage?: FollowRunOutput["lineage"];
} = {}) {
  return selectRun(run, {
    locale: options.locale,
    follow: {
      found: true,
      summary: run,
      events: options.events ?? [],
      answerTail: options.answerTail ?? null,
      lineage: options.lineage,
    },
  });
}

function eventRows(root: ReactTestInstance): ReactTestInstance[] {
  // Event clocks are the row's first text cell, including the missing-time placeholder.
  return nodes(root, "Text").filter((node) => textOf(node) === "--:--:--").map((node) => node.parent!);
}

function factValue(root: ReactTestInstance, label: string): string {
  // FactsCard renders each fact as one label/value Text pair inside the same row View.
  const labelNode = nodes(root, "Text").find((node) => textOf(node) === label);
  expect(labelNode, `fact ${label} must render`).toBeDefined();
  return textOf(labelNode!.parent!.children[1]);
}

async function replaceEvents(view: RenderedClient, run: RunSummary, events: RunEvent[]) {
  await view.change(() => {
    view.query.setQueryData<FollowRunOutput>(["gddRuns", "follow", run.id, 80], {
      found: true, summary: run, events, answerTail: null,
    });
  });
}

describe("run browser surfaces", () => {
  it("shows the global screen's empty scan and wide no-selection guidance without a host", async () => {
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />);
    expect(view.texts()).toContain("No runs yet");
    expect(view.texts()).toContain("No run selected");
  });

  it("merges a delta's changes, additions, removals and order into the mounted list", async () => {
    const a = makeRun({ id: "a", name: "a" });
    const b = makeRun({ id: "b", name: "b" });
    const c = makeRun({ id: "c", name: "c" });
    const fresh = makeRun({ id: "d", name: "d" });
    const settled = makeRun({ id: "a", name: "a", state: "done", liveness: "settled" });
    const calls: unknown[] = [];
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      queryDefaults: { staleTime: 0 },
      invoke: async (method, input) => {
        if (method !== "runs.list") throw new Error(`Unexpected RPC: ${method}`);
        calls.push(input);
        if (calls.length === 1) return { revision: "scan-r1", ...makeScan({ runs: [a, b, c] }) };
        const delta: ListRunsUpdate = {
          ...makeScanFacts(),
          revision: "scan-r2",
          changes: [settled, fresh],
          removed: [b.id],
          order: [fresh.id, a.id, c.id],
        };
        return delta;
      },
    });
    const before = mountedListRows(view);
    expect(before.map((row) => String(row.props.accessibilityLabel))).toEqual([
      "GDD run a: running, live, model no model named",
      "GDD run b: running, live, model no model named",
      "GDD run c: running, live, model no model named",
    ]);

    await view.change(async () => {
      await view.query.refetchQueries({ queryKey: ["gddRuns", "list"] });
    });

    expect(calls).toEqual([{}, { knownRevision: "scan-r1" }]);
    const after = mountedListRows(view);
    expect(after.map((row) => String(row.props.accessibilityLabel))).toEqual([
      "GDD run d: running, live, model no model named",
      "GDD run a: done, settled, model no model named",
      "GDD run c: running, live, model no model named",
    ]);
    // The untouched run keeps the row instance it already had.
    expect(after[2]).toBe(before[2]);
  });

  it.each([
    { locale: "en" as const, missing: "Run root not found on the daemon host", empty: "No runs found under /missing", hint: "Set the run root in this plugin's settings, or export GDD_RUN_ROOT for the daemon host." },
    { locale: "zh-CN" as const, missing: "守护进程主机上未找到运行根目录", empty: "/missing 下没有找到任何运行", hint: "在此插件设置中填写运行根目录，或为守护进程主机设置 GDD_RUN_ROOT。" },
  ])("shows missing-root diagnosis and setup guidance in $locale", async ({ locale, missing, empty, hint }) => {
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, {
      locale, scan: makeScan({ rootExists: false, runRoot: "/missing", warnings: ["fixture scan warning"] }),
    });
    expect(view.texts()).toEqual(expect.arrayContaining([missing, empty, hint, "fixture scan warning"]));
  });

  it("shows a loading surface while the initial run scan is pending", async () => {
    const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, { pending: true });
    expect(nodes(view.root, "Loading")).toHaveLength(1);
    expect(view.texts()).not.toContain("No runs yet");
  });

  it.each(["en", "zh-CN"] as const)("shows the list error instead of indefinite loading in %s", async (locale) => {
    const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, { locale, pending: true });
    await view.change(() => {
      view.query.getQueryCache().find({ queryKey: ["gddRuns", "list"] })!.setState({ status: "error", error: new Error("fixture denied") });
    });
    expect(view.texts()).toContain(locale === "en" ? "Could not read runs: fixture denied" : "无法读取运行列表：fixture denied");
    expect(nodes(view.root, "Loading")).toHaveLength(0);
  });

  it.each([
    ["setting", "Resolved from the plugin setting · Liveness probe: unavailable"],
    ["env", "Resolved from GDD_RUN_ROOT · Liveness probe: unavailable"],
    ["xdg", "Resolved from XDG_STATE_HOME · Liveness probe: unavailable"],
    ["home", "Resolved from the home state directory · Liveness probe: unavailable"],
    ["localappdata", "Resolved from LOCALAPPDATA · Liveness probe: unavailable"],
    ["default", "Resolved from the documented default · Liveness probe: unavailable"],
  ] as const)("names the %s root source independently of process liveness", async (rootSource, expected) => {
    const view = await renderClient(<RunsScreen {...hostProps} params={{}} />, { scan: makeScan({ rootSource }) });
    expect(view.texts()).toContain(expected);
  });

  it.each([
    { locale: "en" as const, label: "GDD run stage-implement: running, stale, model observed/actual", back: "All runs", counters: "1,234 turns · 5,678 tools · $0.0040", duration: "Duration 1m 01s", stale: "The recorded process is gone and the run never finalized. Treat it as stale, not done." },
    { locale: "zh-CN" as const, label: "GDD 运行 stage-implement：运行中，疑似失联，模型 observed/actual", back: "全部运行", counters: "1,234 轮 · 5,678 次工具调用 · $0.0040", duration: "耗时 1m 01s", stale: "记录的进程已不存在，且该运行从未收尾。请视为失联，而不是完成。" },
  ])("keeps state, liveness, model, counters and navigation accessible in $locale", async ({ locale, label, back, counters, duration, stale }) => {
    const run = makeRun({ liveness: "stale", turns: 1234, toolCalls: 5678, costUsd: 0.004, elapsedS: 61,
      model: { requested: "@requested", requestedProvider: null, requestedModel: null, thinking: null,
        observed: [{ provider: "observed", model: "actual", api: null, messages: 2 }] },
      currentTool: "bash", currentToolIntent: "Running checks", eventsTruncated: true,
    });
    const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, {
      locale, scan: makeScan({ runs: [run] }), follow: { found: true, summary: run, events: [], answerTail: null },
    });
    const row = nodes(view.root, "Pressable").find((node) => node.props.accessibilityLabel === label)!;
    expect(row, "run navigation must retain its translated accessibility label").toBeDefined();
    expect(row.props.accessibilityRole).toBe("button");
    expect(view.texts()).toEqual(expect.arrayContaining([counters, duration, stale, "bash · Running checks"]));
    await view.change(() => row.props.onPress());
    const backButton = nodes(view.root, "Pressable").find((node) => node.props.accessibilityLabel === back)!;
    expect(backButton).toBeDefined();
    expect(backButton.props.accessibilityRole).toBe("button");
    expect(view.texts()).not.toContain(locale === "en" ? "Runs" : "运行");
    await view.change(() => backButton.props.onPress());
    expect(nodes(view.root, "Pressable").some((node) => node.props.accessibilityLabel === label)).toBe(true);
  });

  it.each([
    ["running", "Elapsed 1m 00s"], ["settled", "Duration 1m 00s"],
    ["stale", "Duration 1m 00s"], ["unknown", "Duration 1m 00s"],
  ] as const)("derives duration wording from %s liveness rather than run state", async (liveness, expected) => {
    const view = await detailView(makeRun({ state: "running", liveness }));
    expect(view.texts()).toContain(expected);
  });

  it.each(["en", "zh-CN"] as const)("distinguishes missing counters from reported zeros and omits invalid elapsed time in %s", async (locale) => {
    const run = makeRun({ elapsedS: null });
    const view = await renderClient(<RunsScreen {...compactProps} params={{}} />, {
      locale, scan: makeScan({ runs: [run] }),
    });
    expect(view.texts()).toContain(locale === "en" ? "waiting for counters" : "等待计数");
    expect(view.texts().some((text) => /^(Elapsed|Duration|已运行|耗时) /.test(text))).toBe(false);
    await view.change(() => {
      view.query.setQueryData(["gddRuns", "list"], makeScan({ runs: [makeRun({ turns: 0, toolCalls: 0, costUsd: 0, elapsedS: null })] }));
    });
    expect(view.texts()).toContain(locale === "en" ? "0 turns · 0 tools · $0" : "0 轮 · 0 次工具调用 · $0");
    expect(view.texts()).not.toContain(locale === "en" ? "waiting for counters" : "等待计数");
  });

  it.each([
    { locale: "en" as const, provenance: "counters from events.ndjson · partial · partial log", warnings: ["state.json is missing, so this run is unknown rather than successful.", "state.json could not be parsed.", "No lock file and no recorded pid.", "No pid is recorded, so liveness cannot be checked.", "Liveness is unproven for this run.", "events.ndjson could not be read."], suppressed: "The launcher spliced the event log; counters cover the retained part only." },
    { locale: "zh-CN" as const, provenance: "计数来自 events.ndjson · 不完整 · 部分日志", warnings: ["缺少 state.json，该运行状态未知，不能视为成功。", "state.json 无法解析。", "没有 lock 文件，也没有记录进程号。", "没有记录进程号，无法检查存活性。", "该运行的存活性无法确认。", "events.ndjson 无法读取。"], suppressed: "启动器已对事件日志做拼接裁剪，计数仅覆盖保留部分。" },
  ])("reads warning labels in supplied order after provenance and partial qualifications in $locale", async ({ locale, provenance, warnings, suppressed }) => {
    const run = makeRun({ countersFrom: "events", countersPartial: true, eventsTruncated: true,
      warnings: ["state-missing", "state-unreadable", "no-lock", "no-pids", "liveness-unknown", "log-unreadable", "log-truncated"],
      currentTool: "read", currentToolIntent: "Inspecting fixture", lastError: "fixture error",
    });
    const view = await detailView(run, { locale });
    expect(view.texts()).toContain(provenance);
    expect(view.texts().filter((text) => warnings.includes(text))).toEqual(warnings);
    expect(view.texts().indexOf(provenance)).toBeLessThan(view.texts().indexOf(warnings[0]));
    expect(view.texts()).not.toContain(suppressed);
    expect(view.texts()).toContain("read · Inspecting fixture");
    expect(view.texts()).toContain(locale === "en" ? "Last error: fixture error" : "最近错误: fixture error");
  });

  it.each([["state", "counters from state.json"], ["events", "counters from events.ndjson"], ["none", ""]] as const)(
    "shows only the available %s counter provenance", async (countersFrom, expected) => {
      const view = await detailView(makeRun({ countersFrom }));
      if (expected !== "") expect(view.texts()).toContain(expected);
      for (const other of ["counters from state.json", "counters from events.ndjson"].filter((value) => value !== expected)) {
        expect(view.texts()).not.toContain(other);
      }
    },
  );

  it("shows only populated bookkeeping facts, retaining zero exit and answer counts", async () => {
    const view = await detailView(makeRun({ exitCode: 0, answerChars: 0, eventsBytes: 1024,
      maxTime: "", sessionId: "", pids: { pid: null, agentPid: null },
    }));
    expect(view.texts()).toEqual(expect.arrayContaining(["Exit", "0", "Events", "1.0 KB", "Answer", "0 answer chars"]));
    for (const absent of ["Started", "Ended", "Max time", "Session", "PIDs"]) expect(view.texts()).not.toContain(absent);
  });

  it("shows populated run times, process IDs, session, limit, directory and last update", async () => {
    const run = makeRun({ startedAt: "2026-11-14T12:34:56Z", endedAt: "2026-11-14T13:34:56Z",
      maxTime: "12h", sessionId: "session-fixture", pids: { pid: 123, agentPid: 456 }, lastEventAt: "2026-11-14T13:34:56Z" });
    const view = await detailView(run);
    expect(view.texts()).toEqual(expect.arrayContaining(["Nov 14, 12:34 PM", "Nov 14, 01:34 PM", "12h", "session-fixture", "launcher 123 · agent 456", run.runDir, "Fixture host · Updated Nov 14, 01:34 PM"]));
  });

  it.each([
    { locale: "en" as const, title: "Run lineage", goal: "Goal", stage: "Stage", agent: "Initiating Paseo agent", session: "Session", notRecorded: "Not recorded", missing: "No lineage recorded for this run. Previous runs and direct adapter starts have none." },
    { locale: "zh-CN" as const, title: "运行血缘", goal: "目标", stage: "阶段", agent: "发起 Paseo agent", session: "会话", notRecorded: "未记录", missing: "该运行未记录血缘信息。此前的运行和直接通过适配器启动的运行均无记录。" },
  ])("keeps recorded dispatch lineage distinct from the run's own session and names unknown agents in $locale", async ({ locale, title, goal, stage, agent, session, notRecorded, missing }) => {
    const run = makeRun({ sessionId: "session-fixture" });
    const view = await detailView(run, {
      locale,
      lineage: { goal: "goal-fixture", stage: "stage-fixture", parentAgentId: "parent-fixture" },
    });
    expect(view.texts()).toEqual(expect.arrayContaining([title, goal, "goal-fixture", stage, "stage-fixture"]));
    expect(factValue(view.root, agent)).toBe("parent-fixture");
    expect(factValue(view.root, session)).toBe("session-fixture");
    await view.change(() => {
      view.query.setQueryData<FollowRunOutput>(["gddRuns", "follow", run.id, 80], {
        found: true, summary: run, events: [], answerTail: null,
        lineage: { goal: "goal-fixture", stage: "stage-fixture" },
      });
    });
    expect(factValue(view.root, agent)).toBe(notRecorded);
    await view.change(() => {
      view.query.setQueryData<FollowRunOutput>(["gddRuns", "follow", run.id, 80], {
        found: true, summary: run, events: [], answerTail: null,
      });
    });
    expect(view.texts()).toContain(missing);
    expect(view.texts()).not.toContain(notRecorded);
  });

  it("shows event content, fallback clocks, tool names, intent precedence and the answer fragment", async () => {
    const view = await detailView(makeRun(), {
      events: [makeEvent({ type: "tool_execution_start", tool: "bash", intent: "Running test", detail: "not the intent" }),
        makeEvent({ type: "error", at: "2026-11-14T12:34:56Z", detail: "fixture failed" })],
      answerTail: "# Fixture answer",
    });
    expect(view.texts()).toEqual(expect.arrayContaining(["Recent events · last 80 lines", "--:--:--", "bash", "tool_execution_start · Running test", "12:34:56 PM", "error · fixture failed", "Tail of the answer; the plugin reads the last part of the file."]));
    expect(nodes(view.root, "Markdown")[0].props.children).toBe("# Fixture answer");
    expect(view.texts().join("\n")).not.toContain("not the intent");
  });

  it.each(["en", "zh-CN"] as const)("shows pending, gone and failed detail states without inventing success in %s", async (locale) => {
    const run = makeRun();
    const view = await selectRun(run, { locale, pending: true });
    expect(view.texts()).toContain(locale === "en" ? "Scanning…" : "扫描中…");
    expect(view.texts()).toContain(locale === "en" ? "No events yet" : "还没有事件");
    expect(view.texts()).toContain(locale === "en" ? "answer.md appears when the run finalizes." : "运行收尾时会写入 answer.md。");
    await view.change(() => {
      view.query.setQueryData(["gddRuns", "follow", run.id, 80], { found: false, summary: null, events: [], answerTail: null });
    });
    expect(view.texts()).toContain(locale === "en" ? "This run is no longer on disk." : "该运行已不在磁盘上。");
    await view.change(() => {
      view.query.getQueryCache().find({ queryKey: ["gddRuns", "follow", run.id, 80] })!.setState({ status: "error", error: new Error("fixture denied") });
    });
    expect(view.texts()).toContain(locale === "en" ? "Could not read this run: fixture denied" : "无法读取该运行：fixture denied");
  });

  it.each([
    { locale: "en" as const, label: "Copy path: /fixture/state.json", copied: "Path copied", failed: "Could not copy the path.", missing: "no" },
    { locale: "zh-CN" as const, label: "复制路径: /fixture/state.json", copied: "已复制路径", failed: "无法复制路径。", missing: "否" },
  ])("labels file-path buttons and reports copy success or failure in $locale", async ({ locale, label, copied, failed, missing }) => {
    const run = makeRun();
    const view = await selectRun(run, {
      locale, follow: { found: true, summary: run, events: [], answerTail: null },
      paths: { found: true, scannedAt: "2026-11-14T12:00:00Z", paths: [
        { label: "state.json", path: "/fixture/state.json", exists: true, bytes: 42 },
        { label: "answer.md", path: "/fixture/answer.md", exists: false, bytes: null },
      ] },
    });
    const button = nodes(view.root, "Pressable").find((node) => node.props.accessibilityLabel === label)!;
    expect(button.props.accessibilityRole).toBe("button");
    expect(view.texts()).toEqual(expect.arrayContaining(["state.json", "42 B", "answer.md", missing]));
    await view.change(() => button.props.onPress());
    expect(testHost.copyText).toHaveBeenCalledWith("/fixture/state.json");
    expect(testHost.toast.show).toHaveBeenCalledWith(copied, { variant: "success" });
    testHost.copyText.mockRejectedValueOnce(new Error("clipboard denied"));
    await view.change(() => button.props.onPress());
    expect(testHost.toast.error).toHaveBeenCalledWith(failed);
  });

  it("keeps overlapping event row instances mounted when the retained window slides", async () => {
    const run = makeRun();
    const a = makeEvent({ detail: "A" });
    const b = makeEvent({ detail: "B" });
    const c = makeEvent({ detail: "C" });
    const d = makeEvent({ detail: "D" });
    const view = await detailView(run, { events: [a, b, c] });
    const before = eventRows(view.root);
    expect(before.map(textOf)).toEqual(["--:--:--turn_endturn_end · A", "--:--:--turn_endturn_end · B", "--:--:--turn_endturn_end · C"]);
    await replaceEvents(view, run, [b, c, d]);
    const after = eventRows(view.root);
    expect(after[0] === before[1], "retained B row stays mounted").toBe(true);
    expect(after[1] === before[2], "retained C row stays mounted").toBe(true);
    expect(after[2] === before[2], "new D row is not the former C row").toBe(false);
    expect(after.map(textOf)).toEqual(["--:--:--turn_endturn_end · B", "--:--:--turn_endturn_end · C", "--:--:--turn_endturn_end · D"]);
  });

  it("keeps identical event occurrences distinct and stable across append and unrelated head eviction", async () => {
    const run = makeRun();
    const head = makeEvent({ detail: "head" });
    const repeat = makeEvent({ type: "tool_execution_start", tool: "read", intent: "same" });
    const view = await detailView(run, { events: [head, repeat, { ...repeat }] });
    const before = eventRows(view.root);
    expect(before[1] === before[2], "identical occurrences occupy distinct rows").toBe(false);
    await replaceEvents(view, run, [head, repeat, { ...repeat }, { ...repeat }]);
    const appended = eventRows(view.root);
    expect(appended[1] === before[1], "first occurrence survives append").toBe(true);
    expect(appended[2] === before[2], "second occurrence survives append").toBe(true);
    expect(appended[3] === appended[2], "new occurrence gets a distinct row").toBe(false);
    await replaceEvents(view, run, [repeat, { ...repeat }, { ...repeat }]);
    const slid = eventRows(view.root);
    expect(slid).toHaveLength(3);
    expect(slid[0] === appended[1], "first occurrence survives unrelated head eviction").toBe(true);
    expect(slid[1] === appended[2], "second occurrence survives unrelated head eviction").toBe(true);
    expect(slid[2] === appended[3], "third occurrence survives unrelated head eviction").toBe(true);
  });
});
