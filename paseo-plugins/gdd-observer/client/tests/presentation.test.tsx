import { describe, expect, it } from "vitest";
import type { ReactTestInstance } from "react-test-renderer";
import {
  RUN_LIVENESS,
  RUN_ROOT_SOURCES,
  RUN_STATES,
  RUN_WARNINGS,
  type RunLiveness,
  type RunModel,
  type RunModelUsage,
  type RunRootSource,
  type RunState,
  type RunStats,
  type RunWarning,
} from "../../shared/runs";
import { FactsCard } from "../facts";
import {
  STATE_ORDER,
  counterSourceKey,
  livenessColor,
  livenessKey,
  sourceKey,
  stateColor,
  stateKey,
  warningKey,
} from "../labels";
import { ModelCard, ModelChip } from "../model-card";
import { LivenessBadge, StateBadge, StatusStrip } from "../status-strip";
import { hostProps, makeScan, nodes, renderClient, textOf } from "./harness";

const theme = hostProps.theme;
const layout = hostProps.layout;

function stats(overrides: Partial<RunStats> = {}): RunStats {
  return { ...makeScan().stats, ...overrides };
}

function model(overrides: Partial<RunModel> = {}): RunModel {
  return {
    requested: null,
    requestedProvider: null,
    requestedModel: null,
    thinking: null,
    observed: [],
    ...overrides,
  };
}

function usage(overrides: Partial<RunModelUsage> = {}): RunModelUsage {
  return { provider: null, model: null, api: null, messages: 0, ...overrides };
}

function styleEntries(style: unknown): Array<Record<string, unknown>> {
  return Array.isArray(style)
    ? style.filter((entry): entry is Record<string, unknown> => entry !== null && typeof entry === "object")
    : style !== null && typeof style === "object" ? [style as Record<string, unknown>] : [];
}

function barSegments(root: ReactTestInstance) {
  return nodes(root, "View")
    .map((node) => styleEntries(node.props.style).find((entry) => "flexGrow" in entry))
    .filter((entry): entry is Record<string, unknown> => entry !== undefined)
    .map(({ flexGrow, backgroundColor }) => ({ flexGrow, backgroundColor }));
}

function badge(root: ReactTestInstance) {
  const text = nodes(root, "Text")[0];
  return {
    label: textOf(text),
    textColor: styleEntries(text.props.style).find((entry) => "color" in entry)?.color,
    borderColor: nodes(root, "View")
      .flatMap((node) => styleEntries(node.props.style))
      .find((entry) => "borderColor" in entry)?.borderColor,
  };
}

function textColorOf(root: ReactTestInstance, label: string): unknown {
  const text = nodes(root, "Text").find((node) => textOf(node) === label)!;
  return styleEntries(text.props.style).find((entry) => "color" in entry)?.color;
}

const fullStats: RunStats = {
  total: 1248,
  byState: { running: 1234, done: 2, failed: 3, killed: 4, unknown: 5 },
  byLiveness: { running: 3, settled: 1200, stale: 7, unknown: 38 },
  turns: 1234,
  toolCalls: 5678,
  costUsd: 0.004,
  countedRuns: 1200,
  partialRuns: 2,
  flagged: 1,
};

