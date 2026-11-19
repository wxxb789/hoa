import { afterAll, describe, expect, it } from "vitest";
import { PluginTranslationRuntime } from "@getpaseo/plugin/client/host";
import type { RunModel, RunModelUsage } from "../../shared/runs";
import {
  clockOf,
  counterLine,
  countersLine,
  eventClockOf,
  firstUsage,
  formatBytes,
  formatCost,
  formatCount,
  formatDuration,
  usageLabel,
  type CounterKey,
} from "../format";
import { messages } from "../messages";

/**
 * Formats the run surfaces show. Expected strings are literal; the timestamp cases rely on the
 * client project's UTC clock (vitest.config.ts) and the real shipped en/zh-CN resources.
 */

/** The real SDK translations, resolved the same way the rendered surfaces resolve them. */
function labelFor(locale: "en" | "zh-CN") {
  const runtime = new PluginTranslationRuntime({
    getLocale: () => locale,
    subscribe: () => () => {},
  });
  return {
    runtime,
    label: (key: CounterKey, value: string) => runtime.t(messages, key, { value }),
  };
}

const english = labelFor("en");
const chinese = labelFor("zh-CN");

afterAll(() => {
  english.runtime.dispose();
  chinese.runtime.dispose();
});

describe("formatDuration", () => {
  it.each<[number | null, string | null]>([
    [null, null],
    [Number.NaN, null],
    [Number.POSITIVE_INFINITY, null],
    [Number.NEGATIVE_INFINITY, null],
    [-5, "0s"],
    [0, "0s"],
    [0.4, "0s"],
    [0.5, "1s"],
    [59, "59s"],
    [59.5, "1m 00s"],
    [60, "1m 00s"],
    [61, "1m 01s"],
    [599, "9m 59s"],
    [3599, "59m 59s"],
    [3599.6, "1h 00m"],
    [3600, "1h 00m"],
    [3661, "1h 01m"],
    [7322, "2h 02m"],
    [86400, "24h 00m"],
  ])("turns %s seconds into %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe("formatCost", () => {
  it.each<[number | null, string | null]>([
    [null, null],
    [Number.NaN, null],
    [Number.POSITIVE_INFINITY, null],
    [0, "$0"],
    [0.004, "$0.0040"],
    [0.005, "$0.0050"],
    [0.0099, "$0.0099"],
    [0.01, "$0.01"],
    [0.016, "$0.02"],
    [1.234, "$1.23"],
    [12.5, "$12.50"],
    [1234.5, "$1234.50"],
  ])("turns %s USD into %s", (usd, expected) => {
    expect(formatCost(usd)).toBe(expected);
  });
});

describe("formatCount", () => {
  it.each<[string, number, string]>([
    ["en", 0, "0"],
    ["en", 999, "999"],
    ["en", 1000, "1,000"],
    ["en", 1234, "1,234"],
    ["en", 1234567, "1,234,567"],
    ["en", -1234, "-1,234"],
    ["zh-CN", 1234, "1,234"],
    ["zh-CN", 5678, "5,678"],
    ["zh-CN", 1234567, "1,234,567"],
  ])("groups %s count %s as %s", (locale, value, expected) => {
    expect(formatCount(value, locale)).toBe(expected);
  });

  it("passes non-finite counts through as text", () => {
    expect(formatCount(Number.NaN, "en")).toBe("NaN");
    expect(formatCount(Number.POSITIVE_INFINITY, "en")).toBe("Infinity");
  });
});

describe("formatBytes", () => {
  it.each<[number | null, string | null]>([
    [null, null],
    [Number.NaN, null],
    [Number.POSITIVE_INFINITY, null],
    [0, "0 B"],
    [1023, "1023 B"],
    [1024, "1.0 KB"],
    [9730, "9.5 KB"],
    [10240, "10 KB"],
    [1048576, "1.0 MB"],
    [5242880, "5.0 MB"],
    [10485760, "10 MB"],
    [1073741824, "1.0 GB"],
    [2199023255552, "2048 GB"],
  ])("turns %s bytes into %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe("clockOf", () => {
  it("formats the date and wall clock in each shipped locale, in UTC", () => {
    expect(clockOf("2026-11-14T12:34:56Z", "en")).toBe("Nov 14, 12:34 PM");
    expect(clockOf("2026-01-05T00:00:00Z", "en")).toBe("Jan 5, 12:00 AM");
    expect(clockOf("2026-11-14T12:34:56Z", "zh-CN")).toBe("11月14日 12:34");
  });

  it("returns null for a missing timestamp and the raw value for an unparseable one", () => {
    expect(clockOf(null, "en")).toBeNull();
    expect(clockOf("", "en")).toBeNull();
    expect(clockOf("not-a-date", "en")).toBe("not-a-date");
    expect(clockOf("not-a-date", "zh-CN")).toBe("not-a-date");
  });
});

describe("eventClockOf", () => {
  it("formats the second-resolution wall clock in each shipped locale, in UTC", () => {
    expect(eventClockOf("2026-11-14T12:34:56Z", "en")).toBe("12:34:56 PM");
    expect(eventClockOf("2026-01-05T03:04:05Z", "en")).toBe("03:04:05 AM");
    expect(eventClockOf("2026-11-14T12:34:56Z", "zh-CN")).toBe("12:34:56");
    expect(eventClockOf("2026-01-05T03:04:05Z", "zh-CN")).toBe("03:04:05");
  });

  it("returns null for a missing timestamp and the raw value for an unparseable one", () => {
    expect(eventClockOf(null, "en")).toBeNull();
    expect(eventClockOf("", "zh-CN")).toBeNull();
    expect(eventClockOf("garbage", "en")).toBe("garbage");
  });
});

describe("counterLine", () => {
  it("joins the present parts in order and drops null and empty ones", () => {
    expect(counterLine(["turns", null, "tools"])).toBe("turns · tools");
    expect(counterLine([null, "", "tools"])).toBe("tools");
    expect(counterLine(["only"])).toBe("only");
    expect(counterLine([])).toBe("");
    expect(counterLine([null, ""])).toBe("");
  });
});

describe("countersLine", () => {
  it("joins turns, tools and cost with the shipped English copy", () => {
    expect(countersLine({ turns: 1234, toolCalls: 5678, costUsd: 0.004 }, english.label, "en")).toBe(
      "1,234 turns · 5,678 tools · $0.0040",
    );
  });

  it("joins turns, tools and cost with the shipped Chinese copy", () => {
    expect(countersLine({ turns: 1234, toolCalls: 5678, costUsd: 0.004 }, chinese.label, "zh-CN")).toBe(
      "1,234 轮 · 5,678 次工具调用 · $0.0040",
    );
  });

  it("keeps zero counters visible", () => {
    expect(countersLine({ turns: 0, toolCalls: 0, costUsd: 0 }, english.label, "en")).toBe(
      "0 turns · 0 tools · $0",
    );
  });

  it("omits the counters a run does not report", () => {
    expect(countersLine({ turns: null, toolCalls: 1000, costUsd: null }, english.label, "en")).toBe(
      "1,000 tools",
    );
    expect(countersLine({ turns: null, toolCalls: null, costUsd: null }, english.label, "en")).toBe("");
  });
});

describe("usageLabel", () => {
  const usage = (overrides: Partial<RunModelUsage>): RunModelUsage => ({
    provider: null,
    model: null,
    api: null,
    messages: 0,
    ...overrides,
  });

  it("joins provider and model, or returns the single side", () => {
    expect(usageLabel(usage({ provider: "anthropic", model: "claude-opus-4" }))).toBe(
      "anthropic/claude-opus-4",
    );
    expect(usageLabel(usage({ provider: "openai" }))).toBe("openai");
    expect(usageLabel(usage({ model: "gpt-5" }))).toBe("gpt-5");
  });

  it("returns null when the usage names neither side and for no usage at all", () => {
    expect(usageLabel(usage({ api: "messages", messages: 3 }))).toBeNull();
    expect(usageLabel(null)).toBeNull();
  });
});

describe("firstUsage", () => {
  it("returns the first observed usage and null when none was observed", () => {
    const first: RunModelUsage = { provider: "anthropic", model: "claude-opus-4", api: null, messages: 5 };
    const model: RunModel = {
      requested: null,
      requestedProvider: null,
      requestedModel: null,
      thinking: null,
      observed: [first, { provider: "openai", model: "gpt-5", api: null, messages: 2 }],
    };
    expect(firstUsage(model)).toEqual(first);
    expect(firstUsage({ ...model, observed: [] })).toBeNull();
  });
});
