import { defineRpc } from "@getpaseo/plugin";
import { z } from "zod";

/** Run state as written by the launcher in `state.json`. A missing file is `unknown`, never success. */
export const RUN_STATES = ["running", "done", "killed", "failed", "unknown"] as const;
/** Liveness derived from pids, `lock`, and `finalized`; `settled` means the launcher finalized the run. */
export const RUN_LIVENESS = ["running", "settled", "stale", "unknown"] as const;
export const RUN_ROOT_SOURCES = ["setting", "env", "xdg", "home", "localappdata", "default"] as const;
export const COUNTER_SOURCES = ["state", "events", "none"] as const;
export const LIVENESS_PROBES = ["posix", "win32", "unavailable"] as const;
/** Machine-readable per-run diagnostics; the client resolves them to text. */
export const RUN_WARNINGS = [
  "state-missing",
  "state-unreadable",
  "no-lock",
  "no-pids",
  "liveness-unknown",
  "log-unreadable",
  "log-truncated",
] as const;

export const runEventSchema = z.object({
  type: z.string(),
  at: z.string().nullable(),
  tool: z.string().nullable(),
  intent: z.string().nullable(),
  detail: z.string().nullable(),
  role: z.string().nullable(),
});

export const runSummarySchema = z.object({
  id: z.string(),
  date: z.string(),
  slug: z.string(),
  runDir: z.string(),
  name: z.string(),
  state: z.enum(RUN_STATES),
  liveness: z.enum(RUN_LIVENESS),
  finalized: z.boolean(),
  exitCode: z.number().nullable(),
  startedAt: z.string().nullable(),
  endedAt: z.string().nullable(),
  durationS: z.number().nullable(),
  elapsedS: z.number().nullable(),
  model: z.string().nullable(),
  thinking: z.string().nullable(),
  maxTime: z.string().nullable(),
  sessionId: z.string().nullable(),
  turns: z.number().nullable(),
  toolCalls: z.number().nullable(),
  costUsd: z.number().nullable(),
  countersFrom: z.enum(COUNTER_SOURCES),
  countersPartial: z.boolean(),
  currentTool: z.string().nullable(),
  currentToolIntent: z.string().nullable(),
  lastError: z.string().nullable(),
  errorCount: z.number(),
  answerChars: z.number().nullable(),
  hasAnswer: z.boolean(),
  eventsBytes: z.number(),
  eventsDroppedBytes: z.number(),
  eventsTruncated: z.boolean(),
  eventLines: z.number(),
  pids: z.object({ pid: z.number().nullable(), agentPid: z.number().nullable() }),
  livePids: z.array(z.number()),
  lastEventAt: z.string().nullable(),
  dirModifiedAt: z.string().nullable(),
  warnings: z.array(z.enum(RUN_WARNINGS)),
});

export const runPathSchema = z.object({
  label: z.string(),
  path: z.string(),
  exists: z.boolean(),
  bytes: z.number().nullable(),
});

export const eventStatsSchema = z
  .object({
    totalBytes: z.number().nullable(),
    retainedBytes: z.number().nullable(),
    droppedBytes: z.number().nullable(),
    truncated: z.boolean().nullable(),
  })
  .nullable();

export type RunEvent = z.infer<typeof runEventSchema>;
export type RunSummary = z.infer<typeof runSummarySchema>;
export type RunPath = z.infer<typeof runPathSchema>;
export type EventStats = z.infer<typeof eventStatsSchema>;
export type RunState = (typeof RUN_STATES)[number];
export type RunLiveness = (typeof RUN_LIVENESS)[number];
export type RunWarning = (typeof RUN_WARNINGS)[number];
export type RunRootSource = (typeof RUN_ROOT_SOURCES)[number];

export const listRuns = defineRpc({
  name: "runs.list",
  input: z.object({}),
  output: z.object({
    runRoot: z.string(),
    rootSource: z.enum(RUN_ROOT_SOURCES),
    rootExists: z.boolean(),
    candidates: z.array(
      z.object({ path: z.string(), source: z.enum(RUN_ROOT_SOURCES), exists: z.boolean() }),
    ),
    probe: z.enum(LIVENESS_PROBES),
    scannedAt: z.string(),
    runs: z.array(runSummarySchema),
    warnings: z.array(z.string()),
  }),
});

export const runDetail = defineRpc({
  name: "runs.detail",
  input: z.object({
    id: z.string(),
    tailLines: z.number().int().min(1).max(2000).optional(),
  }),
  output: z.object({
    found: z.boolean(),
    summary: runSummarySchema.nullable(),
    events: z.array(runEventSchema),
    answerTail: z.string().nullable(),
    stats: eventStatsSchema,
    paths: z.array(runPathSchema),
    scannedAt: z.string(),
  }),
});

/**
 * Bounded live tail. The client polls this while a run is selected; the server keeps one byte
 * offset per run, so each call reads only what the launcher appended since the previous call.
 * Paseo 0.15 has no plugin subscription transport, so polling is the available live channel and
 * it stops the moment the surface unmounts.
 */
export const followRun = defineRpc({
  name: "runs.follow",
  input: z.object({
    id: z.string(),
    tailLines: z.number().int().min(1).max(2000).optional(),
  }),
  output: z.object({
    found: z.boolean(),
    summary: runSummarySchema.nullable(),
    events: z.array(runEventSchema),
    answerTail: z.string().nullable(),
    scannedAt: z.string(),
  }),
});

export type ListRunsOutput = z.infer<typeof listRuns.output>;
export type RunDetailOutput = z.infer<typeof runDetail.output>;
export type FollowRunOutput = z.infer<typeof followRun.output>;