describe("status summary", () => {
  it("reads totals, liveness and states in running, done, failed, killed, unknown order with proportional segments", async () => {
    const view = await renderClient(<StatusStrip stats={fullStats} theme={theme} layout={layout} />);
    expect(view.texts()).toEqual([
      "1248 runs",
      "3 live",
      "7 stale",
      "1,234",
      "running",
      "2",
      "done",
      "3",
      "failed",
      "4",
      "killed",
      "5",
      "unknown",
      "1,234 turns · 5,678 tools · $0.0040",
      "reported by 1200 of 1248 runs · 2 runs are partial · 1 flagged",
    ]);
    expect(barSegments(view.root)).toEqual([
      { flexGrow: 1234, backgroundColor: theme.colors.accent },
      { flexGrow: 2, backgroundColor: theme.colors.statusSuccess },
      { flexGrow: 3, backgroundColor: theme.colors.statusDanger },
      { flexGrow: 4, backgroundColor: theme.colors.statusWarning },
      { flexGrow: 5, backgroundColor: theme.colors.foregroundMuted },
    ]);
  });

  it("shows grouped counters, Chinese legend labels and qualifications in Chinese", async () => {
    const view = await renderClient(<StatusStrip stats={fullStats} theme={theme} layout={layout} />, {
      locale: "zh-CN",
    });
    expect(view.texts()).toEqual([
      "1248 个运行",
      "3 个存活",
      "7 个疑似失联",
      "1,234",
      "运行中",
      "2",
      "完成",
      "3",
      "失败",
      "4",
      "被终止",
      "5",
      "未知",
      "1,234 轮 · 5,678 次工具调用 · $0.0040",
      "由 1248 个运行中的 1200 个上报 · 2 个计数不完整 · 1 个有告警",
    ]);
  });

  it("says no counters are reported for an empty scan and draws no bar", async () => {
    const view = await renderClient(<StatusStrip stats={stats()} theme={theme} layout={layout} />);
    expect(view.texts().filter((text) => text !== "")).toEqual([
      "0 runs",
      "0",
      "running",
      "0",
      "done",
      "0",
      "failed",
      "0",
      "killed",
      "0",
      "unknown",
      "no counters reported yet",
    ]);
    expect(barSegments(view.root)).toEqual([]);
  });

  it("keeps zero counters, drops zero-count segments and qualifies singular partial runs", async () => {
    const partial = stats({
      total: 10,
      byState: { running: 4, done: 3, failed: 2, killed: 1, unknown: 0 },
      byLiveness: { running: 4, settled: 3, stale: 2, unknown: 1 },
      turns: 3,
      toolCalls: 0,
      costUsd: 0,
      countedRuns: 3,
      partialRuns: 1,
      flagged: 0,
    });
    const view = await renderClient(<StatusStrip stats={partial} theme={theme} layout={layout} />);
    expect(view.texts()).toEqual([
      "10 runs",
      "4 live",
      "2 stale",
      "4",
      "running",
      "3",
      "done",
      "2",
      "failed",
      "1",
      "killed",
      "0",
      "unknown",
      "3 turns · 0 tools · $0",
      "reported by 3 of 10 runs · 1 run is partial",
    ]);
    expect(barSegments(view.root)).toEqual([
      { flexGrow: 4, backgroundColor: theme.colors.accent },
      { flexGrow: 3, backgroundColor: theme.colors.statusSuccess },
      { flexGrow: 2, backgroundColor: theme.colors.statusDanger },
      { flexGrow: 1, backgroundColor: theme.colors.statusWarning },
    ]);

    const flagged = stats({
      total: 10,
      byState: { running: 4, done: 3, failed: 2, killed: 1, unknown: 0 },
      byLiveness: { running: 4, settled: 3, stale: 2, unknown: 1 },
      turns: 2,
      toolCalls: 5,
      costUsd: 0.5,
      countedRuns: 2,
      partialRuns: 0,
      flagged: 1,
    });
    const flaggedView = await renderClient(
      <StatusStrip stats={flagged} theme={theme} layout={layout} />,
    );
    expect(flaggedView.texts().at(-1)).toBe("reported by 2 of 10 runs · 1 flagged");
  });
});

const stateLabels: Record<RunState, string> = {
  running: "running",
  done: "done",
  failed: "failed",
  killed: "killed",
  unknown: "unknown",
};

const livenessLabels: Record<RunLiveness, string> = {
  running: "live",
  settled: "settled",
  stale: "stale",
  unknown: "unknown",
};

const stateColors: Record<RunState, string> = {
  running: theme.colors.accent,
  done: theme.colors.statusSuccess,
  failed: theme.colors.statusDanger,
  killed: theme.colors.statusWarning,
  unknown: theme.colors.foregroundMuted,
};

const livenessColors: Record<RunLiveness, string> = {
  running: theme.colors.statusSuccess,
  settled: theme.colors.foregroundMuted,
  stale: theme.colors.statusWarning,
  unknown: theme.colors.foregroundMuted,
};

describe("state and liveness badges", () => {
  it("labels and colors every state and every liveness with its own token mapping", async () => {
    for (const state of RUN_STATES) {
      const view = await renderClient(<StateBadge state={state} theme={theme} layout={layout} />);
      expect(badge(view.root)).toEqual({
        label: stateLabels[state],
        textColor: stateColors[state],
        borderColor: stateColors[state],
      });
    }
    for (const liveness of RUN_LIVENESS) {
      const view = await renderClient(
        <LivenessBadge liveness={liveness} theme={theme} layout={layout} />,
      );
      expect(badge(view.root)).toEqual({
        label: livenessLabels[liveness],
        textColor: livenessColors[liveness],
        borderColor: livenessColors[liveness],
      });
    }
  });

  it("keeps a running record's state color independent of its liveness color", async () => {
    const running = await renderClient(
      <>
        <StateBadge state="running" theme={theme} layout={layout} />
        <LivenessBadge liveness="running" theme={theme} layout={layout} />
      </>,
    );
    expect(textColorOf(running.root, "running")).toBe(theme.colors.accent);
    expect(textColorOf(running.root, "live")).toBe(theme.colors.statusSuccess);
    expect(stateColor("running", theme)).toBe(theme.colors.accent);
    expect(livenessColor("running", theme)).toBe(theme.colors.statusSuccess);

    const settled = await renderClient(
      <>
        <StateBadge state="done" theme={theme} layout={layout} />
        <LivenessBadge liveness="stale" theme={theme} layout={layout} />
      </>,
    );
    expect(textColorOf(settled.root, "done")).toBe(theme.colors.statusSuccess);
    expect(textColorOf(settled.root, "stale")).toBe(theme.colors.statusWarning);
  });
});

describe("label derivation", () => {
  it("reads the state legend as running, done, failed, killed, unknown", () => {
    expect(STATE_ORDER).toEqual(["running", "done", "failed", "killed", "unknown"]);
  });

  it("maps every state, liveness, root source and warning to its literal translation key", () => {
    const stateKeys: Record<RunState, string> = {
      running: "state.running",
      done: "state.done",
      failed: "state.failed",
      killed: "state.killed",
      unknown: "state.unknown",
    };
    for (const state of RUN_STATES) expect(stateKey(state)).toBe(stateKeys[state]);

    const livenessKeys: Record<RunLiveness, string> = {
      running: "liveness.running",
      settled: "liveness.settled",
      stale: "liveness.stale",
      unknown: "liveness.unknown",
    };
    for (const liveness of RUN_LIVENESS) expect(livenessKey(liveness)).toBe(livenessKeys[liveness]);

    const sourceKeys: Record<RunRootSource, string> = {
      setting: "source.setting",
      env: "source.env",
      xdg: "source.xdg",
      home: "source.home",
      localappdata: "source.localappdata",
      default: "source.default",
    };
    for (const source of RUN_ROOT_SOURCES) expect(sourceKey(source)).toBe(sourceKeys[source]);

    const warningKeys: Record<RunWarning, string> = {
      "state-missing": "warning.state-missing",
      "state-unreadable": "warning.state-unreadable",
      "no-lock": "warning.no-lock",
      "no-pids": "warning.no-pids",
      "liveness-unknown": "warning.liveness-unknown",
      "log-unreadable": "warning.log-unreadable",
      "log-truncated": "warning.log-truncated",
    };
    for (const warning of RUN_WARNINGS) expect(warningKey(warning)).toBe(warningKeys[warning]);

    expect(counterSourceKey("state")).toBe("counter.fromState");
    expect(counterSourceKey("events")).toBe("counter.fromEvents");
    expect(counterSourceKey("none")).toBeNull();
  });

});

describe("model chip", () => {
  it("prefers the first observed usage and shows a differing request beside it", async () => {
    const view = await renderClient(
      <ModelChip
        model={model({
          requested: "link/@sol_high",
          observed: [usage({ provider: "anthropic", model: "claude-opus-4", api: "messages", messages: 5 })],
        })}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual(["anthropic/claude-opus-4", "requested link/@sol_high"]);
  });

  it("does not repeat the request when it names the observed model", async () => {
    const view = await renderClient(
      <ModelChip
        model={model({
          requested: "anthropic/claude-opus-4",
          observed: [usage({ provider: "anthropic", model: "claude-opus-4", messages: 1 })],
        })}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual(["anthropic/claude-opus-4"]);
  });

  it("falls back to the requested name and then to no model named", async () => {
    const requested = await renderClient(
      <ModelChip model={model({ requested: "link/@sol_high" })} theme={theme} layout={layout} />,
    );
    expect(requested.texts()).toEqual(["link/@sol_high"]);

    const none = await renderClient(<ModelChip model={model()} theme={theme} layout={layout} />);
    expect(none.texts()).toEqual(["no model named"]);
  });

  it("translates the differing-request suffix in Chinese", async () => {
    const view = await renderClient(
      <ModelChip
        model={model({
          requested: "link/@sol_high",
          observed: [usage({ provider: "anthropic", model: "claude-opus-4" })],
        })}
        theme={theme}
        layout={layout}
      />,
      { locale: "zh-CN" },
    );
    expect(view.texts()).toEqual(["anthropic/claude-opus-4", "请求 link/@sol_high"]);
  });
});

describe("model card", () => {
  it("lists first-observed facts, requested values and remaining models in first-seen order", async () => {
    const view = await renderClient(
      <ModelCard
        model={model({
          requested: "@sol_high",
          requestedProvider: "openai",
          requestedModel: "gpt-5",
          thinking: "high",
          observed: [
            usage({ provider: "anthropic", model: "claude-opus-4", api: "messages", messages: 5 }),
            usage({ provider: "google", model: "gemini-3-pro", api: "generateContent", messages: 1 }),
            usage({ provider: "openai", model: "gpt-5", api: "responses", messages: 2 }),
          ],
        })}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual([
      "Model",
      "Ran on",
      "claude-opus-4",
      "Provider",
      "anthropic",
      "API",
      "messages",
      "Requested",
      "@sol_high",
      "Thinking",
      "high",
      "Also used: google/gemini-3-pro (1 message)",
      "Also used: openai/gpt-5 (2 messages)",
    ]);
  });

  it("falls back to the tool default with its explanation when nothing was requested", async () => {
    const view = await renderClient(<ModelCard model={model()} theme={theme} layout={layout} />);
    expect(view.texts()).toEqual([
      "Model",
      "Ran on",
      "the run's events name no model yet",
      "Requested",
      "tool default",
      "Thinking",
      "tool default",
      'The launcher requested no model, so the tool\'s own default link chose it; "Ran on" is the model that default resolved to.',
    ]);
  });

  it("shows the requested provider before any observation and suppresses the absent API", async () => {
    const view = await renderClient(
      <ModelCard
        model={model({ requested: "link/@sol_high", requestedProvider: "anthropic", thinking: "high" })}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual([
      "Model",
      "Ran on",
      "the run's events name no model yet",
      "Provider",
      "anthropic",
      "Requested",
      "link/@sol_high",
      "Thinking",
      "high",
    ]);
  });

  it("suppresses empty and null facts while a zero message count stays visible", async () => {
    const view = await renderClient(
      <ModelCard
        model={model({
          requested: "",
          observed: [usage({ provider: "x", model: "y" }), usage({ api: "messages", messages: 0 })],
        })}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual([
      "Model",
      "Ran on",
      "y",
      "Provider",
      "x",
      "Thinking",
      "tool default",
      "Also used: messages (0 messages)",
    ]);
  });

  it("keeps first-seen ordering and message plurals in Chinese", async () => {
    const view = await renderClient(
      <ModelCard
        model={model({
          requestedProvider: "openai",
          observed: [
            usage({ provider: "anthropic", model: "claude-opus-4", api: "messages", messages: 5 }),
            usage({ provider: "google", model: "gemini-3-pro", api: "generateContent", messages: 1 }),
            usage({ provider: "openai", model: "gpt-5", api: "responses", messages: 2 }),
          ],
        })}
        theme={theme}
        layout={layout}
      />,
      { locale: "zh-CN" },
    );
    expect(view.texts()).toEqual([
      "模型",
      "实际使用",
      "claude-opus-4",
      "提供方",
      "anthropic",
      "接口协议",
      "messages",
      "请求值",
      "工具默认",
      "思考等级",
      "工具默认",
      "另外使用：google/gemini-3-pro（1 条消息）",
      "另外使用：openai/gpt-5（2 条消息）",
      "启动器没有请求具体模型，改由工具自身的默认 link 决定；“实际使用”即该默认解析出的模型。",
    ]);
  });
});

describe("facts card", () => {
  it("drops null and empty values, keeps zero, and preserves fact order", async () => {
    const view = await renderClient(
      <FactsCard
        title="Counters"
        icon="Hash"
        facts={[
          ["Turns", "0"],
          ["Tools", ""],
          ["Cost", null],
          ["Session", "s-1"],
        ]}
        theme={theme}
        layout={layout}
      />,
    );
    expect(view.texts()).toEqual(["Counters", "Turns", "0", "Session", "s-1"]);
  });
});
